# 20 — Design Decisions

---

## Decision 1: Polling vs Event-Driven Alert Processing

**Decision:** Alert processor polls the `telemetry` table every 5 seconds for `is_processed=False` rows.

**Why it was chosen:** Simplicity. No additional infrastructure. The `is_processed` column on the existing table acts as a work queue. The same PostgreSQL instance handles both ingestion and processing.

**Alternative:** Event-driven processing using a message queue (Celery + RabbitMQ, Redis Queue, Kafka). The webhook handler would publish a job; a separate worker process would consume it.

**Why alternative was not used:** Reason cannot be confirmed from code. Likely: lower infrastructure complexity, single-server deployment constraint.

**Trade-off:**
- ✅ Simple to understand and operate
- ✅ No additional services to run
- ❌ 5-second minimum alert latency
- ❌ DB query overhead every 5 seconds even when idle
- ❌ Backlog builds under high ingestion load
- ❌ Multiple workers process same rows (race condition risk)

---

## Decision 2: PostgreSQL Instead of Time-Series DB

**Decision:** Store telemetry in a standard PostgreSQL table (`telemetry`).

**Why it was chosen:** Reason cannot be confirmed from code. Likely: team familiarity, single database reduces operational complexity (no need to run TimescaleDB or InfluxDB alongside PostgreSQL for auth/asset data).

**Alternative:** TimescaleDB (PostgreSQL extension with hypertable partitioning), InfluxDB, or QuestDB — purpose-built for time-series data.

**Why alternative was not used:** Reason cannot be confirmed from code.

**Trade-off:**
- ✅ All data in one database (auth, assets, telemetry, alerts)
- ✅ Standard SQL for all queries
- ✅ SQLAlchemy ORM works natively
- ❌ `DISTINCT ON (para_id)` queries for latest values are expensive at scale
- ❌ No automatic time-based partitioning
- ❌ `telemetry` table will grow to billions of rows with 1,000+ devices

---

## Decision 3: Redis as Optional Cache With In-Memory Fallback

**Decision:** Redis is used for latest-value caching but the system falls back to an in-memory Python dict if Redis is unavailable.

**Why it was chosen:** Allows running RDPMS without Redis in development/testing. The in-memory fallback means Redis is an optimization, not a hard dependency.

**Alternative:** Make Redis a hard dependency. Fail fast if Redis is unavailable.

**Trade-off:**
- ✅ Easier development setup
- ✅ System degrades gracefully instead of crashing
- ❌ In-memory fallback is per-process — breaks with multiple workers
- ❌ Gives false confidence that the system works without Redis (it does, but inconsistently in multi-worker mode)

---

## Decision 4: JWT HS256 with Hardcoded Secret

**Decision:** JWT tokens use HS256 algorithm with a secret key defined in `app/auth_utils.py`.

**Why it was chosen:** Reason cannot be confirmed from code. Simplest implementation — HS256 requires only a shared secret, no key management infrastructure.

**Alternative:** RS256 (asymmetric). Private key signs tokens; public key verifies them. Safer in microservice architectures where multiple services verify tokens.

**Why alternative was not used:** Single-service application — no other service needs to verify tokens. HS256 is sufficient.

**Critical trade-off:**
- ✅ Simple
- ❌ Secret is hardcoded: `"change-this-to-a-long-random-secret"` — **must be changed in production via .env**. If the source code leaks, any token can be forged.
- ❌ No rotation mechanism

---

## Decision 5: Refresh Tokens in Database (Not Stateless JWT)

**Decision:** Refresh tokens are random strings stored as SHA-256 hashes in PostgreSQL.

**Why it was chosen:** Enables individual token revocation. A stolen refresh token can be invalidated without affecting other users or rotating signing keys.

**Alternative:** Stateless JWT refresh tokens. No DB storage needed.

**Trade-off:**
- ✅ Per-token revocation (logout works properly)
- ✅ Token rotation detects theft
- ✅ Admin can revoke all tokens for a user by deleting their refresh_tokens rows
- ❌ Every refresh request hits the database
- ❌ Refresh token table grows over time (expired tokens accumulate — no cleanup job currently)

---

## Decision 6: FastAPI Over Django REST Framework

**Decision:** FastAPI is used as the web framework.

**Why it was chosen:** Reason cannot be confirmed from code. Likely: async support (critical for WebSocket), auto-generated OpenAPI docs, Pydantic validation, performance.

**Alternative:** Django REST Framework — mature, large ecosystem, Django ORM.

**Trade-off:**
- ✅ Async native (WebSocket, SSE, background tasks all in one)
- ✅ Auto-generated `/docs` (Swagger UI)
- ✅ Pydantic schemas are both validation and documentation
- ❌ Smaller ecosystem than Django
- ❌ SQLAlchemy instead of Django ORM — more verbose

---

## Decision 7: Nginx for mTLS (Not FastAPI)

**Decision:** TLS termination, including mTLS client certificate verification, is handled by Nginx. FastAPI reads proxy-injected headers.

**Why it was chosen:** FastAPI/uvicorn cannot easily do mTLS in production at scale. Nginx is the industry standard TLS terminator. Separating concerns: Nginx does network, FastAPI does application logic.

**Alternative:** Terminate TLS inside Python (using `ssl` module or `trustme`).

**Trade-off:**
- ✅ Standard production pattern
- ✅ Nginx handles TLS efficiently in C
- ✅ FastAPI code stays simple
- ❌ Header spoofing risk if port 8000 is not firewalled (Nginx injects headers; someone bypassing Nginx could set them)
- ❌ Requires correct Nginx configuration — a misconfigured Nginx (not stripping incoming headers) is a security hole

---

## Decision 8: `is_processed` Flag on Telemetry Table

**Decision:** Use a boolean column on the `telemetry` table as a work queue for the alert processor.

**Why it was chosen:** Simplicity. No external queue. Uses the existing database.

**Alternative:** Separate `alert_queue` table. Or a proper message queue (Redis Queue, Kafka).

**Trade-off:**
- ✅ No additional infrastructure
- ✅ ACID guarantees — telemetry write and flag are in the same transaction
- ✅ Easy to query backlog size: `SELECT COUNT(*) WHERE is_processed=False`
- ❌ Polling overhead every 5 seconds
- ❌ Index on `is_processed` can become hot (many rows with `False`, then mass updates to `True`)
- ❌ Not safe for multiple concurrent workers (no `SELECT FOR UPDATE SKIP LOCKED`)

---

## Decision 9: Single API Key for All Gateways

**Decision:** All gateways use the same `API_KEY` from settings.

**Why it was chosen:** Reason cannot be confirmed from code. Simplest approach — no per-device key management.

**Alternative:** Per-device API keys. Each gateway has its own key. A compromised gateway's key can be revoked independently.

**Trade-off:**
- ✅ Simple configuration
- ❌ One leaked key compromises all gateways
- ❌ No independent revocation
- Per-gateway mTLS certificate binding (`Gateway.mtls_cn`) partially mitigates this — a gateway with a bound cert cannot be impersonated by API key alone

---

## Decision 10: Disable Startup Seeding in Multi-Worker Mode

**Decision:** Database migrations and seeding run only when `RUN_STARTUP_SEEDING=1` is set, not on every worker startup.

**Why it was chosen:** Each Gunicorn worker starts independently. If all 4 workers run migrations simultaneously, they race. If each worker seeds default data, they multiply memory usage at startup — causing OOM on 2GB servers.

**Alternative:** Run migrations as a separate pre-startup step (systemd `ExecStartPre`, Docker entrypoint, or CI/CD pipeline step).

**Trade-off:**
- ✅ Worker startup is lightweight (~80-100MB)
- ✅ No OOM during deployment
- ❌ Requires manual `python seed.py` before first deployment or after schema changes
- ❌ Easy to forget — if a new engineer deploys without running seed, the DB is missing default data
