# 05 — Data Flow

---

## Three Distinct Flows

RDPMS has three separate data flows that must not be confused:

1. **Ingestion flow** — hardware → RDPMS
2. **Query flow** — RDPMS → frontend
3. **Event flow** — RDPMS → frontend (real-time push)

---

## Flow 1: Ingestion (Gateway → RDPMS)

```
Gateway (field hardware)
    │
    │  POST /webhook/parameters/fixed (or /gateway/data)
    │  X-API-Key header
    │  Body: {stngw_id, imei, parameters: [{para_id, prv[], prt[]}]}
    │
    ▼
webhook.py / gateway.py
    │
    ├── Authenticate (API key + optional mTLS header check)
    ├── Validate JSON (Pydantic)
    ├── Get or create Gateway row (auto-register on first sight)
    ├── Auto-discover new para_ids → AssetParameter rows (unassigned)
    ├── Deduplicate readings (para_id + prt + prv)
    ├── Write Telemetry rows (is_processed=False)
    ├── Write latest value → Redis cache
    └── Fire-and-forget: broadcast telemetry_update via WebSocket
    │
    ▼
Returns 202 Accepted (synchronous end)
    │
    │  (async, ~5s later)
    ▼
AlertProcessor._process_batch()
    │
    ├── Query Telemetry WHERE is_processed=False
    ├── For each: resolve Gateway → AssetParameter → Asset
    ├── Call AlertEngine.evaluate_telemetry()
    ├── Asset logic module returns alert candidates
    ├── AlertEngine._generate_alert() → write AlertEvent
    ├── Broadcast new_alert via WebSocket
    └── Mark all rows is_processed=True, commit
```

---

## Flow 2: Query (Frontend → RDPMS)

```
Frontend (browser/app)
    │
    │  GET /api/realtime/dashboard/{station_code}
    │  Authorization: Bearer <access_token>
    │
    ▼
realtime.py
    │
    ├── Validate JWT (get_current_user)
    ├── Query Station (by station_code)
    ├── Query Gateways for this station
    ├── READ from Redis: all latest parameter values
    │       ↑ Redis key: rdpms:latest:{stngw_id}:{para_id}
    ├── Query AlertEvent (recent active alerts count)
    ├── Query AlertEvent (MTTR calculation)
    ├── READ from Redis: gateway health status
    └── Aggregate into dashboard response JSON
    │
    ▼
Returns full dashboard snapshot
```

**Key distinction:** The dashboard snapshot uses Redis for live values and PostgreSQL for historical/aggregated data.

---

## Flow 3: Real-Time Events (RDPMS → Frontend)

### WebSocket Path

```
Frontend connects:
    ws://host/ws/telemetry/LKO?asset_no=PT-101
    │
    ▼
websocket.py endpoint accepts connection
ConnectionManager.connect(websocket, "LKO")
    │
    ├── Add to station_connections["LKO"]
    ├── Start heartbeat task (ping every 30s)
    └── Send initial_state message (all current values from Redis)

Then, whenever gateway sends telemetry:
webhook.py writes to DB + Redis
    │
    └── safe_create_task(websocket_manager.broadcast_parameter_update(...))
            │
            └── For each WebSocket in station_connections["LKO"]:
                    send_text({"type": "telemetry_update", "data": {...}})
```

### SSE Path

```
Frontend connects:
    GET /sse/telemetry/LKO
    X-API-Key: ...
    Accept: text/event-stream
    │
    ▼
sse.py: StreamingResponse (async generator)
    │
    ├── Send initial event (current values from Redis)
    └── Loop:
            await asyncio.sleep(5)
            Read current values from Redis
            If changed since last send → yield update event
            Always yield heartbeat event
```

**Key difference:** WebSocket receives pushes from the server. SSE polls Redis internally every 5 seconds and pushes only changes. WebSocket is more reactive (sub-100ms latency). SSE has 5-second latency.

---

## Data Transformation Points

| Point | Input format | Output format |
|---|---|---|
| Gateway packet received | `DD-MM-YYYY HH:mm:ss.SSS` timestamp string | Stored as-is in `prt` column |
| Alert processor | `prt` string | `datetime` via `safe_parse_datetime()` |
| API responses | snake_case DB fields | camelCase JSON (via Pydantic schema aliases) |
| para_id | 8-char hex string | Decoded: asset type + parameter name + unit |
| Telemetry `prv` | Float (raw sensor reading) | Float (no transformation, stored as-is) |
| stngw_id | 8-char hex string | Decoded: Zone + Division + Station |

---

## Cache vs Database Usage

| API Endpoint | Redis | PostgreSQL |
|---|---|---|
| `/api/realtime/telemetry/{station}` | ✅ Latest values | ❌ (only used as fallback) |
| `/api/realtime/dashboard/{station}` | ✅ Latest values + health | ✅ Alert counts, MTTR |
| `/api/realtime/asset-status/{station}/{asset}` | ✅ Parameters | ✅ Active alerts |
| `/telemetry/history` | ❌ | ✅ Historical rows |
| `/api/dashboard/alert_summary` | ❌ | ✅ Aggregated alert data |
| `/ws/telemetry/{station}` | ✅ (initial_state) | ❌ (live updates from webhook) |
| `/sse/telemetry/{station}` | ✅ (every 5s poll) | ❌ |

---

## How Deduplication Flows

```
Gateway sends packet (possibly resent due to network issue)

For each reading in packet:
    dedup_key = (para_id_upper, timestamp, value)
    │
    ├── Query existing_keys from DB (all matching para_ids for this gateway)
    │
    ├── dedup_key in existing_keys?
    │       YES → increment duplicate_count, skip
    │       NO  → write to DB, add to existing_keys
    │
    └── Also checks within the same packet (in-packet dedup)

After DB commit:
    If IntegrityError (concurrent duplicate at DB level) →
        Rollback entire batch
        Return 202 with records_saved=0
```

---

## Telemetry Storage Detail

For a Clause 5.9 (fixed-interval) packet with 4 readings of one parameter:

**Input:**
```json
{"para_id": "0001000C", "prv": [5.12, 5.14, 5.18, 5.20], "prt": ["t1", "t2", "t3", "t4"]}
```

**Stored as 4 rows:**
```
id | gateway_id | para_id    | prv  | prt | is_processed
1  | 5          | 0001000C   | 5.12 | t1  | False
2  | 5          | 0001000C   | 5.14 | t2  | False
3  | 5          | 0001000C   | 5.18 | t3  | False
4  | 5          | 0001000C   | 5.20 | t4  | False
```

For a Clause 5.10 (event-based) packet with 4 readings:

**Input:**
```json
{"para_id": "0001000C", "prv": [5.12, 5.14, 5.18, 5.20], "prt": "04-11-2025 16:27:45.123"}
```

**Timestamps computed:**
- Sample 0: `16:27:45.123` (original)
- Sample 1: `16:27:45.143` (+ 20ms)
- Sample 2: `16:27:45.163` (+ 40ms)
- Sample 3: `16:27:45.183` (+ 60ms)
