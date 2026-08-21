# 04 — Complete Request / Packet Lifecycle

Tracing a real telemetry packet from a physical gateway arriving at the server all the way to an alert appearing in the frontend dashboard.

---

## The Packet

A Point Machine at Lucknow station just completed a stroke. The gateway sends:

```json
POST /webhook/parameters/fixed
X-API-Key: prod-api-key-xyz
Content-Type: application/json

{
  "imei": "867409070579912",
  "stngw_id": "456523AB",
  "parameters": [
    {
      "para_id": "0001000C",
      "prv": [5.12, 5.14, 5.18, 5.20],
      "prt": ["04-11-2025 16:27:45.123", "04-11-2025 16:27:45.125",
              "04-11-2025 16:27:45.127", "04-11-2025 16:27:45.130"]
    }
  ]
}
```

This is a Clause 5.9 (fixed-interval) packet with 4 readings.

---

## Step 1: Network → Nginx

**What enters:** Raw HTTPS request from gateway's cellular modem.

**What Nginx does:**
1. Terminates TLS (decrypts).
2. If `REQUIRE_MTLS=True`: validates the client certificate presented by the gateway. If valid, sets `X-SSL-Client-Verify: SUCCESS` and `X-SSL-Client-CN: <cert_cn>` headers.
3. If cert is invalid: closes connection at TLS handshake level. FastAPI never sees this request.
4. Forwards plain HTTP to `127.0.0.1:8000`.

**What can fail:** Bad cert → connection closed at Nginx. Expired cert → same.

---

## Step 2: FastAPI — API Key Verification

**Handler:** `app/routers/webhook.py`

**Code path:** `verify_api_key()` dependency (`webhook.py:61-72`).

**What happens:**
1. FastAPI extracts `X-API-Key` header via `APIKeyHeader`.
2. Compares to `settings.API_KEY` (from `.env`).
3. If missing → 401 `"API key missing"`.
4. If wrong → 401 `"Invalid API key"`.
5. If correct → continues.

**What can fail:** Missing/wrong API key → 401 returned immediately. Gateway never retries unless it implements retry logic.

---

## Step 3: FastAPI — mTLS Header Check

**Code path:** `verify_client_cert()` (`webhook.py:74-104`).

**What happens (when `REQUIRE_MTLS=True`):**
1. Reads `X-SSL-Client-Verify` header.
2. If not `"SUCCESS"` → 401.
3. Reads `X-SSL-Client-CN` header for the gateway's certificate identity.
4. Returns the CN for later binding check.

**What can fail:** If someone bypasses Nginx and hits port 8000 directly, the header won't be present → 401. But only if `REQUIRE_MTLS=True`.

---

## Step 4: Pydantic Validation

**Code path:** FastAPI auto-validates the request body against `GatewayDataPayload` schema.

**What is validated:**
- `stngw_id` must be present
- `parameters` must be a list
- Each parameter: `para_id` string, `prv` as list of floats, `prt` as list of strings OR single string

**What can fail:** Malformed JSON → 422 Unprocessable Entity with field-level error details.

---

## Step 5: Gateway Auto-Registration

**Handler:** `app/routers/webhook.py` (calls `_resolve_station_from_stngw_id` from `gateway.py`)

**Code path:** `webhook.py` processes `stngw_id`:
1. Queries `Gateway` table: `db.query(Gateway).filter(Gateway.stngw_id == "456523AB").first()`.
2. **If not found (first time):**
   - Decodes `stngw_id` → calls `_resolve_station_from_stngw_id()` → walks Zone/Division/Station hierarchy
   - Creates `Gateway(stngw_id="456523AB", imei="867...", station_id=<found_id>)`
   - `db.flush()` to get the gateway ID before continuing
3. **If found:** Updates IMEI if changed. Back-fills `station_id` if it was NULL.

**What can fail:** If Zone/Division/Station hierarchy doesn't exist in DB for this `stngw_id` → gateway is created with `station_id=None`. Telemetry is still saved. Alerts won't be attributed to a station.

---

## Step 6: Para-ID Auto-Discovery

**Code path:** `webhook.py:173-183`

**What happens:**
1. Collects all `para_id` values from the packet: `{"0001000C"}`.
2. Queries `AssetParameter` table for any of these that already exist.
3. For each new `para_id` not seen before: creates `AssetParameter(para_id="0001000C", asset_id=None, is_assigned=False)`.
4. This makes it visible in the admin "Configure Slave" screen immediately.

**Key design:** Ingestion is **never blocked** because a `para_id` isn't assigned to an asset yet. Telemetry flows regardless. An admin can assign it later.

---

## Step 7: Deduplication Check

**Code path:** `webhook.py:141-163` (also `gateway.py:141-164`)

**What happens:**
1. Queries all existing `(para_id, prt, prv)` triples for this gateway from the DB.
2. Builds a set `existing_keys`.
3. For each reading in the packet: if `(para_id, prt, prv)` is in `existing_keys` → skip it, increment `duplicate_count`.
4. New readings within the same packet also checked against each other (in-packet deduplication).

**Limitation:** Not race-condition-proof for concurrent requests. If two identical packets arrive simultaneously, both might pass this check. The DB-level `IntegrityError` catch at the end handles this (`webhook.py:249-263`).

---

## Step 8: Write Telemetry to Database

**Code path:** `webhook.py` or `gateway.py:229-244`

**For each non-duplicate reading:**
```python
Telemetry(
    gateway_id=gateway.id,
    para_id="0001000C",
    prv=5.12,
    prt="04-11-2025 16:27:45.123",
    raw_payload=<full JSON>,
    is_processed=False  # ← key: marks it for alert processing
)
```

**Commit:** `db.commit()` at the end. If `IntegrityError` (DB-level unique violation from concurrent duplicate) → `db.rollback()`, returns 202 with `records_saved=0`.

---

## Step 9: Redis Cache Update

**Code path:** `webhook.py` (after DB commit)

**What happens:**
```python
await redis_service.store_latest_parameter(
    stngw_id="456523AB",
    para_id="0001000C",
    value=5.20,           # latest value in the batch
    timestamp="...",
    ttl_seconds=3600
)
```

This overwrites the cached latest value for this parameter. Any WebSocket client calling `GET /api/realtime/telemetry/LKO` will see `5.20` instantly without hitting PostgreSQL.

---

## Step 10: WebSocket Broadcast

**Code path:** `webhook.py` → `safe_create_task(websocket_manager.broadcast_parameter_update(...))`

**What happens:**
- For each parameter reading, creates an asyncio task that broadcasts:
```json
{
  "type": "telemetry_update",
  "data": {
    "stngw_id": "456523AB",
    "station_code": "LKO",
    "para_id": "0001000C",
    "value": 5.12,
    "timestamp": "04-11-2025 16:27:45.123"
  }
}
```
- Sent to all WebSocket clients connected to `ws://host/ws/telemetry/LKO`.

**Response returned:** `{"status": "accepted", "records_saved": 4, "duplicates_skipped": 0}` — **202 Accepted**. The gateway's job is done.

---

## Step 11: Alert Processor (Background — ~5 seconds later)

**Handler:** `app/services/alert_processor.py:56-156`

**Code path:**
1. `asyncio.sleep(5)` expires → `_process_batch()` called.
2. Query: `db.query(Telemetry).filter(Telemetry.is_processed == False).order_by(Telemetry.id.asc()).limit(100).all()`
3. For our 4 readings of `"0001000C"`, the processor iterates each.

**For each telemetry row:**
1. `Gateway` fetched by `telemetry.gateway_id`.
2. `AssetParameter` fetched: `filter(AssetParameter.para_id == "0001000C")`.
   - If `is_assigned=False` or `asset_id=None` → skip. Mark `is_processed=True`.
3. `Asset` fetched by `asset_param.asset_id`.
4. **`alert_engine.evaluate_telemetry()`** called.

---

## Step 12: Alert Engine Dispatch

**Handler:** `app/services/alert_engine.py:29-88`

**Code path:**
1. `param_config = param_config_service.get_parameter_config("0001000C")` — looks up parameter configuration (thresholds, name, unit).
2. Checks `_is_in_maintenance_mode(asset.asset_number_code, stngw_id)` — if True, returns empty list.
3. Reads `asset.asset_type_hex == "00"` → routes to `PointMachineLogics`.

---

## Step 13: Point Machine Logic Evaluation

**Handler:** `app/services/logics/point_machine.py`

**`check_predictive_alerts()`:**
1. Fetches last 15 days of readings for this `para_id` from `Telemetry` table.
2. Calculates rolling average.
3. If current value < 80% of average AND within safe range → predictive alert candidate.

**`check_failure_alerts()`:**
1. Reads `param_config.min_fail`.
2. If `value < min_fail` AND matches known failure parameter codes → adds failure alert dict.

**Returns:** List of alert dicts, e.g.:
```python
[{"cause_code": "PT_N_VOLT_CURR_FAIL", "cause_detail": "...", "alert_type": AlertType.FAILURE}]
```

---

## Step 14: Alert Generation

**Handler:** `app/services/alert_engine.py:143-194`

**`_generate_alert()` — deduplication check:**
1. Key = `"PT-101:PT_N_VOLT_CURR_FAIL:Failure"`.
2. If key in `self.active_alerts` → skip (already active alert for this cause).
3. If key in `self.alert_history` and cleared < 1 hour ago → skip.

**If should generate:**
```python
AlertEvent(
    station_id=gateway.station_id,
    asset_id=asset.id,
    asset_no="PT-101",
    asset_type_hex="00",
    cause="PT_N_VOLT_CURR_FAIL",
    alert_type="Failure",
    alert_status="Active",
    alert_time=<timestamp>
)
```
Written to DB. Added to `self.active_alerts`.

---

## Step 15: Alert WebSocket Broadcast

**Code path:** `alert_processor.py:132-136` → `_broadcast_alert_update(alert)`

**What happens:** The new `AlertEvent` is pushed to all clients connected to `ws://host/ws/alerts/LKO`:
```json
{
  "type": "new_alert",
  "data": {
    "id": 43,
    "alert_type": "Failure",
    "asset_no": "PT-101",
    "cause": "PT_N_VOLT_CURR_FAIL",
    ...
  }
}
```

The frontend alert panel updates **in real time** without the user refreshing.

---

## Step 16: Mark Processed

```python
telemetry.is_processed = True
```
`db.commit()` at end of batch. This row will never be evaluated again.

---

## Failure Summary Table

| Step | Failure | Consequence |
|---|---|---|
| TLS Handshake | Bad client cert | Connection refused by Nginx |
| API Key check | Wrong key | 401, gateway must retry |
| JSON Validation | Bad schema | 422, gateway must fix packet |
| Gateway creation | Zone/Div/Station missing | Gateway saved with station_id=None |
| Para-ID discovery | DB error | Row not created, but telemetry continues |
| Deduplication | Concurrent duplicate | DB IntegrityError → rollback, 202 with 0 saved |
| DB write | PostgreSQL down | 500, data lost for this packet |
| Redis update | Redis down | Fallback to memory, latest value still stored |
| Alert processor | Malformed row | Row marked processed, skipped silently |
| Alert engine | Para not assigned | Alert skipped, row marked processed |
| Alert dedup | Server restart | In-memory state lost, may re-generate alerts |
