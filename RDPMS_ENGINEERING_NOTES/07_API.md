# 07 — API Understanding

---

## Authentication Pattern

All APIs use one of three authentication methods:

| Method | Endpoints | How |
|---|---|---|
| **Bearer JWT** | All human-facing endpoints | `Authorization: Bearer <token>` |
| **X-API-Key** | Webhook, SSE, Real-time | `X-API-Key: <key>` header |
| **None** | `/auth/login`, `/auth/register`, decode, health | Public endpoints |

---

## Critical API Design Decisions

### Why two different auth methods?

Gateways (hardware) cannot participate in a login flow — they have no interactive capability. They use a pre-configured API key. Human users log in with credentials and get a JWT.

### Why 202 for telemetry?

`POST /webhook/parameters/fixed` returns `202 Accepted` (not 200 OK). This signals to the gateway: "I have received your data and will process it eventually." The gateway doesn't wait for alert evaluation — it would time out. 202 is semantically correct for async processing.

### Why camelCase in API responses?

Frontend developers typically expect camelCase in JavaScript. The database uses snake_case. Pydantic schemas use `validation_alias` and `model_validator` to translate. Example: DB field `full_name` → API response `fullName`. Source: `app/models/schemas.py`.

---

## Key APIs Explained

---

### POST /auth/login

**Purpose:** Exchange credentials for JWT tokens.

**Input:**
```json
{"employee_id": "EMP001", "password": "Admin@123", "remember_me": false}
```

**Business logic:**
1. Look up user by `employee_id` (not email — railway engineers use employee IDs)
2. `verify_password(payload.password, user.hashed_password)` — bcrypt check
3. If `remember_me=True` → refresh token TTL = 7 days; otherwise 1 day
4. `_issue_tokens(user, db, remember_me)` — creates refresh token row in DB, returns JWT

**Why `employee_id` instead of `email`:** Railway staff are identified by employee ID in all official systems (SMMS, IRMS). Using email would create a mismatch.

**Source:** `app/routers/auth.py:76-113`

---

### POST /webhook/parameters/fixed

**Purpose:** Receive periodic telemetry from a gateway (Clause 5.9).

**Input:**
```json
{
  "imei": "867409070579912",
  "stngw_id": "456523AB",
  "parameters": [
    {"para_id": "0001000C", "prv": [5.12], "prt": ["04-11-2025 16:27:45.123"]}
  ]
}
```

**Business logic:**
1. Verify API key + optional mTLS header
2. Auto-register gateway (create row if first seen)
3. Auto-discover para_ids (create unassigned AssetParameter rows)
4. Deduplicate (skip readings with identical para_id+prt+prv)
5. Write Telemetry rows with `is_processed=False`
6. Write to Redis cache (latest value per para_id)
7. Broadcast via WebSocket (fire-and-forget)
8. Return 202

**What can fail silently:** If Redis is down, cache update is skipped (fallback). If WebSocket broadcast fails, logged but not propagated.

**Source:** `app/routers/webhook.py`

---

### GET /api/realtime/dashboard/{station_code}

**Purpose:** Single-call dashboard snapshot — all metrics, alerts, health, telemetry summary for one station.

**Input:** `station_code` path param (e.g., `"LKO"`).

**Business logic:**
1. Resolve station by `station_code`
2. Get gateways for station
3. **Redis:** get all latest parameter values → telemetry summary
4. **DB:** count active alerts → failure/predictive breakdown
5. **DB:** calculate MTTR from cleared alerts
6. **DB:** calculate health score `(total - failures) / total × 100`
7. **Redis:** get gateway health status
8. Aggregate and return

**Why this endpoint exists:** Avoids multiple roundtrips. A dashboard page loads one API call and gets everything.

**Source:** `app/routers/realtime.py`

---

### GET /api/alerts (with filters)

**Purpose:** Paginated list of alert events with filters.

**Filters:** `station_id`, `alert_type`, `alert_status`, `asset_no`, `cause`, `from_date`, `to_date`, page/page_size.

**Business logic:** Query `AlertEvent` table with joins to Station and Asset. Apply all filters. Paginate.

**Why pagination:** Alert history can have thousands of rows. Without pagination, a single API call could return megabytes of data and take seconds.

---

### POST /api/alerts/{id}/acknowledge

**Purpose:** Mark an engineer has seen and acknowledged an alert.

**Business logic:**
1. Set `AlertEvent.acknowledged = True`
2. Do NOT change `alert_status` (still Active — acknowledged doesn't mean fixed)
3. Broadcast `alert_updated` via WebSocket

**Why separate from clearing:** Acknowledgement = "I know about this problem." Clearing = "The problem is fixed." These are different states in railway operations.

---

### POST /maintenance

**Purpose:** Activate maintenance mode for an asset.

**Input:**
```json
{
  "station_id": 1,
  "asset_no": "PT-101",
  "asset_type": "Point Machine",
  "from_time": "2026-08-10T10:00:00",
  "to_time": "2026-08-10T12:00:00",
  "reason": "Scheduled inspection"
}
```

**Business logic:**
1. Write `MaintenanceMode` row to DB
2. Call `alert_engine.activate_maintenance_mode(stngw_id, asset_no, from_time, to_time)` — updates in-memory state
3. Broadcast `maintenance_update` via WebSocket

**Side effect:** From this point, the alert processor will skip alert evaluation for this asset until `to_time` passes.

---

### GET /slave-cards

**Purpose:** List all slave cards (optionally filtered by gateway).

**Why this exists:** The admin "Configure Slave" workflow needs to know which physical cards exist under a gateway before an engineer can assign a channel (CH3 on card 81) to a para_id.

---

### PUT /api/assets/parameters/configure/{id}

**Purpose:** Assign a discovered `para_id` to a specific asset, location box, slave card, and channel.

**Input:**
```json
{
  "assetId": 5,
  "prloc": "LB-01",
  "slaveCardId": 3,
  "channelNumber": "CH3"
}
```

**Business logic:**
1. Set `AssetParameter.asset_id = 5`
2. Set `AssetParameter.prloc = "LB-01"`
3. Set `AssetParameter.slave_card_id = 3`
4. Set `AssetParameter.channel_number = "CH3"`
5. Set `AssetParameter.is_assigned = True`

**Effect:** From this point, the alert processor will start evaluating this para_id for alerts.

**Source:** `app/routers/assets.py`

---

### GET /ws/telemetry/{station_code}

**Purpose:** WebSocket endpoint for real-time telemetry stream.

**Why WebSocket:** Persistent bidirectional connection. Server pushes data as soon as it arrives from gateways. No polling interval — updates within milliseconds. Client sends `pong` to keep connection alive.

**On connect:** Server sends `initial_state` message with all current values from Redis.
**Ongoing:** Server sends `telemetry_update` each time a new reading arrives.
**Client sends:** `pong` (in response to server's `ping`), `subscribe` (change filters).

---

## API Design Patterns

### Pagination

All list endpoints use `page` + `page_size` query params. Response includes `total`, `page`, `page_size`, `data` array.

### Soft Deletes

Not used. Assets and users are deleted hard from the DB. Alerts use status fields instead of deletion.

### Cascading Deletes

Handled by SQLAlchemy `cascade="all, delete-orphan"`. Deleting a station cascades to gateways, assets, alerts, maintenance records. This is intentional — no orphaned data.

### Error Responses

FastAPI default 422 for validation errors (field-level detail). Application-level errors use HTTPException with descriptive detail strings. No error codes beyond HTTP status codes.
