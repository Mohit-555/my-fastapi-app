# 17 — Deployment

---

## Production Stack

| Component | Tech | Config |
|---|---|---|
| Process manager | Gunicorn (WSGI/ASGI) | Multiple workers |
| Service manager | systemd | `fastapi.service` |
| Reverse proxy | Nginx | mTLS, TLS termination |
| Database | PostgreSQL | External or local |
| Cache | Redis | `localhost:6379` |
| Python env | virtualenv (`venv/`) | `venv/bin/python` |

---

## Service Unit (`fastapi.service`)

Managed by systemd. Key commands:

```bash
sudo systemctl start fastapi.service
sudo systemctl stop fastapi.service
sudo systemctl restart fastapi.service
sudo systemctl status fastapi.service

# View live logs
journalctl -u fastapi.service -f

# View last 200 lines
journalctl -u fastapi.service -n 200 --no-pager
```

---

## Gunicorn Configuration

Workers start with `gunicorn`:
```bash
venv/bin/gunicorn app.main:app \
    -w 4 \
    -k uvicorn.workers.UvicornWorker \
    --bind 127.0.0.1:8000
```

| Flag | Value | Reason |
|---|---|---|
| `-w 4` | 4 workers | Utilize multiple CPU cores |
| `-k uvicorn.workers.UvicornWorker` | Async worker | Required for FastAPI async endpoints and WebSockets |
| `--bind 127.0.0.1:8000` | localhost only | Port 8000 must not be exposed externally |

---

## Environment Variables (.env)

```bash
DATABASE_URL=postgresql://user:password@localhost/rdpms
API_KEY=your-secure-api-key
REQUIRE_MTLS=False          # Set True in production with mTLS
SECRET_KEY=change-this      # JWT signing secret — MUST change
VENDOR_CODE=XYZ
VENDOR_NAME=XYZ Signalling Ltd
```

---

## Deployment Procedure (First Time)

```bash
# 1. Clone / update code
cd ~/my-fastapi-app
git pull origin main

# 2. Install dependencies
venv/bin/pip install -r requirements.txt

# 3. Run database migrations
venv/bin/alembic upgrade head

# 4. Seed default data (zones, roles, menus, admin user)
venv/bin/python seed.py

# 5. Start/restart service
sudo systemctl restart fastapi.service

# 6. Verify
sudo systemctl status fastapi.service
journalctl -u fastapi.service -n 50 --no-pager
curl http://localhost:8000/
```

---

## Deployment Procedure (Code Update)

```bash
git pull origin main
venv/bin/pip install -r requirements.txt  # if requirements changed

# Run new migrations if schema changed
venv/bin/alembic upgrade head

# Restart (no seed.py needed unless new default data added)
sudo systemctl restart fastapi.service
```

---

## Why `RUN_STARTUP_SEEDING` Matters

```bash
# This causes OOM on a 2GB server with 4 workers:
# Each worker runs migrations + seeding = 4× DB operations simultaneously

# Fixed: workers boot lightweight
# Only run seed.py once, manually, before restarting
RUN_STARTUP_SEEDING=1 venv/bin/python -c "from app.main import app"  # only if needed
```

The fix: `app/main.py` checks `os.environ.get("RUN_STARTUP_SEEDING")` before running heavy startup logic. Source: `app/main.py:71-95`.

---

## Nginx Configuration

**Location:** `/etc/nginx/sites-available/rdpms`

**Key sections:**
```nginx
server {
    listen 443 ssl;
    server_name your-domain.com;

    # Server certificate
    ssl_certificate /etc/nginx/certs/server.crt;
    ssl_certificate_key /etc/nginx/certs/server.key;

    # mTLS client certificate verification
    ssl_client_certificate /etc/nginx/certs/ca.crt;
    ssl_verify_client on;

    # Pass cert verification result to FastAPI
    proxy_set_header X-SSL-Client-Verify $ssl_client_verify;
    proxy_set_header X-SSL-Client-CN $ssl_client_s_dn_cn;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;    # WebSocket support
        proxy_set_header Connection "upgrade";
    }
}
```

**Reference file:** `deployment/nginx-mtls.conf.example`

---

## Redis Setup

```bash
# Install Redis
sudo apt install redis-server

# Start and enable
sudo systemctl enable redis-server
sudo systemctl start redis-server

# Verify
redis-cli ping    # should return PONG
```

RDPMS will work without Redis (in-memory fallback), but production must have Redis for consistency.

---

## Monitoring Deployment Health

After deployment:
```bash
# 1. Service running?
systemctl status fastapi.service

# 2. API responding?
curl -s http://localhost:8000/ | python3 -m json.tool
curl -s http://localhost:8000/api/monitoring/health | python3 -m json.tool

# 3. Workers booted cleanly (no seeding in logs)?
journalctl -u fastapi.service -n 50 | grep -E "Creating tables|seeding|worker"
# Should see: "worker booting" only, not "Creating tables..."

# 4. DB accessible?
journalctl -u fastapi.service -n 50 | grep -i "error\|database"

# 5. Alert processor started?
journalctl -u fastapi.service | grep "Alert processor started"
```

---

## Common Deployment Failures

| Symptom | Cause | Fix |
|---|---|---|
| Service fails to start | Missing .env or wrong DATABASE_URL | Check .env, test DB connection |
| OOM kill during startup | Startup seeding running in all workers | Ensure `RUN_STARTUP_SEEDING` is not set |
| 500 on all requests | DB migration not run | `alembic upgrade head` |
| No alerts generated | seed.py not run (no default data) | `python seed.py` |
| 401 on all gateway requests | Wrong API_KEY in .env | Update .env, restart |
| WebSocket not working | Nginx missing upgrade headers | Add `proxy_set_header Upgrade $http_upgrade` |
| Redis warning in logs | Redis not installed or not running | Install + start Redis |
