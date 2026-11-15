import logging
import time
import uuid

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from sqlalchemy import text

from app.api.admin.merchants import router as admin_merchants_router
from app.api.admin.routes import router as admin_router
from app.api.auth.routes import router as auth_router
from app.api.admin.payments import router as admin_payments_router
from app.api.merchant.payments import router as merchant_payments_router
from app.api.merchant.routes import router as merchant_router
from app.api.v1.routes import router as v1_router
from app.core.config import get_settings
from app.core.errors import install_exception_handlers
from app.core.logging import configure_logging, request_id_ctx
from app.core.redis import redis_healthy
from app.db.session import get_engine, get_sessionmaker
from app.models import ApiRequestLog

log = logging.getLogger("app.request")
API_PREFIX = "/api/v1/"


def _write_api_log(request: Request, status: int, latency_ms: int, rid: str) -> None:
    """Gateway API access log, shown to the merchant under "API request logs". Only requests that
    authenticated as a merchant are stored; anonymous failures go to the application log only."""
    client = getattr(request.state, "api_client", None)
    if not client:
        return
    try:
        with get_sessionmaker()() as db:
            db.add(ApiRequestLog(
                merchant_id=client["merchant_id"], credential_id=client["credential_id"],
                environment=client["environment"], method=request.method, path=request.url.path[:255],
                status_code=status, latency_ms=latency_ms,
                ip_address=request.client.host if request.client else None,
                idempotency_key=(request.headers.get("idempotency-key") or "")[:100] or None,
                request_id=rid, error_code=getattr(request.state, "error_code", None),
            ))
            db.commit()
    except Exception:
        log.exception("api_request_log_failed")

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
}


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.LOG_LEVEL)

    app = FastAPI(
        title="TechMasters Payment Gateway API",
        version="0.3.0",
        description=(
            "Payment gateway platform owned and operated by TechMasters Innovations Private Limited.\n\n"
            "* `/api/auth` — dashboard authentication (JWT + rotating refresh cookie)\n"
            "* `/api/admin` — Super Admin console\n"
            "* `/api/merchant` — merchant console (registration, profile, bank accounts, providers, keys, webhooks)\n"
            "* `/api/v1` — merchant-facing gateway API (HTTP Basic: API key id + secret)\n\n"
            "Amounts are integers in minor units (paise). Timestamps are UTC ISO-8601."
        ),
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "X-TM-Client", "X-Request-Id"],
        expose_headers=["X-Request-Id"],
    )

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        incoming = request.headers.get("x-request-id", "")
        rid = incoming if 8 <= len(incoming) <= 64 and incoming.replace("-", "").isalnum() else uuid.uuid4().hex
        token = request_id_ctx.set(rid)
        start = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            response.headers["X-Request-Id"] = rid
            for k, v in SECURITY_HEADERS.items():
                response.headers.setdefault(k, v)
            return response
        finally:
            if request.url.path.startswith(API_PREFIX):
                await run_in_threadpool(
                    _write_api_log, request, status, int((time.perf_counter() - start) * 1000), rid
                )
            log.info(
                "request",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "status": status,
                    "duration_ms": round((time.perf_counter() - start) * 1000, 1),
                    "client_ip": request.client.host if request.client else None,
                },
            )
            request_id_ctx.reset(token)

    install_exception_handlers(app)
    app.include_router(auth_router)
    app.include_router(admin_router)
    app.include_router(admin_merchants_router)
    app.include_router(merchant_router)
    app.include_router(merchant_payments_router)
    app.include_router(admin_payments_router)
    app.include_router(v1_router)

    @app.get("/health", tags=["Health"])
    def health():
        return {"status": "ok"}

    @app.get("/health/ready", tags=["Health"])
    def ready():
        checks = {"database": False, "redis": redis_healthy() if settings.REDIS_URL else None}
        try:
            with get_engine().connect() as conn:
                conn.execute(text("SELECT 1"))
            checks["database"] = True
        except Exception:
            log.exception("readiness_db_failed")
        ok = checks["database"] and checks["redis"] is not False
        return JSONResponse(status_code=200 if ok else 503, content={"status": "ok" if ok else "degraded", "checks": checks})

    return app


app = create_app()
