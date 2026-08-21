# 06 — Database Understanding

---

## Conceptual Model

Think of the database in three layers:

```
GEOGRAPHY LAYER
  Zone → Division → Station

HARDWARE LAYER
  Station → Gateway → SlaveCard → (channel→) AssetParameter

OPERATIONAL LAYER
  Asset → AssetParameter (links hardware to business object)
  Telemetry (raw readings)
  AlertEvent (detected problems)
  MaintenanceMode (suppression windows)

SECURITY/IDENTITY LAYER
  User → Role → RoleMenu → Menu
  RefreshToken
```

---

## ER Diagram (Conceptual)

```
Zone ─────────────────── Division ────────────── Station
  (1:many, cascade)       (1:many, cascade)        │
                                                   ├──── Gateway ──── SlaveCard
                                                   │         │            │
                                                   │         └── Telemetry │
                                                   │                       │
                                                   ├──── Asset ─── AssetParameter ──┘
                                                   │        (many-to-one)
                                                   ├──── AlertEvent
                                                   ├──── MaintenanceMode
                                                   └──── EquipmentRoom

User ──── Role ──── RoleMenu ──── Menu
  └────── RefreshToken
```

---

## Table: zones

**Why it exists:** Administrative top-level. Required for the 3-tier filter (zone → division → station) in every dashboard.

**Primary key:** `id` (integer, autoincrement)

**Unique constraints:**
- `zone_code` (e.g. `"NR"`) — prevents duplicate zones
- `zone_id_hex` (e.g. `"07"`) — must be unique because it's the first byte of every `stngw_id`; ambiguity here would make gateway-to-station resolution impossible

**Cascade:** `Zone → Division` (delete-orphan) — deleting a zone deletes all its divisions, stations, gateways, assets, alerts. Handle with care.

**Source:** `app/models/models.py:16`

---

## Table: divisions

**Why it exists:** Middle administrative tier. Alerts and dashboards are scoped by division.

**Foreign key:** `zone_id → zones.id`

**Important:** `division_id_hex` must be unique within a zone, but two divisions in different zones can share the same hex. The uniqueness is enforced in application logic during `stngw_id` decode — the code first narrows by zone, then by division hex. No DB-level unique constraint across zones.

**Source:** `app/models/models.py:30`

---

## Table: stations

**Why it exists:** The unit of monitoring. Every asset, gateway, alert is tied to a station.

**Foreign key:** `division_id → divisions.id`

**Important column:** `asset_types` (JSON) — stores a list of `asset_type_hex` values present at this station. Used to populate the "Asset Type" filter dropdown in the UI. Not enforced by constraints — it's advisory data.

**Source:** `app/models/models.py:46`

---

## Table: gateways

**Why it exists:** Represents the physical RTU device. Acts as the identity anchor for all telemetry — every `Telemetry` row is linked to a `gateway_id`.

**Primary key:** `id`

**Unique key:** `stngw_id` (8-char hex) — this is the device's hardware identity. Indexed for fast lookup on every telemetry packet.

**Foreign key:** `station_id → stations.id` (nullable!) — NULL means the gateway sent data before its station hierarchy was configured. The system tolerates this: data is stored, alerts are suppressed until station is linked.

**Important column:** `mtls_cn` — the X.509 certificate CN bound to this gateway. When set + `REQUIRE_MTLS=True`, a leaked API key alone cannot impersonate this gateway. The incoming cert CN must match this value.

**Source:** `app/models/models.py:69`

---

## Table: slave_cards

**Why it exists:** Maps physical I/O cards to their parent gateway. Required to support the admin "Configure Slave" workflow: assigning a `para_id` to a specific slave card + channel.

**Foreign key:** `gateway_id → gateways.id`

**Unique constraint:** `(gateway_id, card_address, card_type)` — two cards of the same type cannot share an address under the same gateway.

**Source:** `app/models/models.py:89`

---

## Table: telemetry

**Why it exists:** The time-series store. Every sensor reading from every gateway lands here.

**Primary key:** `id` (autoincrement — no natural key, readings don't have one)

**Foreign key:** `gateway_id → gateways.id`

**Indexed columns:** `para_id`, `is_processed` — these are queried together very frequently:
- Alert processor: `WHERE is_processed=False`
- Telemetry history: `WHERE gateway_id=X AND para_id=Y AND received_at BETWEEN ...`

**Critical column:** `is_processed` — the work-queue flag. `False` = alert processor has not yet evaluated this row. `True` = done. This is how a synchronous write triggers asynchronous evaluation without a message queue.

**`raw_payload`:** Stores the full JSON packet context for each reading. Expensive in disk space but valuable for debugging malformed packets.

**`prt` type:** String, not DateTime. Reason: the gateway sends timestamps in a non-ISO format (`DD-MM-YYYY HH:mm:ss.SSS`). Storing as string avoids timezone conversion bugs. Alert processor parses it when needed using `safe_parse_datetime()`.

**Source:** `app/models/models.py:124`

---

## Table: asset_parameters

**Why it exists:** Bridges hardware (`para_id` → `slave_card` channel) to business objects (`asset_id`). A `para_id` exists as soon as the first telemetry packet arrives. The assignment to an asset happens later, via admin action.

**Unique key:** `para_id` — one row per unique parameter identifier globally.

**Foreign keys:**
- `asset_id → assets.id` (nullable) — NULL until admin assigns it
- `slave_card_id → slave_cards.id` (nullable) — NULL until admin maps the channel

**`is_assigned`:** True only when both `asset_id` and `prloc` (location box) are set. The alert processor only evaluates rows where the asset parameter is assigned.

**Index:** `(asset_id, para_id)` — used by the alert processor when resolving which asset a reading belongs to.

**Source:** `app/models/models.py:589`

---

## Table: assets

**Why it exists:** The business-level asset registry. An asset is one physical piece of signalling equipment (one Point Machine, one Signal, etc.).

**Unique constraint:** `(station_gateway_id, asset_type_hex, asset_number_id)` — prevents duplicate asset registration. Even if you call create-asset twice with the same gateway/type/number, only one row is created.

**`smms_asset_code`:** Unique globally — this is the SMMS (Indian Railways central system) identifier. Unique constraint on this column.

**`asset_number_id`:** The 1-byte hex that appears in `para_id` byte position 1. E.g., asset number `"01"` means all `para_id`s starting with `AABB00XX` or `AA01XXXX` (depending on position) belong to this asset.

**Source:** `app/models/models.py:553`

---

## Table: alert_events

**Why it exists:** Records every detected problem. Used for dashboards, reports, SLA tracking, MTTR calculation.

**Indexed columns:** `alert_time`, `alert_status`, `station_id`, `asset_no`, `cause` — and composite indexes on commonly queried combinations:
- `(alert_time, alert_status)` — "show me all active alerts in the last week"
- `(station_id, alert_time)` — "show me all alerts at this station"
- `(asset_no, cause)` — "show me recurring failures for this asset"

**`feedback`:** `T/PT/F/M` — engineer's assessment of alert accuracy. Used to calculate prediction accuracy KPI.

**`rectification_time`:** When the alert was cleared. MTTR = `avg(rectification_time - alert_time)` for cleared alerts. Source: `app/routers/realtime.py:204-219`.

**Logical relationships:** `AlertEvent` has `viewonly` relationships to `AssetTypeMaster` and `AlertCauseMaster` via `primaryjoin` on string columns (not FK-enforced). This means `asset_type_hex` in `AlertEvent` references `AssetTypeMaster.asset_type_id` by value only — no DB cascade.

**Source:** `app/models/models.py:245`

---

## Table: users

**Why it exists:** Human users who log into the dashboard.

**Unique constraints:** `employee_id`, `email` — prevents duplicate accounts.

**`hashed_password`:** bcrypt hash via `passlib`. Never stored in plain text. Source: `app/auth_utils.py:22`.

**`role_id`:** FK to `roles`. Determines which menus this user can access.

**Source:** `app/models/models.py:301`

---

## Table: refresh_tokens

**Why it exists:** Refresh tokens need to be revocable. If stored only as a JWT (stateless), a stolen refresh token cannot be invalidated without rotating the signing key. Storing in DB enables per-token revocation.

**`token_hash`:** SHA-256 of the actual token string. The raw token is sent to the client but never stored. This prevents a DB dump from revealing usable tokens.

**Token rotation:** Each `/auth/refresh` call revokes the old token (`revoked_at` set) and issues a new one. Source: `app/routers/auth.py:134-136`.

**Source:** `app/models/models.py:323`

---

## Table: thresholds

**Why it exists:** Configurable alert thresholds per (asset_type, parameter_type). Station-specific overrides for cases where one station's equipment operates at different levels.

**Unique constraint:** `(asset_type_hex, parameter_type_hex, station_id)` — enforces one threshold config per parameter type per station.

**Lookup priority:** Code should always check for `station_id = <station>` first, then fall back to `station_id IS NULL` (global default). This two-level priority is a design convention — not automatically enforced by the ORM.

**Source:** `app/models/models.py:205`

---

## Transactions and Session Management

**Pattern:** FastAPI dependency `get_db()` creates a session per request:
```python
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
```

**`autocommit=False`:** Explicit `db.commit()` required. All writes within a request are in one transaction.

**`autoflush=False`:** SQLAlchemy won't flush automatically. Explicit `db.flush()` is used when you need a DB-generated ID (e.g., gateway ID) before committing.

**Background services:** Alert processor and scheduler create their own `SessionLocal()` instances, not via `get_db()`. They call `db.close()` in `finally` blocks.

---

## Migrations (Alembic)

**Location:** `alembic/versions/`

**Important migrations:**
- `add_asset_types_to_stations.py` — adds `asset_types JSON` column
- `add_asset_parameters_table.py` — adds the `asset_parameters` table

**Never auto-migrate on startup** (current design — `RUN_STARTUP_SEEDING=1` gates it). In production: run `alembic upgrade head` manually before restarting the service.

---

## Cascading Behavior

| Relationship | Cascade |
|---|---|
| Zone → Division | all, delete-orphan |
| Division → Station | all, delete-orphan |
| Station → Gateway | all, delete-orphan |
| Station → Asset | all, delete-orphan |
| Station → AlertEvent | all, delete-orphan |
| Station → MaintenanceMode | all, delete-orphan |
| Gateway → Telemetry | all, delete-orphan |
| Asset → AssetParameter | all, delete-orphan |
| User → RefreshToken | all, delete-orphan |

> ⚠️ Deleting a Zone cascades to everything below it. This is intentional (clean hierarchical data model) but dangerous in production. Always verify before deleting zones or divisions.
