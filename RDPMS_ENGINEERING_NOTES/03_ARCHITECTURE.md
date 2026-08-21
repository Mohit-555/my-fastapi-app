# 03 — System Architecture

---

## Component Map

```
┌─────────────────────────────────────────────────────────────────────┐
│  HARDWARE LAYER                                                     │
│  Sensor → Slave Card Channel → Gateway (RTU)                       │
│  Gateway sends JSON over cellular/broadband                         │
└───────────────────────┬─────────────────────────────────────────────┘
                        │ HTTPS POST
                        ▼
┌─────────────────────────────────────────────────────────────────────┐
│  NGINX (Reverse Proxy)                                              │
│  • Terminates TLS (certificates managed by nginx, not FastAPI)     │
│  • Optionally validates client cert (mTLS)                         │
│  • Forwards X-SSL-Client-Verify + X-SSL-Client-CN headers          │
│  • Proxies to FastAPI on 127.0.0.1:8000                            │
└───────────────────────┬─────────────────────────────────────────────┘
                        ▼
┌─────────────────────────────────────────────────────────────────────┐
│  FASTAPI APPLICATION (app/main.py)                                  │
│                                                                     │
│  ┌───────────┐  ┌───────────┐  ┌───────────┐  ┌────────────────┐  │
│  │  Auth     │  │ Webhook   │  │  Gateway  │  │  Admin/Assets/ │  │
│  │  Router   │  │  Router   │  │  Router   │  │  Alerts/etc.   │  │
│  │  /auth/   │  │ /webhook/ │  │ /gateway/ │  │  routers       │  │
│  └─────┬─────┘  └─────┬─────┘  └─────┬─────┘  └───────┬────────┘  │
│        │              │              │                 │           │
│        └──────────────┴──────────────┴─────────────────┘           │
│                              │                                     │
│                    ┌─────────▼──────────┐                          │
│                    │  SQLAlchemy ORM    │                          │
│                    │  SessionLocal      │                          │
│                    └─────────┬──────────┘                          │
│                              │                                     │
│  ┌───────────────────────────▼─────────────────────────────────┐   │
│  │               BACKGROUND SERVICES                           │   │
│  │  AlertProcessor   Scheduler   WebSocketManager             │   │
│  │  (asyncio task)   (asyncio)   (connection registry)        │   │
│  └─────────────────────────────────────────────────────────────┘   │
└───────────┬─────────────────────────────────────────┬──────────────┘
            │                                         │
            ▼                                         ▼
┌───────────────────────┐               ┌─────────────────────────┐
│  PostgreSQL           │               │  Redis                  │
│  All persistent data  │               │  Latest parameter values│
│  Alert events         │               │  Gateway health cache   │
│  Telemetry history    │               │  (falls back to memory) │
└───────────────────────┘               └─────────────────────────┘
```

---

## Component: Nginx (Reverse Proxy)

**Responsibility:** Sits in front of FastAPI. Handles all raw network concerns.

**Why it exists:** FastAPI/uvicorn should not be exposed directly to the internet. Nginx handles TLS, rate limiting at the network layer, and serves as the mTLS endpoint.

**Input:** Raw HTTPS requests from gateways and browsers.

**Output:** Plain HTTP requests forwarded to `127.0.0.1:8000` with added headers:
- `X-SSL-Client-Verify: SUCCESS` (when mTLS is enabled and cert is valid)
- `X-SSL-Client-CN: <gateway_cert_cn>`

**Failure mode:** If Nginx is misconfigured and these headers are missing, but `REQUIRE_MTLS=True` in settings, FastAPI will reject every request with 401. If Nginx is bypassed entirely and someone connects directly to port 8000, they bypass certificate verification — API key is the only protection then. This is why port 8000 must be firewalled.

---

## Component: FastAPI Application

**Responsibility:** The core of RDPMS. Handles all HTTP/WebSocket requests.

**Source:** `app/main.py` — application assembly, middleware, lifespan.

**Key middleware:**
- `CORSMiddleware` — allows browser AJAX from frontend origin
- `RateLimitExceeded` handler — returns 429 instead of crashing
- SlowAPI rate limiter — protects auth endpoints (5/minute) and refresh (10/minute)

**Startup (lifespan):** `app/main.py:71-95` — starts `alert_processor`, `scheduler`, and `db_service`. Database migrations and seeding only run if `RUN_STARTUP_SEEDING=1` is set, preventing memory spikes on multi-worker startup.

**Routers and their roles:**

| Router | Prefix | Who calls it | Auth |
|---|---|---|---|
| `auth.py` | `/auth` | Frontend | None (login), Bearer (me/change-password) |
| `gateway.py` | `/gateway` | Gateway hardware | None (data), Bearer (admin endpoints) |
| `webhook.py` | `/webhook` | Gateway hardware | X-API-Key |
| `assets.py` | `/api/assets` | Frontend | Bearer |
| `alerts.py` | `/api/alerts` | Frontend | Bearer |
| `maintenance.py` | `/maintenance` | Frontend | Bearer |
| `dashboard.py` | `/api/dashboard` | Frontend | Bearer |
| `realtime.py` | `/api/realtime` | Frontend | X-API-Key |
| `websocket.py` | `/ws` | Frontend | None (WebSocket) |
| `sse.py` | `/sse` | Frontend | X-API-Key |
| `admin.py` | `/api/admin` | Admin Frontend | Bearer |
| `zones.py` / `divisions.py` / `stations.py` | `/zones` etc. | Frontend | Bearer |
| `slave_card.py` | `/slave-cards` | Admin Frontend | Bearer |
| `decode.py` | `/decode` | Debug/Admin | None |
| `monitoring.py` | `/api/monitoring` | Ops | None |

---

## Component: Database (PostgreSQL + SQLAlchemy)

**Responsibility:** Persistent storage for all system state.

**Source:** `app/database.py` — engine creation, session factory, `get_db()` dependency.

**Session pattern:** FastAPI dependency injection via `get_db()`. Each request gets its own session, closed in the `finally` block. This is the standard SQLAlchemy session-per-request pattern.

**Connection pool:** `create_engine(..., pool_pre_ping=True)` — validates connections before use, handles stale connections after database restarts.

**Migrations:** Alembic (`alembic/`). Run manually with `alembic upgrade head`. Schema changes must always be accompanied by a migration file.

**Failure mode:** If PostgreSQL goes down, all API endpoints that touch the DB return 500. There is no retry logic — requests fail immediately. Background workers (alert processor, scheduler) catch the exception, wait, and retry.

---

## Component: Alert Processor

**Responsibility:** Reads unprocessed telemetry rows, evaluates alert logic, writes alerts.

**Source:** `app/services/alert_processor.py`

**Why it's background, not synchronous:** Alert evaluation requires:
1. Querying historical telemetry (15-day window for average calculation)
2. Checking complex threshold logic
3. Potentially writing alert records

Doing all of this synchronously inside the webhook handler would add 100-500ms to every telemetry ingestion response. The gateway would time out or back up. Decoupling via the `is_processed` flag means the webhook returns 202 immediately.

**Processing interval:** 5 seconds (`self.processing_interval = 5`).

**Batch size:** 100 rows per cycle (`self.batch_size = 100`).

**Failure mode:** If an individual telemetry row causes an exception, it is marked `is_processed=True` anyway (to prevent infinite retry loops on malformed data). Source: `app/services/alert_processor.py:143-145`.

---

## Component: Alert Engine + Logic Modules

**Responsibility:** Contains the business rules for when alerts should be generated.

**Source:** `app/services/alert_engine.py`, `app/services/logics/`

**Design:** The AlertEngine is a dispatcher. It receives a telemetry reading and routes it to the correct logic module based on `asset_type_hex`:

| asset_type_hex | Logic class | File |
|---|---|---|
| `00` | `PointMachineLogics` | `logics/point_machine.py` |
| `20` | `TrackCircuitLogics` | `logics/track_circuit.py` |
| `10`-`13` | `SignalLogics` | `logics/signal.py` |
| `50` | `IPSLogics` | `logics/ips.py` |

**In-memory deduplication:** `AlertEngine.active_alerts` dict prevents generating the same alert twice for the same asset+cause while it's still active. `AlertEngine.alert_history` prevents regenerating an alert within 1 hour of it being cleared. Source: `app/services/alert_engine.py:121-141`.

**Critical weakness:** These dicts are in-memory. If the server restarts, deduplication state is lost. Active alerts in the DB won't prevent the engine from generating new alerts for the same cause immediately after restart.

---

## Component: WebSocket Manager

**Responsibility:** Manages all active WebSocket connections and broadcasts messages to them.

**Source:** `app/services/websocket_manager.py`

**Data structure:** `station_connections: Dict[str, Set[WebSocket]]` — maps station_code to all connected clients.

**Heartbeat:** Pings every 30 seconds. Drops connections that don't pong within 60 seconds.

**Broadcast methods:**
- `broadcast_parameter_update()` — called from webhook.py after each new telemetry write
- `broadcast_alert()` — called from alert_processor.py after each new alert
- `broadcast_health_update()` — called from gateway/health endpoints
- `broadcast_maintenance_mode()` — called from maintenance router

---

## Component: Redis / Cache

**Responsibility:** Stores the latest parameter value for each `(stngw_id, para_id)` pair. Enables sub-millisecond lookup of current readings without hitting PostgreSQL.

**Source:** `app/services/redis_service.py`

**Fallback:** If Redis is unavailable (module not installed, server not running), all operations fall back to an in-memory Python dict. This fallback is per-process — multiple Gunicorn workers don't share it.

**TTL:** Latest parameter values expire after 3600 seconds (1 hour). Gateway health expires after 3600 seconds. Sync results kept 7 days.

---

## Component: Task Scheduler

**Responsibility:** Runs periodic background tasks independent of incoming requests.

**Source:** `app/services/scheduler.py`

**Tasks:**
- Daily statistics aggregation (runs at midnight)
- Hourly health check (stub — currently empty body)
- Daily Redis cleanup (stub — currently empty body)
- Daily asset sync from SMMS at 2:00 AM
- Maintenance reminder alerts every 60 seconds

---

## Component: Auth

**Responsibility:** Issues and validates JWT access tokens and DB-backed refresh tokens.

**Source:** `app/auth_utils.py`, `app/routers/auth.py`

**JWT:** HS256, 30-minute expiry. Payload contains `employee_id` as `sub` claim and `type: "access"` to distinguish from other token types.

**Refresh tokens:** Random 64-byte URL-safe strings, stored as SHA-256 hash in `refresh_tokens` table. Expire after 1 day (7 days for "remember me"). Revoked on logout or use (rotation: each refresh issues a new token and revokes the old one).
