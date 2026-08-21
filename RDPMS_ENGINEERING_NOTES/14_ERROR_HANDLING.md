# 14 — Error Handling and Failure Matrix

---

## Failure Matrix

| Failure | Where Detected | HTTP Response | Recovery |
|---|---|---|---|
| Missing X-API-Key | `webhook.py:verify_api_key()` | 401 + detail | Gateway must add header |
| Wrong X-API-Key | `webhook.py:verify_api_key()` | 401 + detail | Gateway must fix key |
| Invalid mTLS cert | Nginx TLS handshake | Connection closed | Gateway must renew cert |
| Missing mTLS header (REQUIRE_MTLS=True) | `webhook.py:verify_client_cert()` | 401 | Fix Nginx config or gateway |
| Cert CN mismatch | `webhook.py:_check_gateway_cert_binding()` | 403 | Admin must update `mtls_cn` |
| Malformed JSON | FastAPI/Pydantic auto-validation | 422 + field errors | Gateway must fix packet format |
| Unknown stngw_id | None — auto-creates gateway | 202 (with station_id=None) | Admin links station manually |
| Zone/Division/Station not found | `_resolve_station_from_stngw_id()` | gateway.station_id=NULL | Admin creates hierarchy |
| Duplicate telemetry (same para_id+prt+prv) | App-level dedup check | 202 (duplicates_skipped=N) | No action needed |
| Concurrent duplicate (race) | DB IntegrityError | 202 (records_saved=0) | No action needed |
| Invalid JWT token | `get_current_user()` | 401 | Client must re-login |
| Expired JWT token | `get_current_user()` | 401 | Client must use refresh token |
| Invalid/expired refresh token | `/auth/refresh` | 401 | Client must re-login |
| Inactive user account | `get_current_user()` | 401 | Admin must re-activate |
| Rate limit exceeded | SlowAPI middleware | 429 | Wait and retry |
| para_id not assigned to asset | Alert processor | Skip (logged) | Admin assigns via Configure Slave |
| Asset in maintenance mode | AlertEngine | Skip (no alert) | Expected behavior |
| Parameter config not found | AlertEngine | Skip (no alert) | Admin must configure parameter |
| Alert already active (dedup) | AlertEngine in-memory | Skip | Expected behavior |
| DB connection failure | SQLAlchemy | 500 (API calls) / retry (background) | Restore PostgreSQL |
| Redis connection failure | RedisService | Fallback to memory | No action; works in degraded mode |
| Alert processor batch exception | alert_processor.py | Rollback + wait 30s | Auto-retry |
| Individual row exception | alert_processor.py | Row marked processed | Error in logs |
| Worker crash | OS-level | No 5xx (background only) | Restart service |
| Gunicorn OOM kill | systemd/kernel | Service restart | Reduce workers or RAM |
| Nginx down | Client-level | Connection refused | Restore Nginx |
| PostgreSQL disk full | DB-level | 500 all writes | Free disk space |

---

## Detailed Error Explanations

### 422 — Malformed Packet

FastAPI uses Pydantic models to validate all request bodies. If a gateway sends:
```json
{"stngw_id": "456523AB", "parameters": "not_a_list"}
```

FastAPI automatically returns:
```json
{
  "detail": [
    {"type": "list_type", "loc": ["body", "parameters"], "msg": "Input should be a valid list"}
  ]
}
```

The gateway must be fixed to send the correct format. No manual intervention on the server side.

---

### 500 — Database Failure

When PostgreSQL is unavailable, any route that calls `db.query(...)` will raise `sqlalchemy.exc.OperationalError`. FastAPI's default exception handler returns 500.

**No automatic retry** on HTTP requests. The client (gateway or frontend) receives 500 and must handle retries.

**Background workers:** The alert processor catches database exceptions in its batch loop and waits 30 seconds before retrying. The scheduler's individual tasks also catch exceptions.

**Data loss risk:** Telemetry packets received during a DB outage are lost. There is no local queue on the gateway side managed by RDPMS. The gateway's own retry policy determines whether lost packets are resent.

---

### Redis Fallback Degraded Mode

When Redis is unavailable:
1. `RedisService` catches the connection error.
2. Logs: `"Redis not available, using in-memory storage"`.
3. All operations use `self._memory_store` (a Python dict).
4. Multiple Gunicorn workers each have their own `_memory_store` — they don't share it.
5. Live dashboard (`/api/realtime/telemetry/{station}`) may return inconsistent results between requests (different workers have different state).

**Detection:** Check Redis connectivity with `redis-cli ping`. Check application logs for Redis warnings.

---

### Worker Crash (Background Task)

If the `alert_processor.start()` coroutine crashes without recovery, the asyncio task ends silently. No error appears in the HTTP logs. Symptoms:
- `Telemetry.is_processed=False` rows grow indefinitely
- No new alerts are generated
- Dashboard shows correct live telemetry (Redis/WebSocket still work) but alert panel goes silent

**Detection:** Query the database:
```sql
SELECT COUNT(*) FROM telemetry WHERE is_processed = FALSE;
```
If this number keeps growing without the alert processor running, the background task has died.

**Recovery:** Restart the FastAPI service.

---

### In-Memory State Loss on Restart

**AlertEngine.active_alerts:** All in-memory active alert tracking is cleared on restart. Effect: the next telemetry batch after restart may generate duplicate alerts for causes that were already active in the DB. Partially mitigated by the DB-level suppression in `create_alert_event()`.

**AlertEngine.maintenance_mode:** All in-memory maintenance windows cleared. Assets that were in maintenance mode will have alerts generated again after restart.

**AlertEngine.alert_history:** The 1-hour regeneration suppression is lost. An alert cleared 30 minutes ago may be regenerated immediately after restart.

---

## Error Monitoring

**Current state:**
- All errors logged via Python `logging` module to stdout/stderr.
- Gunicorn captures to systemd journal.
- Read with `journalctl -u fastapi.service -f`.

**Prometheus metrics** available at `GET /metrics`. Tracks:
- `webhook_requests_total` — total webhook requests by endpoint and status
- `webhook_latency_seconds` — processing latency histogram

**No error tracking service** (Sentry, Datadog, etc.) is integrated. Errors are only visible if someone actively reads the logs.

---

## What Good Looks Like in Logs

Normal operation:
```
INFO  [webhook] Accepted 4 readings for gateway 456523AB (0 duplicates)
INFO  [alert_processor] Processed 48 telemetry records, generated 0 alerts
INFO  [scheduler] Asset sync completed: 124 assets synced
```

Problem indicators:
```
ERROR [alert_processor] Error processing telemetry 12345: ...
ERROR [webhook] Error broadcasting alert: ...
WARNING [websocket_manager] Connection conn_5 timed out (no pong for 65s)
WARNING [gateway] Gateway 456523AB has no mtls_cn bound yet
ERROR [alert_processor] Error in alert processor batch: OperationalError...
```
