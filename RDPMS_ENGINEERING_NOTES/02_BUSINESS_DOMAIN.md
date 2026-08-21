# 02 — Business Domain

> Understand the domain FIRST. The code is just an implementation of these concepts.

---

## Zone

**What it is:** The top-level administrative division of Indian Railways. There are 16 zones (Central Railway, Northern Railway, etc.), each with a headquarters city.

**Why it exists:** Railway operations are administered zone-by-zone. Every asset is ultimately owned by a zone. RDPMS must show zone-level dashboards to DRMs and zonal chiefs.

**In code:** `Zone` model — `app/models/models.py:16`. Field `zone_id_hex` is a 2-character hex string (e.g., `"07"` = Northern Railway). This hex is the **first 2 bytes** of the `stngw_id` (gateway ID), enabling automatic station lookup by decoding the gateway ID.

**In database:** Table `zones`. 16 rows seeded from `seed.py` using RDSO/SPN/257/2025 Annexure-A data.

---

## Division

**What it is:** A sub-unit of a zone. E.g., Lucknow Division under Northern Railway.

**Why it exists:** Divisions manage the actual station infrastructure. A Division Railway Manager (DRM) oversees all stations in his division.

**In code:** `Division` model — `app/models/models.py:30`. Field `division_id_hex` = bytes 2-3 of `stngw_id`.

**Relationship:** `Division → Zone` (many-to-one). Cascade delete: deleting a zone deletes all its divisions.

---

## Station

**What it is:** A physical railway station where signalling equipment is installed.

**Why it exists:** All assets, gateways, alerts, and maintenance records are scoped to a station. A station is the atomic unit of monitoring.

**In code:** `Station` model — `app/models/models.py:46`. Field `station_id_hex` = bytes 4-5 of `stngw_id`. Field `asset_types` (JSON) stores which asset types are installed at this station — used for UI dropdowns.

**Relationship:** `Station → Division` (many-to-one).

---

## Gateway (RTU / Master Card)

**What it is:** The physical hardware device installed at a station that reads sensors and sends data to RDPMS. Also called an **RTU** (Remote Terminal Unit) or **Master Card**.

**Why it exists:** Sensors don't connect to the internet directly. The Gateway is the bridge between the physical sensor world and the RDPMS API.

**In code:** `Gateway` model — `app/models/models.py:69`. Identified by `stngw_id` (8-character hex, unique). The gateway auto-registers on first telemetry packet — no pre-provisioning needed.

**Key field:** `mtls_cn` — the X.509 certificate Common Name bound to this gateway. If set, the webhook layer verifies that the presented client certificate matches. Source: `app/routers/webhook.py:106-120`.

**Decoding `stngw_id`:** `stngw_id = ZZ DD SS GG` where:
- `ZZ` = zone_id_hex
- `DD` = division_id_hex
- `SS` = station_id_hex
- `GG` = gateway number within the station

Example: `"456523AB"` → Zone `45`, Division `65`, Station `23`, Gateway `AB`.

Decode function: `_resolve_station_from_stngw_id()` in `app/routers/gateway.py:41`.

---

## Slave Card

**What it is:** A physical I/O card plugged into the Gateway/Master Card. Each slave card has multiple physical channels (CH1–CH12). Sensors are wired to these channels.

**Why it exists:** A single Gateway can't have enough physical terminals to connect all sensors. Slave cards expand the number of channels. Each slave card has an address (e.g., `"81"`) and a type (Voltage, Analog, DI).

**In code:** `SlaveCard` model — `app/models/models.py:89`. Unique constraint: `(gateway_id, card_address, card_type)`.

**Hierarchy:** `Gateway → Slave Card → Channel → para_id`

---

## Asset

**What it is:** A physical signalling device at a station. Examples: Point Machine PT-101, Signal SIG-02, Track Circuit TC-03.

**Why it exists:** Alerts and telemetry must be attributed to a specific piece of equipment. "Peak current is high" is meaningless unless you know it's for Point Machine PT-101 at Lucknow station.

**In code:** `Asset` model — `app/models/models.py:553`.

**Key fields:**
- `smms_asset_code` — the unique ID from the SMMS (Indian Railways asset system)
- `asset_number_code` — human-readable ID like `"PT-101"`
- `asset_number_id` — 1-byte hex, part of `para_id`
- `asset_type_hex` — which type of asset (see Asset Type below)
- `station_gateway_id` — which gateway serves this asset

**Unique constraint:** `(station_gateway_id, asset_type_hex, asset_number_id)` — ensures no duplicate asset registration for the same gateway.

---

## Asset Type

**What it is:** The category of signalling equipment. E.g., Point Machine (`"00"`), DC Track Circuit (`"20"`), Main Signal (`"10"`), IPS (`"50"`).

**Why it exists:** Different asset types have completely different parameters and different alert logic. A Point Machine's alerts are evaluated by different rules than a Track Circuit's alerts.

**In code:** `ASSET_TYPE_MAP` — `app/constants.py:4`. 37 asset types defined per RDSO/SPN/257/2025 Annexure-A. Also in database as `AssetTypeMaster` table (`app/models/models.py:524`).

**How it's used:** `asset_type_hex` (byte 0-1 of `para_id`) is used by the `AlertEngine` to route telemetry to the correct logic handler (`app/services/alert_engine.py:69-87`).

---

## para_id

**What it is:** An 8-character hex string that uniquely identifies a specific parameter being measured on a specific asset at a specific station. It is the fundamental key for all telemetry.

**Why it exists:** Every sensor reading must be identifiable. `para_id` encodes the full path from asset type down to the specific measurement.

**Structure** (per RDSO/SPN/257/2025 Annexure-A §3):

```
para_id = AA BB CC DD
          ↑↑ ↑↑ ↑↑ ↑↑
          │  │  │  └─ parameter_representation_id (how the value is aggregated)
          │  │  └──── parameter_type_id (generic measurement type: current, voltage, etc.)
          │  └─────── asset_number_id (which specific asset within this type at this station)
          └────────── asset_type_id (which kind of asset: 00=Point Machine, 20=TrackCircuit...)
```

**Example:** `"0001000C"`
- `00` → Point Machine
- `01` → Asset number 01 (e.g., PT-101)
- `00` → Current DC (in Amperes)
- `0C` → representation byte

**Decode function:** `app/routers/decode.py` — exposes `/decode/para/{para_id}`.

> ⚠️ **Important:** The `parameter_representation_id` byte is **asset-type-scoped**. Two different asset types can reuse the same byte for different meanings. Never use the representation byte alone without knowing the asset type first. See `app/constants.py:75-95` for the detailed note on this.

---

## Telemetry

**What it is:** A single sensor reading. One row in the `telemetry` table = one value of one parameter at one point in time.

**Why it exists:** This is the raw data that drives all analysis. Everything else — alerts, reports, dashboards — is derived from telemetry.

**In code:** `Telemetry` model — `app/models/models.py:124`.

**Key fields:**
- `para_id` — which parameter
- `prv` — parameter reading value (float)
- `prt` — parameter reading timestamp (string in gateway format)
- `raw_payload` — full JSON from gateway, stored for debugging
- `is_processed` — has the alert processor evaluated this row yet?
- `received_at` — when RDPMS received it (server clock)

**Why `is_processed` exists:** The alert processor is a background polling loop. It needs to know which telemetry rows haven't been checked for alerts yet. This flag is the work queue. Source: `app/models/models.py:134`, consumed by `app/services/alert_processor.py:61-63`.

---

## TelemetryWaveform

**What it is:** A full array of samples captured during one Point Machine operation (e.g., 230 samples of current every 20ms during one stroke). Stored separately because only some readings carry waveform data.

**In code:** `TelemetryWaveform` — `app/models/models.py:139`. Field `raw` is JSON (the full array).

---

## Alert

**What it is:** A record that something went wrong (Failure) or is about to go wrong (Predictive) with a specific asset.

**Two types:**
- **Failure** — the asset is currently malfunctioning. Requires immediate attention.
- **Predictive** — the asset's readings are trending toward failure. Needs investigation.

**Lifecycle:** `Active → Acknowledged → Cleared`

**In code:** `AlertEvent` model — `app/models/models.py:245`.

**Key fields:**
- `alert_type` — `"Failure"` or `"Predictive"`
- `alert_status` — `"Active"`, `"Cleared"`
- `cause` — cause code (e.g., `"PT_N_VOLT_CURR_FAIL"`)
- `acknowledged` — has an engineer seen this alert?
- `feedback` — engineer's assessment: T (true), PT (partially true), F (false), M (maintenance)
- `rectification_time` — when was it fixed? Used to calculate MTTR.

---

## Threshold

**What it is:** A configured safe operating range for a parameter. Values outside this range trigger alerts.

**In code:** `Threshold` model — `app/models/models.py:205`. Has `warning_low/high` and `critical_low/high`.

**Priority:** Station-specific threshold overrides global default (`station_id IS NULL`).

---

## Maintenance Mode

**What it is:** A time window during which alerts for a specific asset are suppressed. Used when an engineer is physically working on the asset and known abnormal readings are expected.

**Why it exists:** Without maintenance mode, an engineer working on a Point Machine would generate hundreds of false alerts while the machine is powered off.

**In code:** `MaintenanceMode` — `app/models/models.py:503`. Checked by `AlertEngine._is_in_maintenance_mode()` in `app/services/alert_engine.py:90-100`.

**Important limitation:** Maintenance mode is stored **in-memory** in the `AlertEngine` singleton (`self.maintenance_mode` dict). If the server restarts, in-memory maintenance mode is lost. The database record persists but the in-memory check won't know about existing windows until they're re-activated. See `app/services/alert_engine.py:27`.

---

## IMEI

**What it is:** The hardware identifier of the SIM/modem inside the Gateway. Used for cellular network identification.

**In code:** `Gateway.imei` — `app/models/models.py:74`. Sent in every telemetry packet. Updated automatically if it changes (`app/routers/gateway.py:130`).

---

## Equipment Room

**What it is:** The physical rooms at a station that house signalling equipment (Relay Room, IPS Room, Battery Room). Temperature and humidity inside these rooms is also monitored.

**In code:** `EquipmentRoom` — `app/models/models.py:482`. Asset type hex `F0`-`F6` in `ASSET_TYPE_MAP` represents equipment room parameters.

---

## prloc (Parameter Location)

**What it is:** The physical location box identifier where a sensor is wired. Per the RDSO spec, a single asset (e.g., one Point Machine) can have sensors in multiple different location boxes (e.g., current sensor in LB-01, voltage sensor in LB-02).

**Why it's on AssetParameter, not Asset:** Because location is per-sensor, not per-asset. `Asset.location` is a fallback for the asset as a whole. `AssetParameter.prloc` is the precise location for that specific parameter. Source: `app/models/models.py:594-601`.
