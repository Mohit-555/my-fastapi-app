# 08 — Ingestion Pipeline

---

## What Ingestion Means

Ingestion is the process of receiving raw sensor data from field hardware and making it available for analysis and display. It is the most performance-critical path in RDPMS — it runs every 5 seconds per gateway, 24/7.

---

## Entry Points

RDPMS has two ingestion entry points (effectively doing the same thing):

| Endpoint | Router | Auth | Notes |
|---|---|---|---|
| `POST /webhook/parameters/fixed` | `webhook.py` | X-API-Key | Primary. Includes Prometheus metrics |
| `POST /gateway/data` | `gateway.py` | None (currently) | Legacy. Less validation |

Production gateways should use `/webhook/parameters/fixed`.

---

## Packet Types

### Fixed-Interval (Clause 5.9)

Sent periodically (every 5 seconds, configurable). Contains arrays of values + timestamps.

**Identifier in code:** `isinstance(param.prt, list) == True`

```python
# gateway.py:212
is_event_based = isinstance(param.prt, str)
# False = fixed interval (prt is a list)
```

### Event-Based (Clause 5.10)

Triggered by an asset operation (e.g., Point Machine stroke). Contains burst of high-frequency samples with a single start timestamp.

**Identifier in code:** `isinstance(param.prt, str) == True`

**Timestamp computation for sample N:**
```python
# gateway.py:218
timestamp = _offset_event_timestamp(param.prt, i, EVENT_SAMPLE_INTERVAL_MS)
# EVENT_SAMPLE_INTERVAL_MS = 20 (default from spec)
```

---

## Validation Stages

```
Stage 1: Network (Nginx)
    └── TLS certificate (if mTLS enabled)

Stage 2: Authentication (FastAPI)
    └── X-API-Key header check → 401 if wrong/missing
    └── X-SSL-Client-Verify header (if REQUIRE_MTLS=True)
    └── Gateway cert CN binding check

Stage 3: Schema validation (Pydantic, automatic)
    └── stngw_id: string required
    └── parameters: list required
    └── para_id: string (optional — None allowed for raw arrays)
    └── prv: list[float] required
    └── prt: list[str] OR str (both accepted)
    └── Returns 422 if invalid

Stage 4: Business validation (code)
    └── stngw_id length = 8 chars for station decode
    └── Duplicate check (para_id + prt + prv uniqueness)
```

---

## Para_id Handling

### Auto-Discovery

On first sight of a `para_id` not in `asset_parameters`:
```python
# webhook.py/gateway.py
db.add(AssetParameter(para_id=pid, asset_id=None, prloc=None, is_assigned=False))
```

**Purpose:** Makes the para_id visible in the admin UI immediately. Engineers can configure it without waiting for a deploy.

**Design principle:** Ingestion is never blocked by missing configuration. Data flows regardless.

### para_id Normalization

All para_ids are converted to uppercase on ingestion:
```python
para_id_upper = param.para_id.upper()
```
Source: `gateway.py:211`. This prevents `"0001000c"` and `"0001000C"` being treated as different parameters.

---

## Asset Identification

At ingestion time, RDPMS does NOT identify which asset a reading belongs to. Asset identification happens in the alert processor (step 2, async):

```
Ingestion:
    para_id → Telemetry row (no asset lookup)

Alert processor:
    para_id → AssetParameter → Asset (if assigned)
```

**Why?** Looking up the asset for every reading during ingestion would double the DB queries and slow down the synchronous webhook response.

---

## Persistence

Each reading becomes one `Telemetry` row:

```python
Telemetry(
    gateway_id=gateway.id,
    para_id="0001000C",
    prv=5.12,            # parameter reading value
    prt="04-11-2025...", # parameter reading timestamp (as-is from gateway)
    raw_payload=JSON,    # full packet context for debugging
    is_processed=False   # work queue flag
)
```

**`prt` stored as string:** Avoids timezone parsing issues. The gateway sends `"DD-MM-YYYY HH:mm:ss.SSS"` — Python's datetime handling of this format with microseconds requires special treatment. Storing raw avoids bugs from incorrect parsing at ingestion time.

**`raw_payload` stored as JSON text:** Stores the full packet including `imei`, `stngw_id`, `para_id`, `prv`, `prt`, and `packet_type`. Expensive in disk space but invaluable when debugging why a specific reading shows an unexpected value.

---

## Duplicate Handling

### App-Level (Soft Deduplication)

```python
# Build set of existing (para_id, prt, prv) triples from DB
existing_keys = {(r.para_id, r.prt, r.prv) for r in existing_rows}

for value in param.prv:
    dedup_key = (para_id_upper, timestamp, value)
    if dedup_key in existing_keys:
        duplicate_count += 1
        continue  # skip this reading
    existing_keys.add(dedup_key)  # prevent in-packet duplicates too
```

**Covers:** Gateway network retries, ISP redelivery.

**Does not cover:** Concurrent duplicate requests hitting simultaneously (different API workers handling same packet at the same instant).

### DB-Level (Hard Deduplication)

```python
# gateway.py:247-263
try:
    db.commit()
except IntegrityError:
    db.rollback()
    return {"status": "accepted", "records_saved": 0, "duplicates_skipped": ...}
```

When a DB-level unique constraint catches a concurrent duplicate → rollback the entire batch and return 202 with 0 saved. The original delivery already succeeded.

**Note:** The DB-level unique constraint (`uq_telemetry_gateway_para_prt_prv`) must exist as a migration for this to work. Check `alembic/versions/` for this migration.

---

## Malformed Packets

### Unknown para_id (No Asset Mapping Yet)

- Stored in `telemetry` table with `para_id=X`, `is_processed=False`
- `AssetParameter` row auto-created with `is_assigned=False`
- Alert processor: sees `is_assigned=False` → marks `is_processed=True` → skips
- No data loss. No error returned to gateway.

### Raw Array With No para_id (Non-Spec Shape)

```python
# gateway.py:190-209
if param.raw_unattributed is not None:
    record = Telemetry(
        gateway_id=gateway.id,
        para_id=None,
        raw_payload=json.dumps({
            "warning": "raw array received with no para_id — not recognized",
            "raw": param.raw_unattributed,
        }),
    )
```

Stored as a flagged row. Gateway is not rejected (still returns 202). Issue noted in `raw_payload` for debugging.

### Invalid Timestamp Format

`prt` is stored as a string exactly as received. Timestamp parsing happens only in the alert processor (`safe_parse_datetime()`), which has 4 fallback strategies before giving up and using `datetime.utcnow()`. Even unparseable timestamps don't cause data loss.

---

## Synchronous vs Asynchronous Processing

### Synchronous (Inside Webhook Handler)

- API key verification
- mTLS header check
- JSON parsing and Pydantic validation
- Gateway lookup/creation
- Para_id discovery
- Duplicate check
- Telemetry DB write
- Redis cache update
- WebSocket broadcast trigger (fire-and-forget asyncio task)

**Total synchronous time:** ~5-20ms for a typical packet.

### Asynchronous (Background — AlertProcessor)

- Asset resolution (para_id → AssetParameter → Asset)
- Historical data query (15-day rolling average)
- Alert logic evaluation
- Alert DB write
- Alert WebSocket broadcast

**Why this split exists:** The synchronous path must be fast (gateway waiting for 202). The asynchronous path can afford 5-second latency (alert urgency is minutes, not milliseconds).

---

## Idempotency

**Is the webhook idempotent?** Partially.

If a gateway sends the exact same packet twice:
- App-level dedup: second request skips all readings → `records_saved=0`
- DB returns 202 Accepted
- No duplicate rows in `telemetry`

**Not fully idempotent:** If the first request succeeds but the 202 response is lost in transit, the gateway retries. The duplicate check catches it. But if two different concurrent requests land at the exact same instant, only one wins; the other gets DB-level IntegrityError and rolls back.

**Retry safety:** Gateways can safely retry any failed/lost webhook request.
