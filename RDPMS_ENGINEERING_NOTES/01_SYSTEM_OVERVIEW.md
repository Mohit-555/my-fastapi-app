# 01 — RDPMS in One Page

## The Problem

Indian Railways has thousands of **signalling assets** (point machines, track circuits, signals, power supplies) distributed across stations. When they fail, trains stop. Identifying a failing asset *before* it fully fails — **predictive maintenance** — saves downtime and prevents accidents.

Before RDPMS, field engineers manually inspected assets on a schedule. They had no visibility into live electrical readings. A failing point machine gave no warning — it would simply stop one day.

**RDPMS solves this by:**
- Continuously reading electrical parameters (voltage, current, stroke time, temperature) from signalling assets via sensors wired to RTU hardware
- Storing every reading in a PostgreSQL time-series database
- Running threshold and trend logic to detect anomalies
- Generating alerts before (predictive) or at the moment of (failure) equipment problems
- Presenting all of this in a dashboard accessible to engineers at every level of the railway hierarchy

---

## Who Interacts With RDPMS

| Actor | How |
|---|---|
| Physical Gateway (RTU/Master Card) | HTTP POST webhook with X-API-Key (+ optional mTLS) |
| Frontend Web App (React/TypeScript) | REST API + WebSocket + SSE with JWT Bearer token |
| SMMS (Indian Railways asset system) | External API sync — RDPMS pulls asset list |
| Admin / JE / SE / DRM | Human users authenticated via employee_id + password |

---

## Main Inputs

1. **Telemetry packets** from gateways — electrical readings every 5s or on events
2. **Login credentials** from human users
3. **Admin configuration** — thresholds, asset assignments, maintenance windows
4. **Asset data** synced from SMMS

---

## Main Outputs

1. **Failure alerts** — asset has stopped working
2. **Predictive alerts** — asset is trending toward failure
3. **Live telemetry** — real-time parameter values over WebSocket/SSE
4. **Historical reports** — telemetry history, alert summaries, performance metrics
5. **Dashboard KPIs** — system health, MTTR, prediction accuracy

---

## Major Components

| Component | Technology | Source |
|---|---|---|
| API Server | FastAPI (Python 3.12) | `app/main.py` |
| Database | PostgreSQL + SQLAlchemy ORM | `app/database.py` |
| Migrations | Alembic | `alembic/` |
| Background Alert Processor | asyncio task (polling) | `app/services/alert_processor.py` |
| Alert Logic Engine | Per-asset-type Python rules | `app/services/logics/` |
| WebSocket Manager | FastAPI WebSocket | `app/services/websocket_manager.py` |
| Cache Layer | Redis + in-memory fallback | `app/services/redis_service.py` |
| Task Scheduler | asyncio tasks | `app/services/scheduler.py` |
| Reverse Proxy | Nginx (mTLS termination) | `deployment/nginx-mtls.conf.example` |
| Auth | JWT access + DB-backed refresh tokens | `app/auth_utils.py` |
| Rate Limiting | SlowAPI (Redis or memory) | `app/limiter.py` |
| Metrics | Prometheus client | `app/routers/monitoring.py` |

---

## Complete High-Level Data Flow

```
┌──────────────────────────────────────────────────────────────┐
│  FIELD HARDWARE                                              │
│  Sensor → Slave Card channel → Gateway (Master Card/RTU)    │
│  Gateway packs readings as JSON, POSTs every 5s or on event │
└──────────────────┬───────────────────────────────────────────┘
                   │ POST /webhook/parameters/fixed
                   │ X-API-Key + optional X-SSL-Client-Verify
                   ▼
┌──────────────────────────────────────────────────────────────┐
│  NGINX                                                       │
│  Terminates TLS, optionally validates client cert (mTLS)    │
│  Forwards X-SSL-Client-Verify: SUCCESS header to FastAPI    │
└──────────────────┬───────────────────────────────────────────┘
                   ▼
┌──────────────────────────────────────────────────────────────┐
│  FASTAPI (webhook.py / gateway.py)                           │
│  1. Authenticates X-API-Key                                 │
│  2. Validates JSON (Pydantic schemas)                        │
│  3. Auto-creates Gateway row on first sight                 │
│  4. Auto-discovers para_ids → AssetParameter rows           │
│  5. Deduplicates (para_id + prt + prv)                       │
│  6. Writes Telemetry rows (is_processed=False)              │
│  7. Updates Redis latest-value cache                         │
│  8. Broadcasts telemetry_update via WebSocket               │
│  9. Returns 202 Accepted                                     │
└──────────────────┬───────────────────────────────────────────┘
                   │ (background asyncio, every 5 seconds)
                   ▼
┌──────────────────────────────────────────────────────────────┐
│  ALERT PROCESSOR (alert_processor.py)                        │
│  - Polls Telemetry WHERE is_processed=False, batch of 100   │
│  - Resolves Asset via para_id → AssetParameter              │
│  - Calls AlertEngine.evaluate_telemetry()                   │
│  - Dispatches to logic module by asset_type_hex             │
│    00=PointMachine, 20=TrackCircuit, 10-13=Signal, 50=IPS  │
│  - Logic returns alert dicts (cause_code, type)             │
│  - AlertEngine deduplicates + writes AlertEvent to DB       │
│  - Broadcasts new_alert via WebSocket                       │
│  - Marks rows is_processed=True                             │
└──────────────────┬───────────────────────────────────────────┘
                   ▼
┌──────────────────────────────────────────────────────────────┐
│  FRONTEND / API CONSUMERS                                    │
│  REST API  → reports, history, config (JWT Bearer token)    │
│  WebSocket → live telemetry, live alerts, health            │
│  SSE       → same as WebSocket but read-only HTTP stream    │
└──────────────────────────────────────────────────────────────┘
```
