# 18 — Code-to-Concept Map

---

## Core Concepts → Code

| Concept | File | Class / Function | Responsibility |
|---|---|---|---|
| **Application entry** | `app/main.py` | `app = FastAPI(lifespan=...)` | Assembles all routers, starts background services |
| **Lifespan startup** | `app/main.py` | `lifespan()` | Starts alert_processor, scheduler, db_service |
| **DB session** | `app/database.py` | `get_db()` | FastAPI dependency: per-request DB session |
| **DB engine** | `app/database.py` | `engine`, `SessionLocal` | SQLAlchemy connection pool |
| **Settings/config** | `app/database.py` | `Settings(BaseSettings)` | Reads .env, exposes settings |
| **mTLS config** | `app/database.py` | `REQUIRE_MTLS`, `MTLS_VERIFY_HEADER` | Controls mTLS enforcement |

---

## Authentication

| Concept | File | Class / Function | Responsibility |
|---|---|---|---|
| **Password hashing** | `app/auth_utils.py` | `hash_password()` / `verify_password()` | bcrypt via passlib |
| **JWT creation** | `app/auth_utils.py` | `create_access_token()` | Signs HS256 JWT with employee_id |
| **JWT validation** | `app/auth_utils.py` | `get_current_user()` | FastAPI dependency; decodes + validates JWT |
| **Refresh token** | `app/auth_utils.py` | `create_refresh_token()` | Generates random 64-byte token |
| **Refresh token hash** | `app/auth_utils.py` | `hash_refresh_token()` | SHA-256 for DB storage |
| **Login flow** | `app/routers/auth.py` | `login()` | Verifies credentials, issues tokens |
| **Token rotation** | `app/routers/auth.py` | `refresh()` | Revokes old refresh token, issues new pair |
| **Logout** | `app/routers/auth.py` | `logout()` | Revokes refresh token |
| **Rate limiting** | `app/limiter.py` | `limiter` | SlowAPI decorator on auth endpoints |

---

## Domain Model

| Concept | File | Class | Responsibility |
|---|---|---|---|
| **Zone** | `app/models/models.py:16` | `Zone` | Top-level admin hierarchy |
| **Division** | `app/models/models.py:30` | `Division` | Mid-level admin hierarchy |
| **Station** | `app/models/models.py:46` | `Station` | Monitoring unit |
| **Gateway (RTU)** | `app/models/models.py:69` | `Gateway` | Physical IoT device |
| **Slave Card** | `app/models/models.py:89` | `SlaveCard` | I/O expansion card |
| **Telemetry** | `app/models/models.py:124` | `Telemetry` | One sensor reading |
| **Waveform data** | `app/models/models.py:139` | `TelemetryWaveform` | Full burst waveform array |
| **Asset** | `app/models/models.py:553` | `Asset` | Physical signalling device |
| **Asset type lookup** | `app/constants.py:4` | `ASSET_TYPE_MAP` | hex → asset type name |
| **Asset parameter** | `app/models/models.py:589` | `AssetParameter` | Bridge: para_id ↔ asset |
| **Alert** | `app/models/models.py:245` | `AlertEvent` | Detected problem record |
| **Alert cause** | `app/models/models.py:538` | `AlertCauseMaster` | Lookup: cause_code → detail |
| **Threshold** | `app/models/models.py:205` | `Threshold` | Safe operating ranges |
| **Maintenance mode** | `app/models/models.py:503` | `MaintenanceMode` | Alert suppression window |
| **Equipment room** | `app/models/models.py:482` | `EquipmentRoom` | Temperature/humidity monitoring |
| **User** | `app/models/models.py:301` | `User` | Human operator |
| **Role** | `app/models/models.py:370` | `Role` | Permission level |
| **Menu** | `app/models/models.py:338` | `Menu` | Sidebar nav item |
| **RoleMenu** | `app/models/models.py:450` | `RoleMenu` | Role ↔ Menu access mapping |
| **Refresh token** | `app/models/models.py:323` | `RefreshToken` | DB-backed JWT refresh store |

---

## Ingestion Pipeline

| Concept | File | Function | Responsibility |
|---|---|---|---|
| **Primary ingestion** | `app/routers/webhook.py` | `receive_fixed_parameters()` | Handles Clause 5.9 packets |
| **Gateway ingestion** | `app/routers/gateway.py` | `receive_gateway_data()` | Legacy ingestion endpoint |
| **API key auth** | `app/routers/webhook.py` | `verify_api_key()` | Validates X-API-Key header |
| **mTLS header check** | `app/routers/webhook.py` | `verify_client_cert()` | Reads Nginx mTLS headers |
| **Per-gateway cert binding** | `app/routers/webhook.py` | `_check_gateway_cert_binding()` | CN must match gateway.mtls_cn |
| **stngw_id decode** | `app/routers/gateway.py` | `_resolve_station_from_stngw_id()` | Gateway ID → station lookup |
| **Event timestamp offset** | `app/routers/gateway.py` | `_offset_event_timestamp()` | Computes sample timestamps for Clause 5.10 |
| **Deduplication** | `app/routers/gateway.py` | `receive_gateway_data()` | para_id+prt+prv uniqueness check |
| **Para_id auto-discovery** | `app/routers/gateway.py` | `receive_gateway_data()` | Creates unassigned AssetParameter rows |
| **Redis cache write** | `app/services/redis_service.py` | `store_latest_parameter()` | Writes latest value after each ingestion |

---

## Alert System

| Concept | File | Class / Function | Responsibility |
|---|---|---|---|
| **Background loop** | `app/services/alert_processor.py` | `AlertProcessor.start()` | Async polling loop, every 5s |
| **Batch processing** | `app/services/alert_processor.py` | `AlertProcessor._process_batch()` | Processes 100 unprocessed rows |
| **Alert dispatcher** | `app/services/alert_engine.py` | `AlertEngine.evaluate_telemetry()` | Routes to asset-specific logic |
| **Point Machine logic** | `app/services/logics/point_machine.py` | `PointMachineLogics` | Failure + predictive rules for EOP |
| **Track Circuit logic** | `app/services/logics/track_circuit.py` | `TrackCircuitLogics` | Rules for DCT |
| **Signal logic** | `app/services/logics/signal.py` | `SignalLogics` | Rules for LED/signal types |
| **IPS logic** | `app/services/logics/ips.py` | `IPSLogics` | Rules for IPS power supply |
| **Alert dedup (memory)** | `app/services/alert_engine.py` | `AlertEngine._should_generate_alert()` | Checks active_alerts + history |
| **Alert creation** | `app/services/alert_engine.py` | `AlertEngine._generate_alert()` | Writes AlertEvent to DB |
| **Maintenance check** | `app/services/alert_engine.py` | `AlertEngine._is_in_maintenance_mode()` | In-memory suppression check |
| **Maintenance activation** | `app/services/alert_engine.py` | `AlertEngine.activate_maintenance_mode()` | Sets in-memory window |
| **Parameter config** | `app/services/parameter_config_service.py` | `param_config_service.get_parameter_config()` | Threshold lookup by para_id |

---

## Real-Time / WebSocket

| Concept | File | Class / Function | Responsibility |
|---|---|---|---|
| **Connection registry** | `app/services/websocket_manager.py` | `ConnectionManager` | Tracks all WebSocket clients |
| **Connect client** | `app/services/websocket_manager.py` | `ConnectionManager.connect()` | Accepts WS, starts heartbeat |
| **Heartbeat** | `app/services/websocket_manager.py` | `ConnectionManager._heartbeat_loop()` | Pings every 30s, drops stale |
| **Broadcast telemetry** | `app/services/websocket_manager.py` | `broadcast_parameter_update()` | Pushes telemetry_update to station |
| **Broadcast alert** | `app/services/websocket_manager.py` | `broadcast_alert()` | Pushes new_alert to station |
| **Broadcast health** | `app/services/websocket_manager.py` | `broadcast_health_update()` | Pushes health_update |
| **Broadcast maintenance** | `app/services/websocket_manager.py` | `broadcast_maintenance_mode()` | Pushes maintenance_update |
| **WS telemetry endpoint** | `app/routers/websocket.py` | `websocket_telemetry()` | ws://host/ws/telemetry/{station} |
| **WS alerts endpoint** | `app/routers/websocket.py` | `websocket_alerts()` | ws://host/ws/alerts/{station} |
| **WS health endpoint** | `app/routers/websocket.py` | `websocket_health()` | ws://host/ws/health/{station} |
| **SSE telemetry** | `app/routers/sse.py` | `sse_telemetry()` | GET /sse/telemetry/{station} |
| **SSE alerts** | `app/routers/sse.py` | `sse_alerts()` | GET /sse/alerts/{station} |
| **SSE health** | `app/routers/sse.py` | `sse_health()` | GET /sse/health/{station} |
| **Async task safety** | `app/routers/webhook.py` | `safe_create_task()` | Guards asyncio.create_task |

---

## Cache / Redis

| Concept | File | Class / Function | Responsibility |
|---|---|---|---|
| **Redis service** | `app/services/redis_service.py` | `RedisService` | Redis ops with memory fallback |
| **Store latest value** | `app/services/redis_service.py` | `store_latest_parameter()` | Writes latest reading (TTL 3600s) |
| **Get latest values** | `app/services/redis_service.py` | `get_all_station_parameters()` | Bulk read for dashboard |
| **Memory fallback** | `app/services/redis_service.py` | `self._memory_store` | In-process dict when Redis down |

---

## Decode / Protocol

| Concept | File | Function | Responsibility |
|---|---|---|---|
| **Asset type map** | `app/constants.py:4` | `ASSET_TYPE_MAP` | hex → (code, name) for all asset types |
| **Equipment room map** | `app/constants.py:46` | `EQUIPMENT_ROOM_TYPE_MAP` | F0-F6 hex → room type |
| **Generic param type map** | `app/constants.py:98` | `GENERIC_PARAMETER_TYPE_MAP` | Byte 2 → measurement type |
| **Param representation map** | `app/constants.py:190` | `PARAMETER_REPR_MAP` | Byte 3 → aggregation type |
| **stngw_id decode API** | `app/routers/decode.py` | `decode_gateway_id()` | GET /decode/stngw/{id} |
| **para_id decode API** | `app/routers/decode.py` | `decode_para_id()` | GET /decode/para/{id} |
| **Timestamp parse** | `app/services/alert_processor.py` | `safe_parse_datetime()` | Multi-fallback prt parsing |

---

## Background / Scheduler

| Concept | File | Class / Function | Responsibility |
|---|---|---|---|
| **Scheduler** | `app/services/scheduler.py` | `TaskScheduler` | Periodic task runner |
| **Daily stats** | `app/services/scheduler.py` | `_daily_statistics()` | Aggregates KPIs |
| **Asset SMMS sync** | `app/services/scheduler.py` | `_sync_assets_from_smms()` | Pulls assets from SMMS API |
| **Maintenance reminders** | `app/services/scheduler.py` | `_check_maintenance_reminders()` | Alerts for expiring maintenance |

---

## Admin

| Concept | File | Router / Function | Responsibility |
|---|---|---|---|
| **User management** | `app/routers/admin.py` | `create_user()`, `update_user()` | Admin creates/manages users |
| **Role management** | `app/routers/admin.py` | `create_role()`, `assign_menus()` | Role + menu permission setup |
| **Alert cause master** | `app/routers/admin.py` | `create_alert_cause()` | Manages alert cause library |
| **Configure Slave** | `app/routers/assets.py` | `assign_parameter()` | Maps para_id → asset + slave card |
| **Default RBAC seed** | `app/rbac_defaults.py` | `ensure_default_*()` functions | Seeds zones, roles, menus, admin user |
