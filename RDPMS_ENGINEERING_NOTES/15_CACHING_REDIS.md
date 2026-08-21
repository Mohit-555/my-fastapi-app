# 15 — Caching and Redis

---

## What Redis Is Used For

Redis is used as a **cache** and **state store** — not as a queue or message broker.

Specifically:
1. **Latest parameter values** — the most recent reading for each `(stngw_id, para_id)` pair
2. **Gateway health status** — last-seen connectivity state per gateway
3. **SMMS sync results** — results of asset sync operations (cached 7 days)

**Not used for:** Message queuing, pub/sub, session storage, rate limiting (rate limiting uses memory fallback).

**Source:** `app/services/redis_service.py`

---

## What Is Stored

### 1. Latest Parameter Values

**Key pattern:** `rdpms:latest:{stngw_id}:{para_id}` (e.g., `rdpms:latest:456523AB:0001000C`)

**Value:** JSON object:
```json
{
  "value": 5.20,
  "timestamp": "04-11-2025 16:27:45.130",
  "stngw_id": "456523AB",
  "para_id": "0001000C"
}
```

**TTL:** 3600 seconds (1 hour). If a gateway goes silent, the cached value expires after 1 hour. The real-time dashboard will show no data for that parameter.

**Written by:** `webhook.py` (and `gateway.py`) after each telemetry write, via `redis_service.store_latest_parameter()`.

**Read by:** `GET /api/realtime/telemetry/{station_code}` — returns all latest values for a station by scanning Redis for all `rdpms:latest:{stngw_id}:*` keys where the gateway belongs to that station.

**Why this matters:** Without Redis, every call to the live dashboard would run:
```sql
SELECT DISTINCT ON (para_id) * FROM telemetry
WHERE gateway_id = X
ORDER BY para_id, received_at DESC
```
Across potentially thousands of para_ids and millions of rows. Redis makes this O(1) per parameter.

---

### 2. Gateway Health Status

**Key pattern:** `rdpms:health:{stngw_id}` (or similar pattern — needs verification from `redis_service.py`)

**Value:** Health summary JSON including sensor counts and last_seen timestamp.

**TTL:** 3600 seconds.

**Written by:** Gateway health webhook handler.

**Read by:** `GET /sse/health/{station_code}`, `GET /api/realtime/dashboard/{station_code}`.

---

### 3. SMMS Sync Results

**Key:** `rdpms:sync:smms:{timestamp}` or similar.

**TTL:** 7 days (604800 seconds).

**Purpose:** Stores the result of the last SMMS sync so the scheduler doesn't need to hit SMMS every time a dashboard requests asset data.

---

## Cache Lifecycle

```
Gateway sends telemetry
    │
    ▼
webhook.py writes to PostgreSQL
    │
    ▼
webhook.py calls redis_service.store_latest_parameter()
    │
    ├─► Redis available? ──► SET key value EX 3600
    │
    └─► Redis unavailable? ──► In-memory dict fallback

Client requests /api/realtime/telemetry/LKO
    │
    ▼
realtime.py reads from Redis
    │
    ├─► Key exists? ──► Return cached value (< 1ms)
    │
    ├─► Key expired? ──► Return empty/null for that parameter
    │
    └─► Redis unavailable? ──► Fall back to DB query
```

---

## Fallback Behavior (Critical for Ops)

**Source:** `app/services/redis_service.py` — the `RedisService` class implements a complete fallback.

**If Redis is unavailable (at startup or runtime):**
- All `store_*` calls write to `self._memory_store` (Python dict)
- All `get_*` calls read from `self._memory_store`
- The application continues to function
- Log: `"Redis not available, using in-memory storage"`

**Implication for multi-worker deployment:**
```
Worker 1 writes para_id "0001000C" value to memory_store[key]
Worker 2 gets a request for that value → its own memory_store is empty
Result: Worker 2 returns "no data" even though Worker 1 just wrote it
```

Multiple Gunicorn workers do NOT share Python memory. The Redis fallback is only safe for **single-worker** deployments. In production with multiple workers, Redis must be running.

---

## What Redis Is NOT Used For

### Not a Message Queue

The alert processor does not use Redis pub/sub or Redis Queue (RQ) to receive telemetry jobs. It polls the PostgreSQL `telemetry` table directly. This is a deliberate simplicity trade-off.

### Not Session Storage

JWT access tokens are stateless (validated by signature verification). Refresh tokens are stored in PostgreSQL, not Redis.

### Not Rate Limiting Store

SlowAPI is configured to use Redis if available but falls back to an in-memory dictionary. Confirmed from: `app/limiter.py`. The storage backend is configured at app startup.

---

## Performance Implications

**Without Redis:** Every live dashboard load hits PostgreSQL with a `DISTINCT ON (para_id)` query across millions of rows.

**With Redis:** Live dashboard load = N Redis `GET` calls (N = number of parameters at the station). Each call ~0.5ms. For a station with 100 parameters: ~50ms total vs potentially seconds in PostgreSQL.

**Cold cache (after restart):** For ~1 hour (the TTL), the latest values from before the restart are gone. New data starts flowing from the next gateway packet. The system remains functional but the realtime snapshot may show gaps for parameters that haven't sent data yet.

**Cache warming:** There is no cache pre-warming mechanism. After a restart, the cache fills naturally as gateways send new readings.

---

## TTL Design Decisions

| Data | TTL | Reasoning |
|---|---|---|
| Latest parameter value | 3600s (1h) | Gateways send every 5s — a 1h TTL means if a gateway goes silent, stale data expires before the health check detects the outage |
| Gateway health | 3600s (1h) | Same rationale |
| SMMS sync | 604800s (7d) | SMMS asset data changes infrequently; 7-day cache prevents excessive external API calls |

---

## Summary: Redis Roles in RDPMS

| Role | In RDPMS? | Notes |
|---|---|---|
| Cache | ✅ Yes | Latest telemetry values |
| State store | ✅ Yes | Gateway health, sync results |
| Queue | ❌ No | Polling instead |
| Pub/Sub broker | ❌ No | WebSocket broadcasts direct |
| Session store | ❌ No | JWT is stateless |
| Rate limit store | ⚠️ Partial | SlowAPI tries Redis first |
