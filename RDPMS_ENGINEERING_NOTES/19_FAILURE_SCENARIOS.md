# 19 — Failure Scenarios

---

## Scenario 1: Gateway Goes Silent

**What happens:** A gateway stops sending telemetry (power cut, network outage, hardware failure).

**Detection:**
- Redis keys for this gateway's parameters expire after 3600 seconds (1 hour)
- After expiry, `/api/realtime/telemetry/{station}` returns empty/null for those parameters
- Health dashboard shows gateway as "offline" (last_seen timestamp > threshold)
- No new `Telemetry` rows in DB from this gateway

**Detection query:**
```sql
SELECT g.stngw_id, MAX(t.received_at) as last_seen
FROM gateways g LEFT JOIN telemetry t ON t.gateway_id = g.id
GROUP BY g.stngw_id
HAVING MAX(t.received_at) < NOW() - INTERVAL '1 hour';
```

**System behavior:** No new alerts are generated (no new telemetry to evaluate). Existing active alerts remain. Dashboard shows last known state until Redis TTL expires.

**Impact:** Monitoring gap. If equipment fails while gateway is offline, RDPMS won't detect it until the gateway comes back online and sends data.

**Recovery:** When gateway reconnects and starts sending, ingestion resumes normally. Any backlogged readings from the gateway (if it buffers offline data) are deduplicated.

---

## Scenario 2: Database Goes Down

**What happens:** PostgreSQL crashes or becomes unreachable.

**Immediate effects:**
- All API endpoints that touch DB → 500 Internal Server Error
- Telemetry ingestion fails → gateway receives 500 → should retry
- Alert processor catches `OperationalError` → waits 30 seconds → retries
- Scheduler tasks fail → logged

**What still works:**
- Nothing that requires DB access — essentially all endpoints fail

**Data risk:** Any telemetry packets received while DB is down are **lost** (no local queue, no buffer). When DB recovers, those minutes of readings don't exist. Alerts that would have been generated from those readings are never generated.

**Recovery:** When PostgreSQL restarts, FastAPI workers detect the reconnection (via `pool_pre_ping=True`) on the next request. The alert processor retries automatically. Service resumes without restart.

**Prevention:** PostgreSQL replication (hot standby), automated backups, monitoring on `pg_ctl` status.

---

## Scenario 3: Redis Goes Down

**What happens:** Redis crashes or becomes unreachable.

**Immediate effects:**
- `RedisService` catches `ConnectionError`
- Falls back to `self._memory_store` (per-process Python dict)
- Log: `"Redis not available, using in-memory storage"`

**What still works:**
- Telemetry ingestion continues (writes to memory fallback)
- Alert processor continues (uses DB, not Redis)
- Webhook returns 202

**What degrades:**
- Live dashboard (`/api/realtime/telemetry`) may return stale or empty data if the worker handling the request is different from the worker that cached the latest value
- Multiple workers have inconsistent state
- Rate limiting reverts to per-worker memory (limits become multiplied by worker count)

**Recovery:** When Redis comes back online, `RedisService` reconnects automatically on the next call. The in-memory data is not migrated to Redis — workers rebuild the cache organically as new telemetry arrives.

---

## Scenario 4: Alert Processor Background Task Crashes

**What happens:** An uncaught exception escapes the `while self.is_running` loop. The asyncio task ends.

**Symptoms:**
- No new alerts generated (even though telemetry flows normally)
- `is_processed=False` row count grows unboundedly
- No error in HTTP access logs (it's a background task)
- Error visible only in `journalctl` output

**Detection:**
```sql
-- Growing backlog = processor may be dead
SELECT COUNT(*), MAX(received_at) 
FROM telemetry 
WHERE is_processed = FALSE;
```
If count grows over time: processor is dead.

**Recovery:** `sudo systemctl restart fastapi.service`. The processor restarts with the service.

**Backlog processing:** After restart, the processor picks up all unprocessed rows (FIFO). Alert latency = backlog_size / 1200 rows_per_minute. If 10,000 rows accumulated over 1 hour, backlog clears in ~8 minutes.

---

## Scenario 5: Server OOM Kill

**What happens:** The kernel kills FastAPI workers due to memory pressure.

**Cause (before fix):** All Gunicorn workers ran database migrations and seeding on startup, multiplying memory usage 4×.

**Cause (other):** Memory leak in long-running workers, Redis memory fallback consuming too much, or a very large webhook payload.

**After the fix:** Workers boot lightweight (~80-100MB each). `RUN_STARTUP_SEEDING` flag prevents heavy startup logic in workers.

**Symptoms in logs:**
```
Aug 03 09:22:59 ip-172-31-40-15 python[1503221]: Creating tables...
Aug 03 09:22:59 ip-172-31-40-15 python[1503222]: Creating tables...
# ... (all 4 workers seeding simultaneously = OOM)
```

**Recovery:** `sudo systemctl restart fastapi.service` — systemd restarts the service. If OOM repeats: reduce workers, add swap, or upgrade RAM.

---

## Scenario 6: Certificate Expiry (mTLS)

**What happens:** A gateway's client certificate expires.

**Gateway behavior:** TLS handshake fails (Nginx rejects the expired cert). Gateway cannot connect. No telemetry flows from this gateway.

**System behavior:** No new data, no new alerts for this gateway's assets. Looks identical to Scenario 1 (gateway silent).

**Detection:** Check Nginx error logs:
```bash
tail -f /var/log/nginx/error.log | grep "certificate"
```

**Recovery:** Reissue a new client certificate to the gateway, update `Gateway.mtls_cn` if the new cert has a different CN.

---

## Scenario 7: In-Memory State Lost After Restart

**What happens:** Server restarts (deploy, OOM, manual).

**Lost state:**
- `AlertEngine.active_alerts` — in-memory set of currently active alerts
- `AlertEngine.alert_history` — recently cleared alerts (prevents regeneration within 1 hour)
- `AlertEngine.maintenance_mode` — active maintenance windows
- `ConnectionManager.station_connections` — all WebSocket connections

**Consequences:**
1. **Duplicate alerts:** The first batch of telemetry after restart may re-generate alerts for causes already active in the DB. Partially mitigated by DB-level suppression check in `create_alert_event`.
2. **Suppression history lost:** An alert cleared 30 minutes ago may be regenerated immediately after restart.
3. **Maintenance mode lost:** An active maintenance window is not enforced until an admin re-activates it via the API.
4. **WebSocket clients disconnected:** All clients must reconnect. The frontend should implement auto-reconnect.

**Severity:** Medium. The system remains functional but may generate duplicate alerts temporarily after restart.

---

## Scenario 8: Malformed Telemetry Packet

**What happens:** A buggy gateway firmware sends invalid JSON or wrong field types.

**Stage caught:**
1. Invalid JSON body → Nginx/FastAPI returns 422 automatically before any code runs
2. Invalid field type (e.g., `prv` is a string not a list) → Pydantic 422 with field-level error
3. Unknown `para_id` format → stored in DB as-is, logged as unassigned parameter
4. Timestamp in wrong format → stored as string as-is; parsed later with fallback strategies

**System behavior:** Bad packets are rejected with 422. Good packets in a batch may be partially processed (individual parameter errors are handled per-parameter with `continue`).

**No data corruption:** Malformed rows are either rejected entirely or stored as flagged records with `raw_payload` containing diagnostic context.

---

## Scenario 9: Concurrent Duplicate Packets

**What happens:** A gateway sends a packet, doesn't receive the 202 ACK (network timeout), and resends the exact same packet. The original and duplicate arrive at two different Gunicorn workers simultaneously.

**What happens:**
1. Both workers query existing keys → neither sees the other's writes yet (not committed)
2. Both decide the readings are new
3. Both insert the same rows
4. One commits successfully
5. The other hits `IntegrityError` on commit (if DB-level unique constraint exists)
6. The second worker rolls back, returns 202 with `records_saved=0`

**If no DB-level unique constraint:** Both workers commit → duplicate rows in `telemetry` → alert processor evaluates both → potential duplicate alerts (mitigated by DB-level alert suppression).

---

## Scenario 10: Alert Processor Processes Same Row Twice (Multi-Worker)

**What happens:** Two Gunicorn workers both pick up the same `is_processed=False` rows in the same cycle.

**Result:**
1. Both call `alert_engine.evaluate_telemetry()` for the same reading
2. Both check in-memory `active_alerts` — both see the key is absent (different workers, different dicts)
3. Both attempt to create an alert
4. First worker writes `AlertEvent` and commits
5. Second worker checks DB for existing active alert (`create_alert_event` suppression query) → finds the one just written by Worker 1 → alert is suppressed
6. Both mark `telemetry.is_processed=True`
7. Net result: one alert created, telemetry marked processed twice (harmless)

**Severity:** Low — correctly handled by DB-level suppression, but adds extra DB load.

**Proper fix:** `SELECT FOR UPDATE SKIP LOCKED` on the alert processor query.
