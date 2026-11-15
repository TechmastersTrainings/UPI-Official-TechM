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

**Phase 3 (Payment engine): complete.**

- Gateway API `/api/v1` with HTTP Basic API-key auth (the key selects TEST or LIVE), per-key rate limit,
  auth-failure throttling and a per-merchant access log.
- `POST /payments/create` with mandatory `Idempotency-Key`: identical retries replay the original payment,
  a different body under the same key returns `409 IDEMPOTENCY_CONFLICT`; `merchant_reference` unique per environment.
  Races are settled by database unique constraints.
- Get / status / list / cancel. Payment state machine with allowed transitions *and* allowed sources (only the
  provider can ever mark a payment `SUCCESS`), an immutable event timeline, and optimistic locking.
- Expiry of unpaid payments, both on read and via the worker (`python -m app.workers`, or `python -m app.cli run-jobs`).
- Payments list and detail with timeline in the merchant console (with cancel) and the admin console.

**Phase 4 (UPI & hosted checkout): complete.**

- Provider adapter contract and registry; the registry refuses any non-live-capable adapter for LIVE
  (checked against both the code and the database).
- Sandbox adapter (TEST only): generates non-payable `tmsandbox://` QR/intent content.
- `POST /api/v1/payments/{id}/initiate` for merchants who render their own QR / intent screen. Every payment
  now has a `checkout_url`.
- Hosted checkout at `/checkout/{token}`: Pay button → QR (striped "TEST MODE — NO REAL MONEY" frame in sandbox),
  UPI app button in live, a countdown on the server's clock, and status polling. The page shows only statuses the
  server returns. The return link carries only `payment_id`, so the merchant must verify the payment server-side.
- Payments with an open session expire only once the provider confirms nothing was collected.
- The console payment detail shows provider sessions and the checkout link.

**Phase 5 (Verification): complete.**

- Verification engine: the only path to `SUCCESS`. Provider amount, currency and transaction id are cross-checked
  before success. Mismatches are recorded and not applied.
- Provider callbacks at `POST /api/v1/providers/{code}/callback`: stored before processing, signature-verified
  against the merchant's provider configuration, and de-duplicated per provider event. Forged callbacks are stored and ignored.
- Status polling worker with backoff, `POST /api/v1/payments/{id}/verify`, and provider-confirmed expiry.
- Ledger (`transactions`, one row per provider transaction) and `GET /api/v1/transactions`. Late or second payments are
  recorded and flagged `INVESTIGATION_REQUIRED`, never silently applied.
- Outbound webhooks via an outbox. Signed `X-TM-Signature: v1=HMAC(secret, "ts.body")`; retries at 1m/5m/15m/1h/6h/24h/24h,
  then FAILED. SSRF-checked at send time, no redirects. Console delivery log with payload view and redelivery. A test event
  (`POST /api/v1/webhooks/test` or the console button) validates the endpoint for live readiness.

**Phase 6 (Sandbox & refunds): complete.**

- Stateful sandbox simulator: test outcomes by amount (`x.00` success, `x.01` fail, `x.02` processing, `x.03` expires,
  other = manual) and a Simulate panel on the test checkout and API. Simulations send signed callbacks through the real
  verification pipeline. Refused for live payments.
- Refunds: `POST /api/v1/refunds` (Idempotency-Key, full/partial, one in progress per payment, never above the balance),
  refund status polling, REFUND ledger rows, `payment.refund_initiated` / `payment.refunded` / `payment.refund_failed`
  webhooks, and a Refund button on the console payment page.
- A full sandbox lifecycle test: create → checkout → pay → verify → webhooks → partial and full refund.

Phases 7–8 (live provider, reporting and reconciliation) follow the plan in the architecture doc.

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
.venv/bin/python -m app.workers                 # background jobs (expiry, status/refund polling, webhook delivery), in a second terminal
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
cd backend && .venv/bin/python -m pytest     # 204 tests: migrations, security, auth, RBAC, dashboard, onboarding, payments, checkout, verification, webhooks, sandbox, refunds
cd frontend && npm test
```
