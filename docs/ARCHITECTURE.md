# TechMasters Payment Gateway — Architecture

Owner: TechMasters Innovations Private Limited
Status: Phases 1 (Foundation), 2 (Merchant management), 3 (Payment engine), 4 (UPI & checkout) and 5 (Verification) implemented. Later phases are specified here and built incrementally.

This document is the reference for the eight pre-implementation deliverables:
directory structure, backend architecture, frontend architecture, database schema,
API specification, provider integration architecture, sandbox strategy and phase plan.

---

## 0. Ground rules that shape every design decision

1. **The backend owns payment state.** Status only changes through the state machine in
   `services/payment_state.py`, driven by authenticated provider responses or verified
   provider webhooks. Frontend redirects, query strings and client-sent amounts are never
   trusted.
2. **Payment confirmation ≠ bank credit.** "Provider says SUCCESS" (Layer 1) and "money
   landed in the merchant's bank account" (Layer 2, reconciliation) are tracked in separate
   tables with separate statuses. The UI never conflates them.
3. **No fabricated providers.** The only provider shipped is `sandbox`, which is hard-wired
   to the TEST environment and refuses to run in LIVE. Real providers (PSP / acquiring bank)
   are added as adapters once TechMasters has a signed integration agreement and real API
   documentation and credentials. Until then, LIVE mode can't be turned on for any merchant.
4. **Test and live are fully isolated.** Every merchant-scoped row carries `environment`
   (`TEST` | `LIVE`). Credentials are environment-bound (`tm_test_…` / `tm_live_…`), and a
   test key can never read or write live rows.
5. **Bank details or a VPA alone never authorise live collection.** Live mode requires an
   approved provider configuration (provider-side merchant onboarding), a passed integration
   test, a validated webhook, and Super Admin approval.

---

## 1. Directory structure

```
UPI-Techmasters-Standalone/
├── docs/
│   └── ARCHITECTURE.md
├── backend/                       # FastAPI service — deployable on its own
│   ├── app/
│   │   ├── main.py                # app factory, middleware, router mounting
│   │   ├── cli.py                 # operational commands (create-superadmin, seed-roles)
│   │   ├── core/
│   │   │   ├── config.py          # pydantic-settings; all secrets from env
│   │   │   ├── security.py        # argon2 hashing, JWT, refresh tokens
│   │   │   ├── crypto.py          # MultiFernet field encryption (key rotation)
│   │   │   ├── logging.py         # structured JSON logs + request-id context
│   │   │   ├── errors.py          # error envelope + exception handlers
│   │   │   ├── rate_limit.py      # Redis fixed-window limiter (memory fallback for tests)
│   │   │   ├── redis.py
│   │   │   └── masking.py         # PII / secret masking for logs and audit
│   │   ├── db/
│   │   │   ├── base.py            # DeclarativeBase, mixins, id generation
│   │   │   ├── types.py           # UTCDateTime (portable MySQL/SQLite)
│   │   │   └── session.py         # engine (MySQL SSL), SessionLocal
│   │   ├── models/                # SQLAlchemy models, one module per aggregate
│   │   ├── schemas/               # Pydantic request/response models
│   │   ├── services/              # business logic (no FastAPI imports)
│   │   ├── providers/             # provider adapter interface + implementations  [Phase 4]
│   │   ├── workers/               # verification / webhook / reconciliation loops [Phase 5]
│   │   └── api/
│   │       ├── deps.py            # auth dependencies, RBAC guards
│   │       ├── auth/              # /api/auth/*        (dashboard users, JWT)
│   │       ├── admin/             # /api/admin/*       (Super Admin console)
│   │       ├── merchant/          # /api/merchant/*    (merchant console)          [Phase 2]
│   │       └── v1/                # /api/v1/*          (public gateway API, key auth) [Phase 3]
│   ├── alembic/                   # migrations (MySQL 8 target)
│   ├── tests/
│   ├── requirements.txt
│   └── .env.example
└── frontend/                      # React + Vite SPA — deployable on its own (static)
    ├── src/
    │   ├── api/                   # axios client, token refresh, endpoint modules
    │   ├── auth/                  # AuthContext, ProtectedRoute, role guards
    │   ├── components/            # reusable UI: StatCard, DataTable, StatusBadge, Chart…
    │   ├── layouts/               # AppLayout (sidebar + topbar)
    │   ├── pages/                 # route screens grouped by module
    │   ├── theme/                 # light/dark theme provider
    │   └── styles/                # plain CSS: tokens, base, components
    ├── vite.config.js             # dev server on :5177
    └── .env.example
```

---

## 2. Backend architecture

**Layers.** `api` (HTTP, auth, validation) → `services` (business rules, transactions) →
`models` (persistence). Services take a `Session` and never import FastAPI, so the worker
process and CLI reuse them unchanged.

**Processes.**

| Process | Command | Role |
|---|---|---|
| API | `uvicorn app.main:app --port 8000` | All HTTP endpoints |
| Worker | `python -m app.workers` | Payment expiry, provider status polling with backoff, provider-confirmed session expiry, outbound webhook delivery + retries; reconciliation imports (Phase 8) |

**Durable jobs.** The database is the queue of record: `webhook_deliveries.next_attempt_at`,
pending payments (`status IN (INITIATED, PENDING, PROCESSING)`) and settlement imports are
picked up by the worker with `SELECT … FOR UPDATE SKIP LOCKED` (MySQL 8 supports it). Redis
is used for rate limiting, short-lived distributed locks and caching, never as the only
copy of a job. A Redis flush can't lose a payment or a webhook.

**Authentication.**

* *Dashboard users* (Super Admin, platform staff, merchant users): email + password
  (argon2id) → short-lived JWT access token (15 min, kept in memory by the SPA) plus a
  rotating refresh token in an `HttpOnly; SameSite=Lax` cookie scoped to `/api/auth`. Refresh
  tokens are stored hashed in `user_sessions`, and reusing a rotated token revokes the
  session. Account lockout after repeated failures, and login is rate limited per IP and per email.
* *Gateway API clients* (merchant servers): HTTP Basic `key_id:secret`. `key_id` is public
  (`tm_test_…`/`tm_live_…`) and selects the environment. Secrets are 256-bit random and stored
  as HMAC-SHA256(server pepper, secret). They're shown once at creation and can't be recovered.

**RBAC.** Roles: `SUPER_ADMIN`, `PLATFORM_ADMIN`, `PLATFORM_SUPPORT`, `MERCHANT_ADMIN`,
`MERCHANT_DEVELOPER`, `MERCHANT_VIEWER`. Permissions are checked by dependency guards.
Merchant users are always scoped to their own `merchant_id` at query level.

**Encryption at rest.** Bank account numbers, provider credentials and webhook signing
secrets are encrypted with `MultiFernet` (AES-128-CBC + HMAC-SHA256). Keys come from
`ENCRYPTION_KEYS` (comma-separated, newest first) so keys can be rotated without downtime.
Only masked forms (`XXXX1234`) are returned by default. Unmasking bank details requires an
elevated role and writes an audit entry.

**Cross-cutting.** Request-ID middleware, JSON structured logs with masking, a uniform error
envelope `{"error": {"code", "message", "request_id", "details"}}`, CORS allow-list from
env, security headers, and an audit log for every state-changing admin/merchant action.

**Idempotency.** `POST /api/v1/payments/create` and `POST /api/v1/refunds` require an
`Idempotency-Key`. The uniqueness constraint `(merchant_id, environment, idempotency_key)`
plus a stored request hash returns the original response for identical retries, and returns
`409 IDEMPOTENCY_CONFLICT` for a different body under the same key. Provider callbacks are
de-duplicated by `(provider_code, provider_event_id)`. Status transitions use optimistic
locking (`payments.version`) so concurrent webhook + poll can't double-apply.

---

## 3. Frontend architecture

* **Routing** (`react-router-dom`): `/login`, `/admin/*` (platform roles), `/merchant/*`
  (merchant roles, Phase 2), `/checkout/:token` (public hosted checkout, Phase 4).
* **API client**: one axios instance (`withCredentials`) with an interceptor that attaches the
  in-memory access token and, on `401 TOKEN_EXPIRED`, performs a single-flight refresh, then
  retries.
* **State**: React context for auth and theme, with local component state for screens. There is
  no global store until a screen actually needs one.
* **Styling**: plain CSS with design tokens as CSS custom properties. Light/dark themes swap
  token values on `[data-theme]`, and the default follows the OS.
* **Charts**: small dependency-free SVG components fed by backend aggregates.
* **Rule**: a navigation item or button exists only when its backend endpoint exists. Phase
  gating is done by adding routes as phases land, never by shipping dead UI.

---

## 4. Database schema (MySQL 8 / Aiven)

Conventions: string primary keys with type prefixes (`mer_`, `pay_`, `txn_`, …; 24 random
chars), money stored as **integer minor units** (paise) in `BIGINT`, `currency CHAR(3)`,
timestamps in UTC as `DATETIME(6)`, status/enum columns as `VARCHAR(32)` validated in code
(no MySQL `ENUM`, so adding a status doesn't need a table rebuild). JSON columns use native
`JSON`. Every table has a primary key (Aiven enforces `sql_require_primary_key`).

| Table | Purpose | Key columns / constraints |
|---|---|---|
| `roles` | RBAC roles | `name` UNIQUE |
| `users` | Dashboard users | `email` UNIQUE, `role_id` FK, `merchant_id` FK NULL, lockout fields, `token_version` |
| `user_sessions` | Refresh-token sessions | `refresh_token_hash` UNIQUE, `user_id` FK, `expires_at`, `revoked_at` |
| `merchants` | Merchant account | `business_email` UNIQUE, `status`, `live_enabled`, `api_access_enabled` |
| `merchant_profiles` | Business details 1:1 | `merchant_id` UNIQUE FK, address, contact person, business type |
| `merchant_bank_accounts` | Payout/collection accounts | `merchant_id` FK, `environment`, `account_number_enc`, `account_number_last4`, `ifsc`, `upi_vpa`, `is_default`, `verification_status` |
| `payment_providers` | Provider catalogue | `code` UNIQUE, capability flags, `is_live_capable` |
| `provider_configurations` | Merchant ↔ provider onboarding | `(merchant_id, provider_id, environment)` UNIQUE, `provider_merchant_id`, `credentials_enc`, `status` (DRAFT→SUBMITTED→APPROVED→TESTED→ACTIVE/DISABLED) |
| `api_credentials` | Gateway API keys | `key_id` UNIQUE, `secret_hash`, `environment`, `status`, `last_used_at` |
| `webhook_configurations` | Merchant webhook endpoints | `(merchant_id, environment)`, `url`, `signing_secret_enc`, `events` JSON, `validated_at` |
| `payments` | Payment orders | `(merchant_id, environment, idempotency_key)` UNIQUE, `(merchant_id, environment, merchant_reference)` UNIQUE, `checkout_token` UNIQUE, `amount`, `amount_refunded`, `status`, `version`, `expires_at` |
| `payment_attempts` | Provider sessions per payment | `payment_id` FK, `provider_code`, `provider_session_ref`, QR/intent payload, `status` |
| `transactions` | Verified money-movement ledger | `(provider_code, provider_transaction_id)` UNIQUE, `type` (PAYMENT/REFUND), `amount`, `verified_at`, `verification_method` |
| `payment_events` | Immutable status timeline | `payment_id` FK, `from_status`, `to_status`, `source`, `payload` |
| `provider_callbacks` | Inbound provider webhooks | `(provider_code, provider_event_id)` UNIQUE, `signature_valid`, `processed_at` |
| `refunds` | Refunds | `payment_id` FK, `(merchant_id, environment, idempotency_key)` UNIQUE, `amount`, `status`, `provider_refund_ref` |
| `webhook_deliveries` | Outbound webhook outbox | `event_id` UNIQUE, `status`, `attempt_count`, `next_attempt_at` INDEX, last response |
| `settlements` | Provider settlement batches | `(provider_code, settlement_reference)` UNIQUE, gross/fees/tax/net, `utr`, `status` |
| `reconciliation_records` | Payment ↔ settlement ↔ bank credit | `transaction_id` UNIQUE FK, `settlement_id` FK NULL, `status`, expected vs credited amount |
| `audit_logs` | Who did what | actor, `action`, `entity_type/id`, masked before/after, IP; INDEX (`entity_type`,`entity_id`), (`created_at`) |
| `api_request_logs` | Gateway API access log | `credential_id`, method, path, status, latency, `request_id`; INDEX (`merchant_id`,`created_at`) |

Relationships: `merchants 1─1 merchant_profiles`, `merchants 1─n {users, bank_accounts,
provider_configurations, api_credentials, webhook_configurations, payments, refunds,
settlements}`, `payments 1─n {attempts, events, refunds, transactions}`,
`transactions 1─1 reconciliation_records n─1 settlements`.

Payment states (backend-controlled):

```
CREATED ─▶ INITIATED ─▶ PENDING ─▶ PROCESSING ─▶ SUCCESS ─▶ REFUND_PENDING ─▶ PARTIALLY_REFUNDED ─▶ REFUNDED
   │           │           │            │                         │                 ▲
   │           ├───────────┴────────────┴─▶ FAILED                └─────────────────┘
   ├─▶ CANCELLED (merchant, before INITIATED completes)
   └─────────────────────────────────────▶ EXPIRED (worker, past expires_at with no success)
```

Implemented in `services/payment_state.py`. Besides the allowed next statuses, each target status
has an allowed set of *sources*: only `PROVIDER_CALLBACK` / `PROVIDER_POLL` can set `SUCCESS`,
`PENDING`, `PROCESSING`; only `SYSTEM` can set `EXPIRED`; only the merchant or an admin can cancel.
`PROCESSING` can't expire (money may be moving). Automatic expiry only touches `CREATED` payments;
once a provider session exists, expiry must first ask the provider (Phase 5).

`SUCCESS`, `FAILED`, `EXPIRED`, `CANCELLED` are terminal for the payment leg. A late
provider success on an `EXPIRED` payment is never silently applied. It raises
`INVESTIGATION_REQUIRED` on reconciliation for operator action.

Reconciliation states: `NOT_RECONCILED → MATCHED → SETTLEMENT_PENDING → SETTLED`, with
`MISMATCH` and `INVESTIGATION_REQUIRED` as exception states.

---

## 5. API specification

All responses are JSON. Errors use the envelope above. The interactive spec is at `/docs`.

### 5.1 Dashboard auth — `/api/auth` (Phase 1)
| Method | Path | Notes |
|---|---|---|
| POST | `/api/auth/login` | email, password → access token, sets refresh cookie |
| POST | `/api/auth/refresh` | rotates refresh cookie → new access token |
| POST | `/api/auth/logout` | revokes current session |
| GET | `/api/auth/me` | current user + role + permissions |
| POST | `/api/auth/change-password` | revokes all other sessions |

### 5.2 Super Admin — `/api/admin` (Phase 1 +)
| Method | Path | Phase |
|---|---|---|
| GET | `/api/admin/dashboard/summary?environment=LIVE\|TEST` | 1 |
| GET | `/api/admin/dashboard/timeseries?environment=&days=` | 1 |
| GET | `/api/admin/dashboard/activity` | 1 |
| GET | `/api/admin/audit-logs` | 1 |
| GET/POST/PATCH | `/api/admin/users` | 1 |
| GET/PATCH | `/api/admin/merchants[/{id}]` (approve, suspend, enable live) | 2 |
| GET/PATCH | `/api/admin/provider-configurations/{id}` (approve onboarding) | 2 |
| GET | `/api/admin/transactions`, `/export.csv` | 5/8 |
| GET/POST | `/api/admin/settlements`, `/reconciliation` | 8 |

### 5.3 Merchant console — `/api/merchant` (Phase 2 +)
Registration, profile, bank accounts (CRUD, default, activate), provider configurations,
API credentials (generate / regenerate / revoke — secret returned once), webhook config and
test, transactions, refunds, request logs.

### 5.4 Public gateway API — `/api/v1` (Phase 3 +, Basic auth with API key)
| Method | Path | Notes |
|---|---|---|
| POST | `/api/v1/payments/create` | `Idempotency-Key` required; returns the payment incl. `checkout_url` |
| GET | `/api/v1/payments` | paginated list in the key's environment (Phase 3) |
| POST | `/api/v1/payments/{payment_id}/cancel` | only from `CREATED`; safe to retry (Phase 3) |
| POST | `/api/v1/payments/{payment_id}/initiate` | opens provider session; returns QR / intent / redirect |
| GET | `/api/v1/payments/{payment_id}` | full payment |
| GET | `/api/v1/payments/{payment_id}/status` | lightweight status |
| POST | `/api/v1/payments/{payment_id}/verify` | forces provider status check (server-to-server) |
| POST | `/api/v1/refunds` | `Idempotency-Key` required; full/partial |
| GET | `/api/v1/transactions` | paginated, filterable |
| POST | `/api/v1/webhooks/test` | sends signed `webhook.test` event |
| POST | `/api/v1/providers/{code}/callback` | provider → gateway (signature verified, unauthenticated by key) |
| GET | `/api/v1/checkout/{token}` | public checkout view model (no secrets, no customer PII; rate-limited per IP) |
| POST | `/api/v1/checkout/{token}/initiate` | customer clicked Pay: opens or reuses the provider session (Phase 4) |

Create-payment body: `merchant_reference`, `order_reference`, `amount` (integer paise),
`currency` (`INR`), `customer{name,mobile,email}`, `payment_method` (`UPI_QR`|`UPI_INTENT`|
`HOSTED`), `return_url`, `webhook_url` (must match a registered host), `expires_in_seconds`
(60–86400), `notes`.

### 5.4.1 Verification engine (Phase 5)

`services/verification.py` is the only code that turns provider information into payment changes.
Inputs: authenticated status calls (`PROVIDER_POLL`) and signature-verified callbacks
(`PROVIDER_CALLBACK`, stored in `provider_callbacks` before processing, unique per provider event).
Before `SUCCESS`, amount, currency and the provider transaction id are cross-checked against the
payment; a mismatch is recorded (`payment.verification_failed`) and not applied. A success writes one
ledger row (`transactions`, unique per provider transaction id) and a `NOT_RECONCILED`
reconciliation record. Money reported for an expired/cancelled/failed payment, or a second
transaction for a paid one, is recorded in the ledger and flagged `INVESTIGATION_REQUIRED`.
Polling: 5s, 10s, 15s, 30s, 1m, 2m, then every 5 minutes until the session is final.

### 5.5 Outbound webhooks (Phase 5)
Implemented as an outbox (`webhook_deliveries` rows written in the same transaction as the status
change). Events: `payment.created|initiated|pending|success|failed|expired|cancelled` (refund events
in Phase 8). Delivery re-checks DNS at send time (public IPs only, except TEST in development),
never follows redirects, and a 2xx reply to `webhook.test` validates the endpoint.
Headers: `X-TM-Event-Id`, `X-TM-Event-Type`, `X-TM-Timestamp`, `X-TM-Signature: v1=<hex HMAC-SHA256(secret,
"{timestamp}.{raw_body}")>`. Receivers must reject timestamps older than 5 minutes. Retries
use exponential backoff (1m, 5m, 15m, 1h, 6h, 24h), up to 8 attempts, then `FAILED`. A manual
redeliver is available from the dashboard.

---

## 6. Payment provider integration architecture (Phase 4)

Implemented in `app/providers/` (`base.py` contract, `registry.py`, `sandbox.py`): `create_session`,
`fetch_status`, and callbacks split into `identify_callback` (unverified routing fields, used only to
find the merchant's configuration) and `verify_callback` (must check the signature). A payment with
an open session expires only when the provider reports the session closed with nothing collected.
The sandbox signs its callbacks with HMAC-SHA256 under a server-only key derived from `HASH_PEPPER`.

```python
class PaymentProvider(Protocol):
    code: str
    supported_environments: set[Environment]
    capabilities: ProviderCapabilities          # upi_qr, upi_intent, hosted, refunds, status_api

    def create_session(self, ctx: ProviderContext, payment: PaymentSnapshot) -> SessionResult
    def fetch_status(self, ctx, payment, attempt) -> ProviderStatus      # authenticated API call
    def parse_callback(self, ctx, headers, raw_body) -> CallbackEvent    # MUST verify signature
    def create_refund(self, ctx, refund) -> RefundResult
    def fetch_refund_status(self, ctx, refund) -> RefundResult
    def fetch_settlements(self, ctx, date_from, date_to) -> list[SettlementRecord]
```

* `ProviderContext` carries the decrypted provider configuration for exactly one merchant +
  environment. Adapters never see other merchants' credentials.
* The **core payment engine** only consumes the normalized results (`ProviderStatus.state`,
  `amount`, `currency`, `provider_txn_id`, `merchant_ref`). The verification engine
  cross-checks every field against the stored payment before any transition to `SUCCESS`.
* A registry maps `code → adapter`. The registry **refuses** to return a non-live-capable
  adapter for `LIVE`, and the `sandbox` adapter raises if constructed for `LIVE`.
* A real adapter (e.g. a licensed PSP/PA or acquiring bank UPI API) is added as one module
  plus a provider row, with no changes to the payment engine. Each adapter ships with contract
  tests against the provider's own sandbox before LIVE is enabled.

---

## 7. Sandbox testing strategy (Phase 6)

* Sandbox merchant + `tm_test_` credentials are created automatically on registration.
* The `sandbox` provider generates a **non-payable** QR. Its content is a
  `tmsandbox://pay?...` URI rather than `upi://`, so no UPI app can act on it. It's
  rendered with a striped "TEST MODE — NO REAL MONEY" frame and banner.
* Outcomes are controlled by the **amount's paise** (documented test values), e.g.
  `…00` → SUCCESS, `…01` → FAILED, `…02` → stays PENDING, `…03` → EXPIRED. There's also a
  "Simulate" panel on the test checkout that calls a TEST-only endpoint. Both paths go
  through the same callback → verification → state machine → webhook pipeline as live, so the
  real code path is exercised.
* Sandbox refunds settle through the same simulated provider. Live refunds never use it.
* Automated tests: unit (state machine, signature, idempotency, encryption), API integration
  (pytest + TestClient against SQLite and, in CI, MySQL 8), and end-to-end sandbox lifecycle
  tests (create → initiate → callback → verify → webhook delivered → refund → reconcile).

---

## 8. Development phases

| Phase | Scope | Exit criteria |
|---|---|---|
| **1 Foundation** ✅ | Structure, FastAPI, DB + Alembic, auth (JWT/refresh/RBAC/lockout/rate limit), audit log, platform users, Super Admin dashboard on real aggregates, React shell with theme | Tests green; login → dashboard works end-to-end |
| **2 Merchant management** ✅ | Registration, profile, bank accounts (encrypted), provider configs, API credentials, webhook config, admin approval | Merchant can self-register; admin approves; keys issued once |
| **3 Payment engine** ✅ | `/api/v1` payments, idempotency, state machine, expiry, events | Concurrency + idempotency tests pass |
| **4 UPI & checkout** ✅ | Provider interface, sandbox adapter, QR/intent, hosted checkout + countdown | Checkout renders only server-verified states |
| **5 Verification** ✅ | Status polling worker, callback verification, ledger, outbound webhooks + retries | Duplicate callbacks are no-ops; webhooks signed + retried |
| 6 Sandbox | Test scenarios, simulate panel, webhook tester, refund simulation | Full sandbox lifecycle E2E test |
| 7 Live | First real provider adapter (needs signed provider agreement + docs), live gating, settlement import | Provider contract tests vs provider sandbox |
| 8 Reporting & admin | Transaction reports/CSV, refunds UI, settlements, reconciliation, audit viewer filters | Reconciliation exception flow tested |

**External dependency for Phase 7:** live UPI collection requires an agreement with an
RBI-authorised payment aggregator or an acquiring bank, plus their API documentation and
credentials. TechMasters operating as a payment aggregator in its own right requires RBI PA
authorisation. The code is structured so either path plugs in as an adapter.
