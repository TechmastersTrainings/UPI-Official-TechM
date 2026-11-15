# TechMasters Payment Gateway

Standalone payment gateway platform owned and operated by **TechMasters Innovations Private Limited**.

| Component | Local URL | Stack |
|---|---|---|
| Frontend (console + hosted checkout) | http://localhost:5177 | React 18, Vite, plain CSS, axios |
| Backend API | http://localhost:8000 | FastAPI, SQLAlchemy 2, Alembic, Pydantic |
| API docs | http://localhost:8000/docs | OpenAPI / Swagger UI |
| Database | — | MySQL 8 (Aiven) in staging/production; SQLite for local dev without credentials |
| Cache / rate limits | — | Redis |

Architecture, schema, API spec, provider design, sandbox strategy and the phase plan are in
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Current status

**Phase 1 (Foundation): complete.**

- Project structure, FastAPI app, structured JSON logging, request IDs, uniform error envelope, security headers, CORS allow-list.
- Full relational schema (21 tables) as one Alembic migration, MySQL 8 compatible, with RBAC roles seeded.
- Auth: argon2id passwords, 15-minute JWT access tokens, rotating HttpOnly refresh cookie with reuse detection, lockout, Redis rate limiting, CSRF header check, RBAC.
- Super Admin dashboard on real aggregates (Live and Sandbox kept separate), daily trend chart, status summary, recent activity.
- Platform user management, audit log viewer, change password, light/dark theme, responsive layout.

**Phase 2 (Merchant management): complete.**

- Self-service merchant registration (business, address, contact/PAN/GSTIN, owner login) → `PENDING_REVIEW`.
- Business profile editing; Indian identifier validation (mobile, IFSC, PAN, GSTIN, PIN, UPI ID).
- Bank accounts: encrypted account numbers, masked display, duplicate detection, default per environment,
  activate/deactivate, audited reveal, TechMasters verification (re-verification on any identity change).
- Provider onboarding: DRAFT → SUBMITTED → APPROVED → TESTED → ACTIVE, credentials encrypted and never returned.
  A TEST-only sandbox configuration is created for every merchant; live configs require a live-capable provider.
- API credentials: `tm_test_` / `tm_live_` key IDs, secrets shown once and stored as HMAC, regenerate/revoke,
  merchant-level API on/off, request log viewer. Live keys only after live mode is enabled.
- Webhook endpoints per environment with platform-generated signing secrets (shown once, rotatable) and SSRF-safe URL rules.
- Super Admin merchant console: search/filter, approve/reject/suspend/reactivate, bank verification, provider approval,
  and live mode gated by a 7-item readiness checklist.

Phases 3–8 (payment engine, UPI/checkout, verification, sandbox, live, reporting) follow the plan in the architecture doc.

> Live payments are intentionally unreachable today: no live-capable payment provider is integrated yet (Phase 7 needs a
> signed agreement with an RBI-authorised payment aggregator or acquiring bank), so the readiness checklist cannot complete.

## Local setup

Prerequisites: Python 3.12, Node 20+, Redis. MySQL 8 is optional locally.

### Backend

```bash
cd backend
python3.12 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
cp .env.example .env
.venv/bin/python -m app.cli generate-env-secrets >> .env   # appended values override the blank ones
.venv/bin/alembic upgrade head
.venv/bin/python -m app.cli create-superadmin --email you@yourcompany.com --name "Your Name"   # prompts for password
.venv/bin/uvicorn app.main:app --reload --port 8000
```

### Frontend

```bash
cd frontend
npm install
cp .env.example .env
npm run dev          # http://localhost:5177
```

Open the console at `http://localhost:5177`, not `127.0.0.1`. The refresh cookie relies on the frontend and
API being same-site (`localhost`).

## Using Aiven MySQL

1. In the Aiven console, create the database (e.g. `techmasters_pg`) and download the CA certificate.
2. Set in the environment (or `backend/.env`):
   ```
   DATABASE_URL=mysql+pymysql://avnadmin:<password>@<host>.aivencloud.com:<port>/techmasters_pg?charset=utf8mb4
   DATABASE_SSL_CA=/path/to/ca.pem
   ```
3. `.venv/bin/alembic upgrade head`

The schema satisfies Aiven's `sql_require_primary_key`, uses `DATETIME(6)` in UTC, and keeps every identifier
within MySQL's 64-character limit (enforced by a test). To run the test suite against MySQL:
`TEST_DATABASE_URL=mysql+pymysql://... .venv/bin/python -m pytest`. The suite downgrades and re-upgrades the schema,
so point it at a **dedicated test database**.

## Production checklist

`APP_ENV=production` refuses to start unless `JWT_SECRET` (≥ 32 chars), `ENCRYPTION_KEYS` and `HASH_PEPPER` are set,
`COOKIE_SECURE=true`, and `DATABASE_URL` is not SQLite. Also:

- Serve both apps over HTTPS on sibling subdomains (e.g. `console.` and `api.`), and set `CORS_ORIGINS` and `FRONTEND_BASE_URL` to match.
- Run uvicorn behind a reverse proxy with `--proxy-headers --forwarded-allow-ips=<proxy ip>` so client IPs in audit logs are correct.
- Keep secrets in a secret manager, not in `.env` files. Rotate encryption keys by prepending a new key to `ENCRYPTION_KEYS`.

## Tests

```bash
cd backend && .venv/bin/python -m pytest     # 73 tests: migrations, security, auth, RBAC, dashboard, merchant onboarding
cd frontend && npm test
```
