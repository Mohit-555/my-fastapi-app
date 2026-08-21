# 21 — Interview Questions

---

## Beginner Level

---

**Q: What is RDPMS?**

**A:** RDPMS is a Remote Diagnostic and Predictive Maintenance System for Indian Railways signalling infrastructure. It receives real-time electrical sensor readings from field hardware (gateways) at stations, stores them in a database, and automatically detects equipment problems before they cause failures. It exposes a web dashboard for railway engineers to monitor assets, acknowledge alerts, and plan maintenance.

**What the interviewer is testing:** Can you articulate what the system does in plain English? Do you understand the business problem, not just the code?

---

**Q: What does a gateway do in RDPMS?**

**A:** A gateway (also called RTU or Master Card) is a physical device installed at a railway station. It reads voltage, current, and other electrical parameters from signalling equipment via sensor channels (slave cards), packs them into JSON, and sends HTTP POST requests to the RDPMS server every 5 seconds. The gateway is identified by a unique 8-character hex ID called `stngw_id` that encodes which zone, division, and station it belongs to.

**What the interviewer is testing:** Understanding of IoT data ingestion. Do you know the difference between the device and the server?

---

**Q: What is a para_id?**

**A:** A para_id is an 8-character hex string that uniquely identifies one specific sensor parameter. It encodes: which type of asset (byte 0), which specific asset instance (byte 1), what kind of measurement (byte 2, e.g., current or voltage), and how the value is represented (byte 3, e.g., instantaneous or average). Example: `"0001000C"` = Point Machine (00), asset #1 (01), DC Current (00), representation 0C.

**What the interviewer is testing:** Protocol/domain knowledge. Can you explain a key encoding scheme?

---

## Intermediate Level

---

**Q: Why is Redis used in RDPMS?**

**A:** Redis is used as a cache for the latest telemetry values. Gateways send readings every 5 seconds. If the live dashboard queried PostgreSQL every time to find the latest value for each parameter, it would run expensive `DISTINCT ON` queries across millions of rows. Instead, after each telemetry write, the latest value is stored in Redis with a 1-hour TTL. The dashboard reads from Redis in microseconds. Redis is also used for gateway health state and SMMS sync results. If Redis is unavailable, the system falls back to an in-memory dict per worker.

**What the interviewer is testing:** Understanding of why caching exists. Can you explain the trade-off between consistency and performance?

---

**Q: Why does the alert processor run as a background task instead of inline in the webhook handler?**

**A:** Alert evaluation requires querying 15 days of historical data per parameter, running business logic, and potentially writing new alert records. For a packet with 24 parameters, this would add seconds to the webhook response time — the gateway would time out and resend. By writing telemetry with `is_processed=False` and returning 202 immediately, the webhook finishes in under 10ms. The background processor evaluates alerts asynchronously, every 5 seconds. The trade-off is a 5-second alert latency — acceptable for the business (engineers don't need millisecond-precise alerts).

**What the interviewer is testing:** Architecture reasoning. Synchronous vs asynchronous processing trade-offs.

---

**Q: How does refresh token rotation work and why is it important?**

**A:** When a user logs in, they get an access token (JWT, 30 minutes) and a refresh token (random string, stored in DB as SHA-256 hash). When the access token expires, the client sends the refresh token to `/auth/refresh`. The server validates it (not revoked, not expired), revokes it immediately (`revoked_at = now`), and issues a new pair. This is token rotation. It's important because: if a refresh token is stolen and used by an attacker, the legitimate user's next refresh will fail (old token was revoked by attacker's use). This detects the theft. Without rotation, a stolen refresh token would be valid forever.

**What the interviewer is testing:** Security understanding. JWT refresh token patterns.

---

**Q: How does a telemetry row become an alert?**

**A:** (Walk through the pipeline): The webhook writes a Telemetry row with `is_processed=False`. Every 5 seconds, the AlertProcessor picks up unprocessed rows in batches of 100. For each row, it looks up the gateway, then the `AssetParameter` (which maps the para_id to an asset), then the asset. It calls `AlertEngine.evaluate_telemetry()`. The engine checks if the asset is in maintenance mode (if yes, skip). It routes to the correct logic module based on `asset_type_hex` (e.g., PointMachineLogics for `00`). The logic module compares the value against historical averages and configured thresholds. If a threshold is crossed, it returns a list of alert dicts. The AlertEngine deduplicates (checks in-memory and DB) and writes a new `AlertEvent`. It broadcasts via WebSocket. The row is marked `is_processed=True`.

**What the interviewer is testing:** End-to-end system understanding. Data flow tracing.

---

## Advanced Level

---

**Q: Why was polling used instead of event-driven processing for alerts?**

**A:** The reason cannot be confirmed from the codebase. From architectural evidence: polling using the `is_processed` flag on the telemetry table requires no additional infrastructure. The DB write and the flag are in one ACID transaction — no possibility of writing data without it entering the work queue. Event-driven alternatives (Celery, Redis Queue, Kafka) add operational complexity: another service to deploy, monitor, and recover when it fails. For the current scale (tens of gateways), the 5-second polling interval is acceptable. The trade-off is: polling adds DB load every 5 seconds and doesn't scale to thousands of devices without backlog accumulation.

**What the interviewer is testing:** Do you understand the trade-offs behind architectural choices? Can you reason about "why not the alternative"?

---

**Q: The alert processor processes rows `ORDER BY id ASC LIMIT 100`. What is a potential problem with this in a multi-worker Gunicorn deployment?**

**A:** Multiple workers execute this same query simultaneously. Both Worker 1 and Worker 2 may select the same 100 rows. Both will evaluate alert logic for the same telemetry readings. Both may try to generate alerts for the same asset+cause. The in-memory deduplication (`active_alerts` dict) doesn't help — each worker has its own dict. The DB-level suppression (`create_alert_event` checks for existing active alert) partly prevents duplicate alerts, but there's a race window between the check and the insert. The proper fix is `SELECT FOR UPDATE SKIP LOCKED` — atomically marks rows as "being processed" so only one worker can claim each row. Currently, this is not implemented. Source: identified from `app/services/alert_processor.py:61-63`.

**What the interviewer is testing:** Concurrency understanding. SELECT FOR UPDATE patterns. Race conditions in background processing.

---

**Q: What would break if the JWT secret key (`SECRET_KEY` in `auth_utils.py`) leaked?**

**A:** An attacker who knows `SECRET_KEY = "change-this-to-a-long-random-secret"` can forge any JWT token for any user by crafting the payload `{"sub": "admin", "type": "access", "exp": <far future>}` and signing it with the known key. Every endpoint protected by `get_current_user()` would accept this forged token as valid — no DB lookup can detect it because JWTs are self-validating. The attacker would have full admin access. Short-term mitigation: change the secret key in `.env` and restart — this invalidates all existing tokens (users re-login). Long-term: use environment variables for secrets, never hardcode.

**What the interviewer is testing:** JWT security understanding. What "stateless" means and its security implications.

---

## Senior Level

---

**Q: How would you scale telemetry ingestion to 100,000 devices?**

**A:** Three architectural changes are needed. First: decouple ingestion from storage. The webhook handler should publish to Kafka (or Redis Streams) and return 202 immediately. A separate pool of consumer workers writes to the DB in batches of 500-1,000 rows — this multiplies write throughput by eliminating per-row commit overhead and allows horizontal scaling of writers. Second: migrate the `telemetry` table to TimescaleDB (hypertable partitioned by month). This adds automatic time-based partitioning, chunk compression for old data, and efficient time-range queries. At 100,000 devices × 10 params × 12 packets/min = 12 billion rows/year — without partitioning, this breaks PostgreSQL. Third: replace the polling alert processor with Kafka consumer groups. N worker processes each consume a partition of telemetry events. No DB polling. Horizontal scaling by adding consumers. The `is_processed` flag becomes obsolete.

**What the interviewer is testing:** Architectural thinking at scale. Specific knowledge of distributed systems patterns.

---

## Architecture Level

---

**Q: How does mTLS work in your system?**

**A:** mTLS provides mutual authentication: both client (gateway) and server prove their identity with certificates. Standard TLS only authenticates the server. In RDPMS, TLS is terminated by Nginx, not FastAPI. Nginx is configured with the CA certificate (`ssl_client_certificate ca.crt`) and `ssl_verify_client on`. When a gateway connects, it presents its client certificate. Nginx validates it against the CA. If valid, Nginx sets `X-SSL-Client-Verify: SUCCESS` and `X-SSL-Client-CN: <cert_CN>` headers and proxies to FastAPI. FastAPI reads these headers in `verify_client_cert()`. Additionally, each gateway's expected CN is stored in `Gateway.mtls_cn`. If this is set, the presented CN must match — preventing a gateway from impersonating a different gateway even if it has a valid CA-signed cert. Port 8000 must be firewalled — bypassing Nginx allows forging these headers. The `REQUIRE_MTLS` flag is currently `False` (dev-friendly default); must be set to `True` in production.

**What the interviewer is testing:** Deep TLS/mTLS understanding. Security architecture. Nginx-FastAPI integration pattern.

---

## Debugging Level

---

**Q: Telemetry is arriving (you can see it in the DB) but alerts aren't being generated. How do you debug this?**

**A:** Systematic approach:

Step 1 — Is the alert processor running?
```bash
journalctl -u fastapi.service -f | grep alert_processor
```
Look for "Processed N telemetry records". If absent, the background task has died. Fix: restart service.

Step 2 — Is there a backlog?
```sql
SELECT COUNT(*) FROM telemetry WHERE is_processed = FALSE;
```
If > 10,000, the processor is overwhelmed or stuck.

Step 3 — Is the para_id assigned to an asset?
```sql
SELECT * FROM asset_parameters WHERE para_id = '0001000C';
```
If `is_assigned=FALSE` or `asset_id IS NULL`, alerts are skipped. Fix: assign via admin "Configure Slave".

Step 4 — Is the asset in maintenance mode?
Check `maintenance_modes` table for active windows for this asset. Also check application logs for "in maintenance mode, skipping alerts".

Step 5 — Is there a parameter config?
The `param_config_service` must have a config for this `para_id`. If not, `evaluate_telemetry()` returns empty list immediately.

Step 6 — Is there an active alert already (dedup)?
```sql
SELECT * FROM alert_events WHERE asset_no = 'PT-101' AND cause = 'PT_N_VOLT_CURR_FAIL' AND alert_status = 'Active';
```
If one exists, the dedup logic suppresses new ones.

Step 7 — Check logs for errors:
```bash
journalctl -u fastapi.service | grep "ERROR.*alert"
```

**What the interviewer is testing:** Methodical debugging under pressure. Knowledge of all the places where alert generation can be silently suppressed.

---

**Q: A gateway has been sending data for 2 weeks but alerts are only arriving 45 minutes after the threshold is crossed. Why?**

**A:** The alert processor has a backlog. The telemetry table has a large number of unprocessed rows that were inserted before this gateway's readings. The processor works FIFO (`ORDER BY id ASC`) — it processes old rows before new ones. At 100 rows per 5-second cycle, 1,200 rows/minute capacity, if there are 54,000 unprocessed rows ahead in the queue, the new readings from this gateway won't be evaluated for 45 minutes. Diagnose with: `SELECT COUNT(*), MAX(received_at), MIN(received_at) FROM telemetry WHERE is_processed=FALSE`. Fix immediately: increase `batch_size` in `AlertProcessor` and reduce `processing_interval`. Long-term: horizontal alert processing workers.

**What the interviewer is testing:** Ability to reason about queue depth and processing lag. Connecting symptoms to root causes.
