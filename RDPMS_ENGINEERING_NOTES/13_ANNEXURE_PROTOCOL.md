# 13 — Annexure / Protocol Understanding

---

## What RDSO/SPN/257/2025 Is

RDSO/SPN/257/2025 is the Indian Railways specification that defines:
- The asset types and their hex codes (Annexure A)
- The telemetry packet format gateways must send (Annexure B)
- The alert logic rules for each asset type (Annexure C)

**All para_id encoding, packet formats, and alert rules in RDPMS directly implement this spec.** When you see a hex code or a threshold constant in the code, it maps to a table in the RDSO document.

---

## Packet Types

### Clause 5.9 — Fixed Interval Packet

**Purpose:** Periodic readings sent every 5 seconds (configurable), regardless of whether the asset is doing anything.

**Structure:**
```json
{
  "imei": "867409070579912",
  "stngw_id": "456523AB",
  "parameters": [
    {
      "para_id": "0001000C",
      "prv": [5.12, 5.14, 5.18, 5.20],
      "prt": [
        "04-11-2025 16:27:45.123",
        "04-11-2025 16:27:45.125",
        "04-11-2025 16:27:45.127",
        "04-11-2025 16:27:45.130"
      ]
    }
  ]
}
```

**Key characteristic:** `prt` is an **array** aligned 1:1 with `prv`. Each reading has its own timestamp.

**How RDPMS identifies it:** `isinstance(param.prt, list)` — the prt field is a list. Source: `app/routers/gateway.py:212`.

---

### Clause 5.10 — Event-Based Packet

**Purpose:** Triggered by a specific asset event (e.g., a Point Machine completing one stroke). Sends a burst of high-frequency samples.

**Structure:**
```json
{
  "imei": "867409070579912",
  "stngw_id": "456523AB",
  "parameters": [
    {
      "para_id": "0001000C",
      "prv": [5.12, 5.14, 5.18, 5.20, 5.22, ...],
      "prt": "04-11-2025 16:27:45.123"
    }
  ]
}
```

**Key characteristic:** `prt` is a **single string** — the timestamp of the FIRST sample only.

**Timestamp computation for samples 2–N:**
```
sample_N_timestamp = first_timestamp + (N × sampling_interval_ms)
```

Default sampling interval: 20ms. Code: `_offset_event_timestamp()` in `app/routers/gateway.py:18-38`.

---

### Webhook Packet Types

The `/webhook/` router handles additional packet types beyond raw telemetry:

| Endpoint | Packet | Purpose |
|---|---|---|
| `/webhook/parameters/fixed` | Fixed telemetry | Periodic sensor readings (5.9) |
| `/webhook/parameters/event` | Event telemetry | Event-triggered burst (5.10) |
| `/webhook/health` | Health data | Sensor connectivity status |
| `/webhook/discovery` | Discovery | Gateway announces itself + detected para_ids |
| `/webhook/time_sync_confirm` | Time sync | Gateway confirms clock sync |
| `/webhook/config_confirm` | Config confirm | Gateway confirms configuration applied |
| `/webhook/information` | Info log | Freeform message from gateway |
| `/webhook/image` | Image | Base64 image capture |

---

## para_id Encoding

### The Spec (RDSO Annexure A §3)

`para_id` is 4 bytes (8 hex characters):

```
Byte 0:  asset_type_id          — which class of asset
Byte 1:  asset_number_id        — which specific asset instance
Byte 2:  parameter_type_id      — generic measurement type (current, voltage, etc.)
Byte 3:  parameter_representation_id — how the value is aggregated (instantaneous, avg, max, ...)
```

### Examples

| para_id | Byte 0 | Byte 1 | Byte 2 | Byte 3 |
|---|---|---|---|---|
| `0001000C` | `00` (Point Machine) | `01` (asset #1) | `00` (Current DC, A) | `0C` |
| `200A000C` | `20` (DC Track Circuit) | `0A` (asset #10) | `00` (Current DC) | `0C` |
| `1000200C` | `10` (Main Signal) | `00` (asset #0) | `20` (Voltage DC) | `0C` |
| `F001500C` | `F0` (Relay Room) | `01` (room #1) | `50` (Temperature) | `0C` |

### Byte 0: asset_type_id

**Source:** `app/constants.py:4-59` (`ASSET_TYPE_MAP`)

| Hex | Asset Type |
|---|---|
| `00` | Point Machine |
| `10` | Main Signal LED |
| `20` | DC Track Circuit |
| `50` | Integrated Power Supply (IPS) |
| `F0`-`F6` | Equipment Room types |

### Byte 2: parameter_type_id

**Source:** `app/constants.py:98-118` (`GENERIC_PARAMETER_TYPE_MAP`)

| Hex | Measurement |
|---|---|
| `00` | Current DC (Amperes) |
| `20` | Voltage DC (Volts) |
| `40` | Digital (Boolean) |
| `50` | Temperature (°C) |
| `51` | Humidity (%) |
| `90` | Time (seconds) |

### Byte 3: parameter_representation_id

**Source:** `app/constants.py:190-199` (`PARAMETER_REPR_MAP`)

| Hex | Representation |
|---|---|
| `00` | Instantaneous |
| `01` | Average |
| `02` | Maximum |
| `03` | Minimum |
| `04` | RMS |
| `05` | Boolean / Status |

> ⚠️ **Critical warning from the code** (`app/constants.py:75-94`): Byte 3 (`parameter_representation_id`) is **asset-type-scoped**. Two different asset types can legitimately reuse the same byte 3 value for different parameters. Never interpret byte 3 alone. Always combine with byte 0 (asset type) to get the correct meaning. Use `param_config_service` for alert logic — not the raw byte maps.

---

## Decoding stngw_id

**Format:** `ZZ DD SS GG`
- `ZZ` = zone_id_hex (2 hex chars = 1 byte)
- `DD` = division_id_hex
- `SS` = station_id_hex
- `GG` = gateway number within the station

**Decode function:** `_resolve_station_from_stngw_id()` — `app/routers/gateway.py:41-72`

**Algorithm:**
1. Extract `zone_hex = stngw_id[0:2]`
2. Query `Zone WHERE zone_id_hex = zone_hex`
3. Extract `div_hex = stngw_id[2:4]`
4. Query `Division WHERE zone_id = zone.id AND division_id_hex = div_hex`
5. Extract `station_hex = stngw_id[4:6]`
6. Query `Station WHERE division_id = div.id AND station_id_hex = station_hex`
7. Return `station.id`

**Example:** `"456523AB"`
- Zone hex `45` → find zone with `zone_id_hex="45"`
- Division hex `65` → find division in that zone with `division_id_hex="65"`
- Station hex `23` → find station in that division with `station_id_hex="23"`
- Gateway `AB` → gateway number (not used in lookup, just part of identity)

**Decode API:** `GET /decode/stngw/{stngw_id}` — `app/routers/decode.py`

---

## Timestamp Format

Gateways send timestamps in: `DD-MM-YYYY HH:mm:ss.SSS`

Example: `"04-11-2025 16:27:45.123"`

**Parse function** (for alert processor): `safe_parse_datetime()` in `app/services/alert_processor.py:11-24`:
1. Strips ` IST` suffix if present.
2. Tries `datetime.fromisoformat()`
3. Falls back to `strptime("%Y-%m-%d %H:%M:%S.%f")`
4. Falls back to `strptime("%Y-%m-%d %H:%M:%S")`
5. Falls back to `datetime.utcnow()` if all fail.

**Parse function** (for timestamp offsetting): `_offset_event_timestamp()` in `gateway.py:18-38`:
- Pads milliseconds from 3 digits to 6 digits (Python `%f` requires 6).
- Parses with `strptime(ts_str, _GATEWAY_TS_FORMAT)` where `_GATEWAY_TS_FORMAT = "%d-%m-%Y %H:%M:%S.%f"`.

---

## Discovery Packet

When a gateway first comes online, it sends a discovery packet:

```json
POST /webhook/discovery
{
  "stngw_id": "456523AB",
  "vcc": "4500",
  "vgc": "3800",
  "version": "1.2.0",
  "parameters": ["0001000C", "0001000D", "0001000E"]
}
```

**Purpose:** Announces which `para_id`s this gateway will be sending. RDPMS creates `AssetParameter` rows for each new `para_id`. Engineers can then pre-assign them to assets before telemetry starts.

**Fields:**
- `vcc` — gateway VCC power voltage (millivolts, as string)
- `vgc` — gateway VGC power voltage (millivolts, as string)
- `version` — gateway firmware version

---

## Health Data Packet

```json
POST /webhook/health
{
  "stngw_id": "456523AB",
  "sensors": [
    {"para_id": "0001000C", "status": "healthy"},
    {"para_id": "0001000D", "status": "faulty"}
  ],
  "timestamp": "04-11-2025 16:27:45.000"
}
```

**Purpose:** Reports connectivity status of each sensor channel. "Faulty" means the channel isn't returning valid readings. This populates the health dashboard (sensor count breakdown) and triggers `health_update` WebSocket broadcasts.

---

## Non-Spec Raw Array (Edge Case)

Some gateway implementations send a bare `raw` array with no `para_id`:

```json
{"parameters": [{"raw": [0.0, 9.9, 4.7, ...]}]}
```

This is **not** part of Annexure B 5.9/5.10. RDPMS handles it as a special case — stores it with `para_id=None` and a warning in `raw_payload`, then continues. Source: `app/routers/gateway.py:190-209`.

---

## Parameter Config Service

**Source:** `app/services/parameter_config_service.py`

The `param_config_service` is a lookup table keyed by the full 4-byte `para_id`. It returns:
- `parameter_representation_name` (human-readable, e.g., `"VPT 110 DC LOC N"`)
- `min_safe`, `max_safe` — safe operating range
- `min_fail` — absolute failure threshold
- `unit`

This is what the alert logic modules use to evaluate thresholds. It is the correct way to interpret a `para_id` — asset-type-aware, not just byte-level lookup.
