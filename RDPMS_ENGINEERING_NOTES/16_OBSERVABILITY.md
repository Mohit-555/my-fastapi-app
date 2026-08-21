# 16 — Observability

---

## Current State

### Logs

**Mechanism:** Python `logging` module. Each module creates its own logger:
```python
logger = logging.getLogger("webhook")
logger = logging.getLogger("alert_processor")
logger = logging.getLogger("websocket_manager")
```

**Output:** stdout/stderr → captured by Gunicorn → forwarded to systemd journal.

**Read command:**
```bash
journalctl -u fastapi.service -f        # live
journalctl -u fastapi.service -n 1000   # last 1000 lines
journalctl -u fastapi.service --since "2026-08-10 08:00:00"
```

**Log levels used:**
- `INFO` — normal operation events (telemetry accepted, alerts processed, scheduler tasks)
- `WARNING` — non-critical issues (gateway has no mtls_cn, WebSocket pong timeout)
- `ERROR` — failures that need attention (DB errors, broadcast failures, processor exceptions)
- `DEBUG` — maintenance mode skips (not shown in production by default)

---

### Metrics

**Mechanism:** Prometheus client (`prometheus_client` library).

**Endpoint:** `GET /metrics` — returns Prometheus text format.

**Metrics exposed** (from `app/routers/webhook.py:44-55`):

| Metric | Type | Description |
|---|---|---|
| `webhook_requests_total` | Counter | Total webhook requests, labeled by endpoint and status |
| `webhook_latency_seconds` | Histogram | Webhook processing latency, labeled by endpoint |

**How to use:** Point a Prometheus scraper at `http://host/metrics`. Connect Grafana for dashboards.

**Current limitation:** Only webhook metrics are instrumented. No metrics for:
- Alert processor throughput
- DB query latency
- Redis hit/miss rate
- WebSocket connection count
- Alert generation rate

---

### Health Check

**Endpoint:** `GET /api/monitoring/health` — `app/routers/monitoring.py`

**Returns:** System health JSON (database connectivity, Redis status, component states).

**Also:** `GET /` (root) returns a simple ping/pong response.

---

## Practical Debugging Procedure: Production Breaks at 2 AM

### Step 1: Is the service running?

```bash
sudo systemctl status fastapi.service
```

If `inactive (dead)` → service crashed. Check why:
```bash
journalctl -u fastapi.service -n 200 --no-pager
```

If `active (running)` → the process is up but something is wrong at the application level.

---

### Step 2: Is the API responding?

```bash
curl -s http://localhost:8000/ | python3 -m json.tool
curl -s http://3.6.93.103/api/monitoring/health | python3 -m json.tool
```

If health check returns DB errors → PostgreSQL issue.
If health check returns Redis errors → Redis issue (degraded mode, not fatal).
If no response → Nginx or network issue.

---

### Step 3: Is PostgreSQL running?

```bash
sudo systemctl status postgresql
psql -U postgres -c "SELECT 1;"
```

If down:
```bash
sudo systemctl restart postgresql
sudo systemctl restart fastapi.service
```

---

### Step 4: Is telemetry arriving?

```sql
SELECT COUNT(*), MAX(received_at), MIN(received_at)
FROM telemetry
WHERE received_at > NOW() - INTERVAL '5 minutes';
```

If count = 0 for the last 5 minutes → no gateway is sending. Check:
- Gateway connectivity (cellular/broadband)
- Nginx: `sudo systemctl status nginx` and `sudo nginx -t`

---

### Step 5: Is the alert processor running?

```bash
journalctl -u fastapi.service | grep "Processed.*telemetry"
```

If no output in last 5 minutes, the background task may have died. Check:
```bash
journalctl -u fastapi.service | grep "Error in alert processor"
```

```sql
SELECT COUNT(*) FROM telemetry WHERE is_processed = FALSE;
```
If this number is growing → processor is stuck or dead. Restart service.

---

### Step 6: Are alerts being generated?

```sql
SELECT * FROM alert_events
ORDER BY created_at DESC
LIMIT 10;
```

If no recent alerts despite known equipment issues:
- Check if `is_processed=False` rows exist and are old (backlog)
- Check if `asset_parameters.is_assigned = FALSE` for affected parameters
- Check for maintenance mode: `SELECT * FROM maintenance_modes WHERE is_cleared=FALSE`

---

### Step 7: Are WebSocket clients connected?

Check logs for WebSocket disconnections:
```bash
journalctl -u fastapi.service | grep "WebSocket"
```

Check connection count via admin panel or add temporary debug endpoint.

---

### Step 8: Redis status

```bash
redis-cli ping
redis-cli info memory
redis-cli keys "rdpms:latest:*" | wc -l
```

If Redis is down: application falls back to memory (functional but inconsistent across workers). Non-critical for most functionality.

---

## Key Queries for Ops

```sql
-- How many unprocessed telemetry rows? (alert backlog)
SELECT COUNT(*) FROM telemetry WHERE is_processed = FALSE;

-- Which gateways are sending data right now?
SELECT g.stngw_id, MAX(t.received_at) as last_seen
FROM gateways g LEFT JOIN telemetry t ON t.gateway_id = g.id
GROUP BY g.stngw_id
ORDER BY last_seen DESC;

-- Active alerts today
SELECT station_id, asset_no, cause, alert_time
FROM alert_events
WHERE alert_status = 'Active'
ORDER BY alert_time DESC;

-- How many parameters are unassigned?
SELECT COUNT(*) FROM asset_parameters WHERE is_assigned = FALSE;

-- Recent errors in the last hour (check via logs, not DB)
-- journalctl -u fastapi.service --since "1 hour ago" | grep ERROR
```

---

## What's Missing (Gaps in Observability)

| Gap | Impact | Fix |
|---|---|---|
| No structured logging | Hard to query logs programmatically | Add JSON log formatter |
| No error tracking (Sentry) | Errors only visible if you watch logs | Integrate Sentry SDK |
| Minimal Prometheus metrics | Can't build Grafana dashboards for processing | Instrument alert processor, DB queries |
| No alerting on the monitoring system | No notification if RDPMS itself goes down | Set up uptime monitoring (UptimeRobot, Grafana alerts) |
| No distributed tracing | Can't trace a request across webhook → processor | Add OpenTelemetry |
| No log aggregation | Logs only on the server | Ship to Loki, ELK, or CloudWatch |
