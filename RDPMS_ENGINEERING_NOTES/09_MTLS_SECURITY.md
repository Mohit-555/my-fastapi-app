# 09 — mTLS and Security

---

## mTLS From First Principles

### What Problem mTLS Solves

Normal TLS (HTTPS) proves to the **client** that the **server** is who it claims to be (via the server's certificate signed by a trusted CA). But it doesn't prove to the server that the *client* is who it claims to be.

In RDPMS, field gateways send telemetry to the server. We need to prevent:
1. A fake device impersonating a legitimate gateway
2. Someone who obtains a valid API key from being able to POST fake telemetry from their laptop
3. A gateway that was replaced/stolen from being able to send data using its old API key

**mTLS (mutual TLS)** solves this by requiring **both sides** to present certificates. The gateway presents a client certificate. The server verifies it was signed by the trusted CA. A leaked API key alone is insufficient — you also need the physical certificate file.

---

### Why TLS Alone Is Insufficient

With TLS only:
- Server is authenticated ✅
- Gateway is not authenticated (only API key) ❌

With API key only:
- Anyone who finds or guesses the API key can POST data ❌
- No cryptographic proof of gateway identity ❌

With mTLS:
- Server is authenticated ✅
- Gateway is authenticated with a hardware-bound private key ✅
- Even if API key leaks, attacker needs the certificate's private key (which stays on the gateway hardware) ✅

---

### Architecture: How RDPMS Implements mTLS

**TLS is terminated by Nginx, not FastAPI.** FastAPI receives plain HTTP. It cannot "see" the TLS layer.

```
Gateway (has client cert + key)
    │
    │ HTTPS (presents client cert)
    ▼
Nginx (has server cert + CA cert for client verification)
    │ Validates client cert against CA
    │ If valid: sets X-SSL-Client-Verify: SUCCESS
    │           sets X-SSL-Client-CN: <cert_CN>
    │ If invalid: drops connection (FastAPI never sees it)
    │
    │ Plain HTTP + injected headers
    ▼
FastAPI (reads X-SSL-Client-Verify header)
```

**Nginx config excerpt** (`deployment/nginx-mtls.conf.example`):
```nginx
ssl_client_certificate /etc/nginx/certs/ca.crt;  # CA that signed gateway certs
ssl_verify_client on;                              # require client cert
ssl_verify_depth 2;                                # allow intermediate CAs

proxy_set_header X-SSL-Client-Verify $ssl_client_verify;
proxy_set_header X-SSL-Client-CN $ssl_client_s_dn_cn;
```

---

### Who Presents the Certificate

**The Gateway** presents its client certificate during the TLS handshake. The private key never leaves the gateway's hardware.

**Nginx** presents the server certificate to the gateway (standard HTTPS server cert).

---

### Who Validates It

**Nginx** validates the gateway's client certificate against the trusted CA certificate (`ca.crt`). If validation fails, Nginx closes the connection before FastAPI is ever invoked.

---

### How FastAPI Knows the Connection Was Authenticated

FastAPI reads the `X-SSL-Client-Verify` header set by Nginx:

```python
# app/routers/webhook.py:74-104
def verify_client_cert(request: Request) -> Optional[str]:
    if not settings.REQUIRE_MTLS:
        return None
    verify_status = request.headers.get(settings.MTLS_VERIFY_HEADER)  # "X-SSL-Client-Verify"
    if verify_status != "SUCCESS":
        raise HTTPException(status_code=401, ...)
    cn = request.headers.get(settings.MTLS_CN_HEADER)  # "X-SSL-Client-CN"
    return cn
```

Settings in `app/database.py:33-34`:
```python
MTLS_VERIFY_HEADER: str = "X-SSL-Client-Verify"
MTLS_CN_HEADER: str = "X-SSL-Client-CN"
```

---

### What Prevents Header Spoofing

This is a critical security question. If a client could forge `X-SSL-Client-Verify: SUCCESS`, they'd bypass mTLS entirely.

**Prevention:** Nginx must be configured to **strip** these headers from incoming requests before adding its own. Without this configuration, a client who bypasses Nginx (hitting port 8000 directly or forging headers through Nginx) could set the header themselves.

**Current state:** The Nginx config must include `proxy_set_header X-SSL-Client-Verify $ssl_client_verify;` (Nginx's own variable, not the client's). This overwrites any client-set header. Port 8000 must be firewalled from external access.

> ⚠️ **If port 8000 is accessible from the internet and `REQUIRE_MTLS=True`, the system is insecure.** The firewall protecting port 8000 is a critical dependency.

---

### Per-Gateway Certificate Binding

Beyond validating the cert is signed by the CA, RDPMS can enforce that a specific gateway can only use a specific certificate CN:

```python
# app/routers/webhook.py:106-125
def _check_gateway_cert_binding(cn: Optional[str], gateway: Gateway):
    if gateway.mtls_cn is None:
        logger.warning(f"Gateway {gateway.stngw_id} has no mtls_cn bound yet")
        return  # Permissive: allow but warn
    if cn != gateway.mtls_cn:
        raise HTTPException(status_code=403, "Certificate CN mismatch")
```

**`Gateway.mtls_cn`** is set by an admin after a gateway's certificate is issued. Until it's set, any certificate from the CA is accepted (permissive mode, with warning). Once set, only that specific certificate CN is accepted — a certificate from the same CA for a *different* gateway is rejected.

**This prevents:** A rogue insider who has CA signing ability from generating a cert for gateway A and using it to impersonate gateway B. Each gateway's cert CN is unique and bound to that gateway's DB record.

---

### What Happens When Certificate Is Invalid/Expired

1. Nginx fails the TLS handshake during certificate validation.
2. Connection is closed at the network level.
3. FastAPI receives nothing — no request, no log entry.
4. Gateway must retry with a valid certificate. Dead gateway until cert is renewed.

---

### What Happens If Nginx Is Bypassed

If someone connects directly to FastAPI on port 8000:
- `X-SSL-Client-Verify` header will be absent (or they could forge it).
- If `REQUIRE_MTLS=True` and the header is absent → 401. **But only API key is really protecting this.**
- **Port 8000 must be firewalled.** This is the architectural dependency. Source: `app/database.py:27-31` (comment explicitly states this).

---

## Other Security Controls

### 1. JWT Authentication (Human Users)

**Algorithm:** HS256

**Secret key:** Hardcoded as `"change-this-to-a-long-random-secret"` in `app/auth_utils.py:11`. **This must be changed in production via environment variable or .env file.** A hardcoded secret is a critical vulnerability — anyone who reads the source code can forge any token.

**Access token:** 30 minutes TTL. Claims: `sub=employee_id`, `type=access`, `exp`.

**Validation:** `get_current_user()` in `auth_utils.py:44-59`:
1. Extracts Bearer token from `Authorization` header.
2. Decodes and verifies JWT signature + expiry.
3. Checks `type == "access"` (prevents refresh tokens from being used as access tokens).
4. Queries DB for user, checks `is_active`.

### 2. Refresh Token Security

**Why not stateless:** Stateless refresh tokens (JWTs) cannot be revoked without rotating the signing key. DB-backed tokens can be individually revoked. Source: `app/models/models.py:323`.

**Token stored as hash:** SHA-256 hash of the raw token. Raw token is sent to browser (in cookie or response body) but never stored in DB. A DB dump reveals only hashes — useless without the raw token.

**Rotation:** Each refresh call revokes the old token and issues a new one. If a refresh token is stolen and used, the legitimate user's next refresh will fail (old token already revoked). This detects token theft.

### 3. API Key Authentication (Gateways/SSE)

**Single shared key:** `settings.API_KEY` from `.env`. All gateways use the same key. This is a weakness — if one gateway is compromised and the key is extracted, all gateways' authority is compromised. mTLS per-gateway binding mitigates this.

**No key rotation mechanism** exists in current code. Reason: cannot be confirmed from code.

### 4. Rate Limiting

**Library:** SlowAPI (`app/limiter.py`)

**Limits:**
- `/auth/register`: 5 requests/minute
- `/auth/login`: 5 requests/minute
- `/auth/refresh`: 10 requests/minute
- `/auth/change-password`: 5 requests/minute

**Why:** Prevents brute-force attacks on login credentials.

**Storage:** SlowAPI uses Redis if available, falls back to memory. With memory storage and multiple Gunicorn workers, each worker has its own rate limit counter — effective limit is `limit × workers`. Source: `app/limiter.py`.

### 5. Password Hashing

**Algorithm:** bcrypt via `passlib`. Source: `app/auth_utils.py:17`.

**Why bcrypt:** bcrypt is deliberately slow (adjustable cost factor), making brute-force attacks computationally expensive. MD5/SHA hashes are fast and vulnerable.

### 6. CORS

**Configuration:** `CORSMiddleware` in `app/main.py`. Allows cross-origin requests from the frontend origin.

**Current state:** Exact origins need verification from the actual `.env` or `main.py` CORS config in production. Over-broad CORS (allow all origins) is a risk.

---

## Security Checklist

| Control | Status | Notes |
|---|---|---|
| mTLS gateway auth | ✅ Implemented | Requires Nginx config + `REQUIRE_MTLS=True` |
| API key auth | ✅ Implemented | Single shared key — weak without mTLS |
| JWT auth | ✅ Implemented | Secret key must be changed from default |
| Refresh token rotation | ✅ Implemented | Detects stolen tokens |
| Rate limiting | ✅ Implemented | Memory-based (multi-worker issue) |
| bcrypt passwords | ✅ Implemented | Standard |
| Port 8000 firewall | ⚠️ Assumed | Not enforced in code — infrastructure concern |
| Per-gateway cert binding | ✅ Implemented | Only active when `mtls_cn` is set per gateway |
| Header stripping (anti-spoof) | ⚠️ Nginx config | Must be verified in production Nginx config |
| JWT secret rotation | ❌ No mechanism | Manual restart required |
| API key rotation | ❌ No mechanism | Manual `.env` change required |
