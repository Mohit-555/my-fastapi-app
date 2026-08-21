# 00 — INDEX

## RDPMS Engineering Notebook

**Purpose:** Deep engineering understanding for architecture explanation, debugging, technical interviews, and rebuilding simplified versions.

**Not for:** Feature documentation, user manuals, or API references (see Postman collection for that).

---

## Reading Order

If you are studying this for a technical interview, read in this order:

1. **[01_SYSTEM_OVERVIEW.md](01_SYSTEM_OVERVIEW.md)** — Start here. One-page summary of what RDPMS is and does.
2. **[02_BUSINESS_DOMAIN.md](02_BUSINESS_DOMAIN.md)** — Understand the railway domain (Zones, Gateways, Assets, para_id, Telemetry).
3. **[03_ARCHITECTURE.md](03_ARCHITECTURE.md)** — How the system components fit together.
4. **[05_DATA_FLOW.md](05_DATA_FLOW.md)** — How data moves through the system (ingestion, query, real-time events).
5. **[04_REQUEST_LIFECYCLE.md](04_REQUEST_LIFECYCLE.md)** — Trace one packet from a gateway to an alert appearing in the dashboard.
6. **[06_DATABASE.md](06_DATABASE.md)** — Database structure, table purposes, cascade behavior, migrations.
7. **[08_INGESTION.md](08_INGESTION.md)** — Deep dive on telemetry ingestion (authentication, deduplication, storage).
8. **[11_ALERT_PROCESSING.md](11_ALERT_PROCESSING.md)** — Alert lifecycle, logic types, deduplication layers.
9. **[09_MTLS_SECURITY.md](09_MTLS_SECURITY.md)** — Security: mTLS, JWT, refresh tokens, API keys.
10. **[10_BACKGROUND_PROCESSING.md](10_BACKGROUND_PROCESSING.md)** — Background workers: alert processor, scheduler, race conditions.
11. **[12_ASSET_HIERARCHY.md](12_ASSET_HIERARCHY.md)** — Zone → Division → Station → Gateway → Slave Card → Asset.
12. **[13_ANNEXURE_PROTOCOL.md](13_ANNEXURE_PROTOCOL.md)** — RDSO spec: para_id encoding, packet types, stngw_id decode.
13. **[07_API.md](07_API.md)** — Key API endpoints explained with business logic.
14. **[15_CACHING_REDIS.md](15_CACHING_REDIS.md)** — Redis usage, fallback behavior, performance implications.
15. **[14_ERROR_HANDLING.md](14_ERROR_HANDLING.md)** — Complete failure matrix and error response guide.
16. **[19_FAILURE_SCENARIOS.md](19_FAILURE_SCENARIOS.md)** — Detailed failure scenarios: what breaks, how, and how to recover.
17. **[16_TESTING.md](16_TESTING.md)** — Current test coverage gaps and test scenarios that matter.
18. **[16_OBSERVABILITY.md](16_OBSERVABILITY.md)** — Logging, metrics, debugging procedures.
19. **[17_DEPLOYMENT.md](17_DEPLOYMENT.md)** — Deployment procedure, Gunicorn, Nginx, systemd.
20. **[18_SCALABILITY.md](18_SCALABILITY.md)** — Current bottlenecks and how to scale to 100,000 devices.
21. **[20_DESIGN_DECISIONS.md](20_DESIGN_DECISIONS.md)** — Why each major decision was made (and the trade-offs).
22. **[18_CODE_CONCEPT_MAP.md](18_CODE_CONCEPT_MAP.md)** — Every concept mapped to its exact file, class, and function.
23. **[21_INTERVIEW_QUESTIONS.md](21_INTERVIEW_QUESTIONS.md)** — Q&A format: beginner to senior level.

---

## Key Facts to Memorize

| Fact | Answer |
|---|---|
| What is RDPMS? | IoT telemetry + predictive maintenance for Indian Railways signalling |
| Programming language | Python 3.12, FastAPI |
| Database | PostgreSQL + SQLAlchemy ORM + Alembic migrations |
| Cache | Redis (with in-memory fallback) |
| Real-time | WebSocket + SSE |
| Ingestion auth | X-API-Key header (+ optional mTLS via Nginx) |
| Human auth | JWT HS256 (30 min) + DB-backed refresh tokens |
| Alert processing | Background asyncio task, polls every 5 seconds |
| Asset types | 37 types defined in RDSO/SPN/257/2025 Annexure A |
| para_id format | 8 hex chars = asset_type + asset_number + param_type + representation |
| stngw_id format | 8 hex chars = zone + division + station + gateway_number |
| Packet types | Clause 5.9 (fixed, prt=array) and 5.10 (event-based, prt=single string) |
| Alert types | Failure (immediate) and Predictive (trending toward failure) |
| Alert dedup | In-memory dict (per worker) + DB-level suppression query |
| Maintenance mode | In-memory (lost on restart); DB record stored for audit |
| Redis fallback | Per-process in-memory dict (breaks with multiple workers) |
| Startup OOM fix | `RUN_STARTUP_SEEDING` env var gates heavy startup logic |
| Cascade deletes | Zone → Division → Station → Gateway/Asset/Alert (everything) |
| Refresh token security | Stored as SHA-256 hash; rotation on every use |
| SECRET_KEY | Hardcoded default MUST be changed in production (.env) |

---

## System Boundaries

**RDPMS controls:**
- Data ingestion from gateways
- Alert generation
- User management and RBAC
- Dashboard and reporting API
- Real-time WebSocket/SSE streams

**RDPMS does NOT control:**
- Physical sensors and hardware
- Gateway firmware or connectivity
- SMMS (external Indian Railways asset system — read-only sync)
- Email/SMS notifications (not implemented)
- The cellular network the gateways use

---

## The Single Most Important Line of Code

```python
# app/models/models.py:134
is_processed: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
```

This boolean column is the **entire work queue mechanism** that decouples fast telemetry ingestion from slow alert processing. Without it, the system architecture would be fundamentally different.
