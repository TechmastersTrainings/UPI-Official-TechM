"""Super Admin dashboard aggregates. Every number comes from a database query; nothing is estimated.

"Collection" means payments verified as successful with the provider (Layer 1). It does NOT mean
money credited to a bank account — that is tracked separately by reconciliation (Layer 2)."""

from datetime import date, datetime, timedelta, timezone

from sqlalchemy import case, func, literal_column, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.types import utcnow
from app.models import AuditLog, Merchant, Payment, Refund, Transaction
from app.models.enums import (
    COLLECTED_STATUSES,
    IN_FLIGHT_STATUSES,
    MerchantStatus,
    PaymentStatus,
    RefundStatus,
    TransactionType,
)


def _tz() -> timezone:
    return timezone(timedelta(minutes=get_settings().REPORTING_UTC_OFFSET_MINUTES))


def _local_day_start_utc(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, tzinfo=_tz()).astimezone(timezone.utc)


def _local_date_expr(db: Session, column):
    """SQL expression for the reporting-timezone calendar date of a UTC DATETIME column."""
    minutes = get_settings().REPORTING_UTC_OFFSET_MINUTES
    dialect = db.get_bind().dialect.name
    if dialect == "mysql":
        return func.date(func.date_add(column, literal_column(f"INTERVAL {int(minutes)} MINUTE")))
    if dialect == "sqlite":
        return func.date(column, f"{int(minutes):+d} minutes")
    if dialect == "postgresql":
        return func.date(column + literal_column(f"INTERVAL '{int(minutes)} minutes'"))
    raise NotImplementedError(dialect)


def _vals(statuses) -> list[str]:
    return [s.value for s in statuses]


def summary(db: Session, environment: str) -> dict:
    now_local = utcnow().astimezone(_tz())
    today_start = _local_day_start_utc(now_local.date())
    month_start = _local_day_start_utc(now_local.date().replace(day=1))

    merchants = db.execute(
        select(
            func.count(),
            func.coalesce(func.sum(case((Merchant.status == MerchantStatus.ACTIVE, 1), else_=0)), 0),
            func.coalesce(func.sum(case((Merchant.live_enabled.is_(True), 1), else_=0)), 0),
        ).select_from(Merchant)
    ).one()

    collected = Payment.status.in_(_vals(COLLECTED_STATUSES))
    p = db.execute(
        select(
            func.count(),
            func.coalesce(func.sum(case((collected, 1), else_=0)), 0),
            func.coalesce(func.sum(case((Payment.status == PaymentStatus.FAILED, 1), else_=0)), 0),
            func.coalesce(func.sum(case((Payment.status.in_(_vals(IN_FLIGHT_STATUSES)), 1), else_=0)), 0),
            func.coalesce(func.sum(case((Payment.status == PaymentStatus.EXPIRED, 1), else_=0)), 0),
            func.coalesce(func.sum(case((Payment.status == PaymentStatus.CANCELLED, 1), else_=0)), 0),
            func.coalesce(func.sum(case((collected, Payment.amount), else_=0)), 0),
            func.coalesce(func.sum(case((collected, Payment.amount_refunded), else_=0)), 0),
            func.coalesce(
                func.sum(case(((collected) & (Payment.confirmed_at >= today_start), Payment.amount), else_=0)), 0
            ),
            func.coalesce(
                func.sum(case(((collected) & (Payment.confirmed_at >= month_start), Payment.amount), else_=0)), 0
            ),
        ).where(Payment.environment == environment)
    ).one()

    by_status = dict(
        db.execute(
            select(Payment.status, func.count()).where(Payment.environment == environment).group_by(Payment.status)
        ).all()
    )

    upi_txn_count = db.scalar(
        select(func.count())
        .select_from(Transaction)
        .where(Transaction.environment == environment, Transaction.type == TransactionType.PAYMENT)
    )

    r = db.execute(
        select(
            func.count(),
            func.coalesce(func.sum(case((Refund.status == RefundStatus.SUCCESS, Refund.amount), else_=0)), 0),
            func.coalesce(
                func.sum(case((Refund.status.in_([RefundStatus.PENDING, RefundStatus.PROCESSING]), 1), else_=0)), 0
            ),
        ).where(Refund.environment == environment)
    ).one()

    env_counts = dict(db.execute(select(Payment.environment, func.count()).group_by(Payment.environment)).all())

    return {
        "environment": environment,
        "currency": "INR",
        "generated_at": utcnow(),
        "merchants": {"total": merchants[0], "active": int(merchants[1]), "live_enabled": int(merchants[2])},
        "payments": {
            "total": p[0],
            "successful": int(p[1]),
            "failed": int(p[2]),
            "pending": int(p[3]),
            "expired": int(p[4]),
            "cancelled": int(p[5]),
            "by_status": {s.value: int(by_status.get(s.value, 0)) for s in PaymentStatus},
        },
        "collection": {
            "total_amount": int(p[6]),
            "refunded_amount": int(p[7]),
            "net_amount": int(p[6]) - int(p[7]),
            "today_amount": int(p[8]),
            "month_amount": int(p[9]),
        },
        "upi_transactions": int(upi_txn_count or 0),
        "refunds": {"total": r[0], "succeeded_amount": int(r[1]), "in_progress": int(r[2])},
        "environment_counts": {"TEST": int(env_counts.get("TEST", 0)), "LIVE": int(env_counts.get("LIVE", 0))},
    }


def timeseries(db: Session, environment: str, days: int) -> dict:
    today = utcnow().astimezone(_tz()).date()
    first_day = today - timedelta(days=days - 1)
    start_utc = _local_day_start_utc(first_day)
    day = _local_date_expr(db, Payment.created_at).label("day")
    collected = Payment.status.in_(_vals(COLLECTED_STATUSES))

    rows = db.execute(
        select(
            day,
            func.count(),
            func.coalesce(func.sum(case((collected, 1), else_=0)), 0),
            func.coalesce(func.sum(case((Payment.status == PaymentStatus.FAILED, 1), else_=0)), 0),
            func.coalesce(func.sum(case((collected, Payment.amount), else_=0)), 0),
        )
        .where(Payment.environment == environment, Payment.created_at >= start_utc)
        .group_by(day)
    ).all()
    by_day = {str(r[0]): r for r in rows}

    points = []
    for i in range(days):
        d = (first_day + timedelta(days=i)).isoformat()
        r = by_day.get(d)
        points.append(
            {
                "date": d,
                "created": int(r[1]) if r else 0,
                "successful": int(r[2]) if r else 0,
                "failed": int(r[3]) if r else 0,
                "collected_amount": int(r[4]) if r else 0,
            }
        )
    return {"environment": environment, "days": days, "timezone_offset_minutes": get_settings().REPORTING_UTC_OFFSET_MINUTES, "points": points}


def recent_activity(db: Session, environment: str, limit: int = 10) -> dict:
    payments = db.execute(
        select(
            Payment.id, Payment.merchant_reference, Payment.amount, Payment.currency, Payment.status,
            Payment.created_at, Merchant.business_name,
        )
        .join(Merchant, Merchant.id == Payment.merchant_id)
        .where(Payment.environment == environment)
        .order_by(Payment.created_at.desc())
        .limit(limit)
    ).all()
    audits = db.scalars(select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit)).all()
    return {
        "recent_payments": [
            {
                "id": r.id, "merchant_reference": r.merchant_reference, "amount": r.amount, "currency": r.currency,
                "status": r.status, "created_at": r.created_at, "merchant_name": r.business_name,
            }
            for r in payments
        ],
        "recent_audit": [
            {
                "id": a.id, "action": a.action, "actor_label": a.actor_label, "entity_type": a.entity_type,
                "entity_id": a.entity_id, "created_at": a.created_at,
            }
            for a in audits
        ],
    }
