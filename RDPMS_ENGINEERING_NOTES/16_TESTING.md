# 16 — Testing

---

## Current Test Coverage

RDPMS has scratch test scripts in the `scratch/` directory. These are manual/exploratory scripts, not automated test suites. There is **no pytest test suite** currently.

**Existing scratch scripts observed:**
- `test_alert_causes.py` — manual test of alert cause endpoints
- `test_live_filters.py` — manual test of live telemetry filters
- `test_cascading_filters.py` — manual test of cascading dropdown filters
- `test_deployed_api.py` — manual API tests against deployed server
- `test_deployed_dup.py` — manual test of duplicate detection

These are valuable for exploratory testing but do not provide automated regression coverage.

---

## Missing Test Coverage

| Area | Coverage | Risk |
|---|---|---|
| Unit tests for alert logic | ❌ None | High — alert rules could silently break |
| Unit tests for para_id decode | ❌ None | Medium — encoding bugs affect all analysis |
| Unit tests for stngw_id decode | ❌ None | Medium — wrong station attribution |
| Webhook ingestion tests | ❌ None | High — core data path |
| Deduplication tests | ❌ None | Medium — duplicates could flood DB |
| Alert engine deduplication | ❌ None | High — duplicate alerts in production |
| Auth flow tests | ❌ None | Medium — security regressions |
| DB migration tests | ❌ None | Low — manual verification |
| Load tests | ❌ None | High — OOM issues were discovered in production |

---

## Important Test Scenarios

### Category 1: Ingestion

**Test: Fixed-interval packet (Clause 5.9)**
```python
# Send valid packet with 4 readings
# Expect: 202, records_saved=4, duplicates_skipped=0
# Verify: 4 rows in telemetry table with is_processed=False
```

**Test: Event-based packet (Clause 5.10)**
```python
# Send packet with prt as single string (not list)
# Expect: 202, correct timestamps computed (0ms, 20ms, 40ms, 60ms offsets)
# Verify: timestamps in DB match expected offset values
```

**Test: Duplicate detection**
```python
# Send same packet twice
# First: records_saved=4, duplicates_skipped=0
# Second: records_saved=0, duplicates_skipped=4
# Verify: still only 4 rows in telemetry table
```

**Test: New gateway auto-registration**
```python
# Send packet from unknown stngw_id
# Expect: Gateway row created automatically
# Expect: station_id populated if Zone/Division/Station hierarchy exists
```

**Test: New para_id auto-discovery**
```python
# Send packet with unknown para_id
# Expect: AssetParameter row created with is_assigned=False
# Expect: telemetry row stored anyway
```

**Test: Wrong API key**
```python
# Send webhook with wrong X-API-Key
# Expect: 401 with detail "Invalid API key"
```

**Test: Malformed JSON**
```python
# Send request with prv as string instead of list
# Expect: 422 with field error on prv
```

---

### Category 2: Alert Logic

**Test: Point Machine — predictive alert**
```python
# Setup: 100 telemetry rows with value=100 (historical average=100)
# Action: send reading with value=75 (< 80% of average)
# Expect: predictive alert generated for "PT_N_VOLT_CURR_LOW"
```

**Test: Point Machine — failure alert**
```python
# Setup: param_config with min_fail=50
# Action: send reading with value=40
# Expect: failure alert generated for "PT_N_IND_VOLT_FAIL_AT_LOC"
```

**Test: Alert deduplication (in-memory)**
```python
# Action: send two readings that both cross threshold
# Expect: only ONE alert created (second deduplicated)
# Verify: active_alerts dict contains the key
```

**Test: Maintenance mode suppression**
```python
# Activate maintenance mode for asset
# Send threshold-crossing reading
# Expect: NO alert generated
```

**Test: Cleared alert regeneration window**
```python
# Generate + clear an alert
# Immediately send another threshold-crossing reading
# Expect: NO alert generated (within 1-hour window)
```

---

### Category 3: Authentication

**Test: Login with valid credentials**
```python
# POST /auth/login with correct employee_id + password
# Expect: access_token and refresh_token in response
# Verify: JWT can be decoded and contains correct employee_id
```

**Test: Login with wrong password**
```python
# Expect: 401 "Invalid employee ID or password"
```

**Test: Expired access token**
```python
# Create token with 0-second expiry
# Use it on a protected endpoint
# Expect: 401 "Invalid or expired token"
```

**Test: Refresh token rotation**
```python
# Login → get refresh_token_1
# POST /auth/refresh with refresh_token_1 → get refresh_token_2
# POST /auth/refresh with refresh_token_1 again
# Expect: 401 (token already revoked)
```

**Test: Rate limiting**
```python
# POST /auth/login 6 times in under 1 minute
# Expect: 6th request returns 429
```

---

### Category 4: para_id Encoding

**Test: Decode known para_id**
```python
decode_para_id("0001000C")
# Expected: asset_type="Point Machine", asset_number="01", parameter_type="Current DC"
```

**Test: Decode equipment room para_id**
```python
decode_para_id("F0015000")
# Expected: asset_type="Relay Room"  (not None!)
```

**Test: stngw_id decode**
```python
# Given Zone with zone_id_hex="45", Division with division_id_hex="65",
# Station with station_id_hex="23"
_resolve_station_from_stngw_id("456523AB", db)
# Expected: returns station.id for that station
```

---

### Category 5: Database

**Test: Cascade delete**
```python
# Create Zone → Division → Station → Gateway → Telemetry
# Delete Zone
# Verify: all child records deleted
```

**Test: Unique constraints**
```python
# Create AssetParameter with para_id="0001000C"
# Attempt to create another with same para_id
# Expect: IntegrityError / UniqueConstraint violation
```

---

## How to Set Up Tests

Create a `tests/` directory with:

```
tests/
├── conftest.py          (pytest fixtures: test DB, test client)
├── test_ingestion.py    (webhook + gateway tests)
├── test_alerts.py       (alert logic + deduplication)
├── test_auth.py         (login, tokens, rate limiting)
├── test_decode.py       (para_id, stngw_id decoding)
└── test_realtime.py     (Redis cache, dashboard endpoint)
```

**Test database:** Use SQLite for unit tests (no PostgreSQL needed). FastAPI's `TestClient` from `httpx` handles sync/async test cases.

**Key fixture:**
```python
@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    yield session
    session.close()
    Base.metadata.drop_all(engine)
```

---

## Testing Recommendations (Priority Order)

1. **Alert logic unit tests** — highest risk of silent bugs
2. **Ingestion deduplication tests** — data integrity
3. **Auth security tests** — JWT token handling
4. **para_id decode tests** — foundation of all analysis
5. **Integration tests for full ingestion → alert pipeline**
