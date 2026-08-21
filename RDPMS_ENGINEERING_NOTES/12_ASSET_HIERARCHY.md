# 12 — Asset Hierarchy

---

## The Physical Hierarchy

```
Zone (e.g., Northern Railway)
    └── Division (e.g., Lucknow Division)
            └── Station (e.g., Lucknow Junction)
                    └── Gateway (Master Card/RTU)
                            └── Slave Card (I/O expansion card)
                                    └── Channel (CH1-CH12)
                                            └── Sensor wire
                                                    └── Asset parameter (para_id)
```

**The administrative hierarchy** (Zone → Division → Station) is how railway operations are organized.

**The hardware hierarchy** (Gateway → Slave Card → Channel) is how physical sensors are wired.

**The logical bridge** is `AssetParameter` — it connects a `para_id` (produced by hardware) to an `Asset` (managed administratively).

---

## Zone → Division → Station

**Encoding in stngw_id:**
- Bytes 0-1: zone_id_hex
- Bytes 2-3: division_id_hex
- Bytes 4-5: station_id_hex
- Bytes 6-7: gateway number

This encoding means the system can automatically determine which station a gateway belongs to just by decoding its ID. No manual configuration needed.

**DB tables:** `zones`, `divisions`, `stations`

**Cascade:** Zone deletion cascades to all divisions, stations, gateways, assets, alerts. Irreversible.

---

## Gateway (Master Card)

**One gateway per station** (typically). May be more for large stations.

**Auto-registration:** On the first telemetry packet from a new gateway, RDPMS creates a `Gateway` row automatically. The gateway doesn't need to be pre-registered. Source: `app/routers/gateway.py:117-136`.

**Station linking:** The gateway decodes its own `stngw_id` to determine which station it belongs to. If the station doesn't exist yet in the DB, the gateway registers with `station_id=NULL`. It's back-filled when the station is added.

---

## Slave Card → Channel → para_id

**Physical reality:**
- Gateway (Master Card) has multiple physical slots
- Each slot accepts one Slave Card
- Each Slave Card has 12 channels (CH1-CH12)
- Each channel has a physical terminal screw
- A sensor wire is connected to a terminal

**In the database:**
```
SlaveCard
    ├── gateway_id  (which gateway)
    ├── card_address (hex, e.g. "81")
    └── card_type    ("Voltage", "Analog", "DI")

AssetParameter
    ├── para_id      (which sensor)
    ├── slave_card_id (which physical card)
    └── channel_number ("CH3")
```

**The assignment flow:**
1. Gateway sends telemetry → `AssetParameter(para_id=X, is_assigned=False)` created automatically
2. Admin opens "Configure Slave" screen in the UI
3. Admin selects which Slave Card and Channel this para_id comes from
4. Admin selects which Asset this parameter belongs to
5. `AssetParameter.is_assigned = True`, `asset_id`, `slave_card_id`, `channel_number` set

Until step 5, telemetry is stored but no alerts are generated.

---

## Asset

**Defined by:**
- `asset_type_hex` — what kind of device (Point Machine, Track Circuit, etc.)
- `asset_number_code` — human label (e.g., "PT-101")
- `asset_number_id` — 1-byte hex (byte 1 of para_id — encodes which asset instance)
- `station_gateway_id` — which gateway's zone this asset is under
- `smms_asset_code` — unique ID in the SMMS central system

**Unique identity:** `(station_gateway_id, asset_type_hex, asset_number_id)` — these three together uniquely identify one asset.

**Multiple parameters per asset:** A single Point Machine has many parameters:
- Peak current (Normal stroke)
- Peak current (Reverse stroke)
- Stroke time (Normal)
- Stroke time (Reverse)
- Motor temperature
- Battery voltage

Each is a separate `AssetParameter` row with its own `para_id`, all pointing to the same `asset_id`.

---

## AssetParameter — The Bridge

This is the most important join table in the system. It is the bridge between:
- Hardware world: which slave card, which channel is this reading coming from?
- Business world: which asset is this reading about?

```
para_id: "0001000C"
    │
    ├── slave_card_id → SlaveCard(gateway=456523AB, address=81, type=Voltage)
    ├── channel_number: "CH3"
    ├── asset_id → Asset(asset_no="PT-101", type="00", station=LKO)
    ├── prloc: "LB-01"   (which location box the sensor is in)
    └── is_assigned: True
```

Without this row being assigned, the alert processor can't generate any alerts for this parameter. Telemetry flows, but no analysis happens.

---

## Asset Type Master vs Asset Types on Station

**`AssetTypeMaster` table:** Global registry of all asset types (from Annexure A). 37 types. Seeded from `seed.py`. Changes only when the RDSO spec is updated.

**`Station.asset_types` (JSON column):** List of `asset_type_hex` values present at this station. Example: `["00", "20", "10"]` = Point Machines, Track Circuits, Main Signals. This is advisory data used to populate UI dropdowns. Not enforced by DB constraints. Updated by admins.

---

## Equipment Room as a Special Asset Type

Equipment rooms (Relay Room, IPS Room, Battery Room) are monitored for temperature and humidity. Per the spec, room parameters use `asset_type_hex` from `F0` to `F6`.

**In the database:**
- `EquipmentRoom` table stores the latest temperature and humidity per room
- `asset_type_hex = "F0"` in para_id = Relay Room
- These are treated like any other asset for telemetry purposes

**Special handling in code:** `ASSET_TYPE_MAP` in `app/constants.py` includes both signalling assets (`00`-`60`) and equipment room types (`F0`-`F6`). This unified lookup means `ASSET_TYPE_MAP.get("F0")` returns `("RR", "Relay Room")`.

---

## Why This Hierarchy Exists

The hierarchy solves real operational problems:

1. **Zone/Division/Station hierarchy:** Railway administration is structured this way. A JE sees only their station. A DRM sees their division. A zonal admin sees everything.

2. **Gateway auto-detection:** By encoding Z/D/S in stngw_id, there's zero manual configuration for gateway-to-station mapping.

3. **para_id encoding:** By encoding asset type + asset number + parameter type, any reading can be unambiguously attributed without additional DB lookups during ingestion.

4. **AssetParameter bridge:** Sensors don't know which asset they're on — they just produce values. The Configure Slave workflow is where human knowledge (this CH3 on card 81 is the current sensor for Point Machine PT-101) becomes machine-readable configuration.
