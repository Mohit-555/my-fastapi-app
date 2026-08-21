# 10 — Background Processing

---

## Why Background Processing Is Needed

When a telemetry packet arrives, the gateway is waiting for a response. If alert evaluation happened synchronously (inside the webhook handler), you'd need to:

1. Parse the packet
2. Query the DB for this gateway, asset, parameter config
3. Query the last 15 days of telemetry for rolling averages
4. Run logic rules
5. Write alerts
6. Return response

Steps 2-5 take 50-500ms each. A packet with 24 parameters would multiply this by 24. The gateway would time out. Packet loss would occur. Under high load, database connections would be held for seconds each.

**Solution:** Decouple ingestion from evaluation using the `is_processed` flag as a work queue. The webhook writes and returns in <10ms. Evaluation happens asynchronously.

---

## Alert Processor

**Source:** `app/services/alert_processor.py`

**Class:** `AlertProcessor` (singleton `alert_processor` at module level)

**Started:** During FastAPI lifespan startup in `app/main.py`.

**How it runs:** `asyncio` coroutine on the same event loop as FastAPI:

```python
async def start(self):
    self.is_running = True
    while self.is_running:
        try:
            await self._process_batch()
            await asyncio.sleep(5)      # wait 5 seconds between batches
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Error: {e}")
            await asyncio.sleep(30)     # wait 30s on error before retry
```

---

## What the Worker Polls

**Query:** `app/services/alert_processor.py:61-63`
```python
db.query(Telemetry)
  .filter(Telemetry.is_processed == False)
  .order_by(Telemetry.id.asc())
  .limit(100)
  .all()
```

- Processes oldest-first (`.order_by(Telemetry.id.asc())`).
- Processes in batches of 100 rows.
- On an idle system, this query returns 0 rows and the worker sleeps again.

---

## How Unprocessed Records Are Identified

The `is_processed` column on the `Telemetry` table is the work queue. It is indexed (`index=True` in the model — `app/models/models.py:134`).

On every telemetry write: `is_processed=False` (the default).
After evaluation: `telemetry.is_processed = True`.
All rows are committed at the end of the batch.

---

## What Happens on Failure

### Exception During Individual Row Processing

```python
# app/services/alert_processor.py:142-145
except Exception as e:
    logger.error(f"Error processing telemetry {telemetry.id}: {e}")
    telemetry.is_processed = True   # ← still marked done
```

The row is marked processed **even on error**. This is a deliberate design: a malformed or problematic row should not block the queue forever. The error is logged. The row is abandoned.

**Downside:** If there's a bug in the logic code, affected telemetry rows are silently skipped. You'd only know by checking the logs.

### Exception During Batch Commit

```python
# app/services/alert_processor.py:152-156
except Exception as e:
    logger.error(f"Error in alert processor batch: {e}")
    db.rollback()
```

Entire batch rolls back. All 100 rows remain `is_processed=False`. The next cycle (5 seconds later) will re-process the same batch. This is correct behavior for commit failures — the batch is retried.

**Potential double-processing risk:** If the commit succeeds but the `is_processed=True` write somehow fails for some rows (theoretically impossible since they're in the same transaction, but worth understanding), those rows would be re-processed.

### Worker Crash

If the entire alert processor task crashes (unhandled exception escapes the `while` loop), the task ends. No rows will ever be processed until the FastAPI application is restarted. There is no watchdog or auto-restart for the background task beyond the outer `except asyncio.CancelledError`.

**How to detect:** `journalctl -u fastapi.service` would show the final exception. The `Telemetry.is_processed=False` rows would grow unboundedly in the DB.

---

## What the Scheduler Does

**Source:** `app/services/scheduler.py`

Separate background task that runs on a time-based schedule (daily, hourly). Tasks:

| Task | Schedule | Purpose |
|---|---|---|
| `_daily_statistics()` | Daily (midnight) | Aggregate KPI metrics |
| `_hourly_health_check()` | Hourly | Gateway health evaluation |
| `_daily_cleanup()` | Daily | Redis cleanup (currently stub) |
| `_sync_assets_from_smms()` | Daily 2:00 AM | Pull asset list from SMMS API |
| `_check_maintenance_reminders()` | Every 60 seconds | Alert if maintenance window is about to expire |

**Failure handling:** Each task has its own try/except. A failing task logs the error and the scheduler continues. No retry logic for scheduled tasks — they try again at next scheduled time.

---

## Is This a Queue or Just Polling?

**It is polling, not a queue.** 

There is no message queue (Celery, RabbitMQ, Redis Queue). The database table itself acts as the queue:
- Producer (webhook handler) inserts rows with `is_processed=False`
- Consumer (alert processor) queries for `is_processed=False` rows and updates them to `True`

**Why polling instead of a queue:** Reason cannot be confirmed from code. Likely rationale: simplicity. No additional infrastructure (Redis Queue, Celery workers). The 5-second latency is acceptable for alert generation (alerts don't need millisecond response times).

**Trade-off:** Under high ingestion rates (many devices sending simultaneously), the `is_processed=False` backlog can grow. The DB query `WHERE is_processed=False` becomes slower as unprocessed rows accumulate. With a proper queue (Redis Queue, Celery), the consumer pops tasks; with polling, the DB pays the query cost every 5 seconds regardless.

---

## Race Conditions

### Multiple Gunicorn Workers

If you run 4 Gunicorn workers, each starts its own `AlertProcessor` background task. All 4 will query `WHERE is_processed=False LIMIT 100` simultaneously every 5 seconds. They may process the same rows.

**Result:** Multiple alert generation attempts for the same telemetry row. The in-memory `AlertEngine.active_alerts` deduplication won't help — each worker has its own instance. The `create_alert_event()` function in `alerts.py` has its own suppression logic (checks if an active alert already exists for the same asset+cause), but this runs a DB query that may have race conditions too.

**Mitigation:** The current production deployment uses Gunicorn but the alert processor design assumes single-worker. **This is a known architectural gap.** The proper fix is `SELECT FOR UPDATE SKIP LOCKED` on the unprocessed query, which would serialize worker access to the queue.

---

## Processing State Machine

```
Telemetry written
    │
    │  is_processed=False
    ▼
Waiting in DB queue
    │
    │  Alert processor picks up (every 5s)
    ├─── gateway not found ──────────────► is_processed=True (skip)
    ├─── asset_param not assigned ────────► is_processed=True (skip)
    ├─── asset not found ─────────────────► is_processed=True (skip)
    ├─── in maintenance mode ─────────────► is_processed=True (no alert)
    ├─── no alert condition ──────────────► is_processed=True (no alert)
    ├─── exception in logic ──────────────► is_processed=True (error logged)
    └─── alert generated ─────────────────► is_processed=True + AlertEvent written
```

---

## Duplicate Processing Risk Summary

| Scenario | Risk | Current Mitigation |
|---|---|---|
| Single packet sent twice | Webhook deduplication (para_id+prt+prv) | ✅ |
| Two workers process same row | Both generate alert | ⚠️ Partial (alert suppression in create_alert_event) |
| Worker crash + restart | Rows reprocessed from last batch | ✅ Idempotent (row-level flag) |
| DB rollback on commit failure | Batch reprocessed next cycle | ✅ |
| Server restart | In-memory alert history lost | ⚠️ May regenerate recently-cleared alerts |
