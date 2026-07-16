# Asset type lookup from RDSO/SPN/257/2025 Annexure A
# Maps asset_type_id hex → (asset_type_code, asset_type_name)

ASSET_TYPE_MAP = {
    "00": ("EOP",  "Point Machine"),
    "10": ("LED",  "Main Signal LED"),
    "11": ("LES",  "Shunt Signal"),
    "12": ("LEC",  "Calling On Signal"),
    "13": ("LER",  "Route Signal"),
    "20": ("DCT",  "DC Track Circuit"),
    "21": ("SSE",  "Single Section Axle Counter - Eldyne"),
    "22": ("SSC",  "Single Section Axle Counter - CEL"),
    "23": ("SSG",  "Single Section Axle Counter - G.G. Tronics"),
    "24": ("MSE",  "Multi Section Axle Counter - Eldyne"),
    "25": ("MSC",  "Multi Section Axle Counter - CEL"),
    "26": ("MSS",  "Multi Section Axle Counter - Siemens"),
    "27": ("ACM",  "Multi Section Axle Counter - Siemens ACM200"),
    "28": ("MSF",  "Multi Section Axle Counter - Frauscher"),
    "29": ("MSM",  "Multi Section Axle Counter - Medha"),
    "2A": ("MSG",  "Multi Section Axle Counter - G.G. Tronics"),
    "2B": ("MSA",  "Multi Section Axle Counter - Sigma Altpro"),
    "2C": ("HAG",  "High Availability Single Section Digital Axle Counter - GGtronics"),
    "2D": ("AFA",  "Audio Frequency Track Circuit - Ansaldo/Alstom"),
    "2E": ("AFS",  "Audio Frequency Track Circuit - Siemens"),
    "2F": ("AFB",  "Audio Frequency Track Circuit - Bombardier"),
    "30": ("BUA",  "Block Proving Axle Counter with UAC"),
    "31": ("BUF",  "Block Proving Axle Counter with UFSBI"),
    "32": ("SGE",  "SGE Double Line Block Instrument"),
    "33": ("DDT",  "DIODO Type Single Line Block Instrument"),
    "34": ("PBT",  "Block Instrument - Push Button"),
    "35": ("NLT",  "Block Instrument - Push Button - Neal's Token"),
    "40": ("MLC",  "Mechanical Level Crossing Gate"),
    "41": ("ELC",  "Electrical Level Crossing Gate"),
    "50": ("IPS",  "Integrated Power Supply"),
    "51": ("SPD",  "SPD"),
    "60": ("ELD",  "Earth Leakage Detector"),
}

# Equipment Room Type table — Annexure A §3(j). eqpmntroom_type_id occupies the
# SAME byte position as asset_type_id in para_id, for parameters that belong to
# a room (temperature/humidity/relay-room-open-close) rather than a signalling
# asset. Previously missing entirely, which meant every Relay/IPS/Battery/
# Maintainer/Generator Room + Outdoor + Location Box reading resolved to
# asset_type_name=None / asset_type_code=None everywhere (decode.py, alerts.py,
# assets.py, maintenance.py, telemetry.py all call ASSET_TYPE_MAP.get(...)).
EQUIPMENT_ROOM_TYPE_MAP = {
    "F0": ("RR",      "Relay Room"),
    "F1": ("IPSR",     "IPS Room"),
    "F2": ("BATT",    "Battery Room"),
    "F3": ("MAIN",    "Maintainer Room"),
    "F4": ("GEN",     "Generator Room"),
    "F5": ("OUTDOOR", "Outdoor"),
    "F6": ("LOC",     "Location Box"),
}

# Merge so every existing ASSET_TYPE_MAP.get(asset_type_hex) call site
# (decode.py, alerts.py, assets.py, maintenance.py, telemetry.py) resolves
# equipment-room parameters correctly without needing to touch each file.
ASSET_TYPE_MAP.update(EQUIPMENT_ROOM_TYPE_MAP)

# Dashboard display groups — maps friendly label to asset_type_hex values
# Used for the "Asset Type" dropdown in the UI
ASSET_TYPE_DISPLAY_GROUPS = {
    "Point Machine":    ["00"],
    "DC Track Circuit": ["20"],
    "AC Track Circuit": ["2D", "2E", "2F"],
    "Main Signal":      ["10", "11", "12", "13"],
    "Axle Counter":     ["21", "22", "23", "24", "25", "26", "27", "28", "29", "2A", "2B", "2C"],
    "LC Gate":          ["40", "41"],
    "BPAC":             ["30", "31"],
    "IPS":              ["50", "51"],
    "Battery":          ["60"],
    "Relay Room":       ["F0"],
    "IPS Room":         ["F1"],
    "Battery Room":     ["F2"],
    "Maintainer Room":  ["F3"],
    "Generator Room":   ["F4"],
    "Outdoor":          ["F5"],
    "Location Box":     ["F6"],
}


# ═══════════════════════════════════════════════════════════════════════════
# NOTE ON parameter_type_id vs parameter_representation_id (Annexure A §3(l)/(m))
#
# Per spec, byte 3 of para_id (parameter_type_id) is a GENERIC measurement-type
# code shared by every asset (Current DC=00, Voltage DC=20, Digital=40,
# Temperature=50, Vibration=60, ... — see GENERIC_PARAMETER_TYPE_MAP below).
# Byte 4 (parameter_representation_id) is what actually varies per asset and
# carries the specific parameter's identity (e.g. IPS repr 0x00 = "IPS 110 DC
# O/P Voltage"; DC Track Circuit repr 0x00 means something else entirely).
#
# ASSET_PARAMETER_CATALOG below (previously misnamed PARAMETER_TYPE_MAP) is
# kept ONLY as a flat, best-effort, asset-agnostic lookup for quick decode/
# display convenience — it is NOT spec-compliant, because representation_id
# is asset-type-scoped, not global (two different assets can legitimately
# reuse the same representation byte for different parameters). Do not use
# this table to drive alert logic. For anything logic/alert-related, resolve
# the full 4-byte para_id through
# app.services.parameter_config_service.param_config_service, which is keyed
# correctly by (asset_type_id, asset_number_id, parameter_type_id,
# parameter_representation_id) together.
# ═══════════════════════════════════════════════════════════════════════════

# Generic parameter_type_id map — Annexure A §3(l). Same meaning for every asset.
GENERIC_PARAMETER_TYPE_MAP = {
    "00": ("CUR_DC_A",  "Current DC", "A"),
    "01": ("CUR_DC_MA", "Current DC", "mA"),
    "10": ("CUR_AC_A",  "Current AC", "A"),
    "11": ("CUR_AC_MA", "Current AC", "mA"),
    "20": ("VOLT_DC_V", "Voltage DC", "V"),
    "21": ("VOLT_DC_MV","Voltage DC", "mV"),
    "30": ("VOLT_AC_V", "Voltage AC", "V"),
    "31": ("VOLT_AC_MV","Voltage AC", "mV"),
    "40": ("DIGITAL",   "Digital",    ""),
    "50": ("TEMP_C",    "Temperature","°C"),
    "51": ("HUMIDITY",  "Humidity",   "%"),
    "60": ("VIBRATION", "Vibration",  ""),
    "70": ("FREQ_KHZ",  "Frequency",  "kHz"),
    "71": ("FREQ_HZ",   "Frequency",  "Hz"),
    "80": ("RES_OHM",   "Resistance", "Ohm"),
    "81": ("RES_KOHM",  "Resistance", "KOhm"),
    "90": ("TIME_S",    "Time",       "seconds"),
    "91": ("TIME_MS",   "Time",       "milliseconds"),
    "A0": ("STRING",    "String",     ""),
}

# Asset-specific parameter catalogue — NOT the spec's parameter_type_id.
# (kept under its old name PARAMETER_TYPE_MAP as an alias below for
# backwards compatibility with existing imports; new code should prefer
# ASSET_PARAMETER_CATALOG / GENERIC_PARAMETER_TYPE_MAP / param_config_service.)
ASSET_PARAMETER_CATALOG = {
    # ── Point Machine (asset 00) ──────────────────────────────────────────────
    "01": ("AVG_CUR",   "Avg Current",          "A"),
    "02": ("PEAK_CUR",  "Peak Current",          "A"),
    "03": ("STK_TIME",  "Stroke Time",           "ms"),
    "04": ("BAT_VOLT",  "Battery Voltage",       "V"),
    "05": ("MOT_TEMP",  "Motor Temperature",     "°C"),
    "06": ("PWR_CONS",  "Power Consumption",     "W"),
    "07": ("OPER_CNT",  "Operation Count",       "count"),
    "08": ("DETECT_F",  "Detection Failure",     "bool"),
    "09": ("LOCK_F",    "Locking Failure",       "bool"),

    # ── Track Circuit ─────────────────────────────────────────────────────────
    "0A": ("TC_VOLT",   "Track Circuit Voltage", "V"),
    "0B": ("TC_CURR",   "Track Circuit Current", "A"),
    "0C": ("RELAY_V",   "Relay Voltage",         "V"),
    "0D": ("BALLAST_R", "Ballast Resistance",    "Ω"),
    "0E": ("SHUNT_R",   "Shunt Resistance",      "Ω"),

    # ── Axle Counter ─────────────────────────────────────────────────────────
    "10": ("AXL_CNT",   "Axle Count",            "count"),
    "11": ("HEAD_V",    "Head Voltage",           "V"),
    "12": ("HEAD_C",    "Head Current",           "A"),
    "13": ("EVAL_V",    "Evaluator Voltage",      "V"),
    "14": ("RESET_CNT", "Reset Count",            "count"),

    # ── Signal / LED ──────────────────────────────────────────────────────────
    "20": ("LED_CUR",   "LED Current",            "mA"),
    "21": ("LED_VOLT",  "LED Voltage",            "V"),
    "22": ("LUX",       "Luminous Intensity",     "cd"),
    "23": ("LAMP_HRS",  "Lamp Hours",             "h"),

    # ── LC Gate ───────────────────────────────────────────────────────────────
    "30": ("GATE_POS",  "Gate Position",          "deg"),
    "31": ("GATE_SPD",  "Gate Speed",             "rpm"),
    "32": ("GATE_TRQ",  "Gate Torque",            "Nm"),
    "33": ("GATE_CNT",  "Gate Operation Count",   "count"),

    # ── IPS / Power ───────────────────────────────────────────────────────────
    "40": ("INP_VOLT",  "Input Voltage",          "V"),
    "41": ("OUT_VOLT",  "Output Voltage",         "V"),
    "42": ("INP_CUR",   "Input Current",          "A"),
    "43": ("OUT_CUR",   "Output Current",         "A"),
    "44": ("BAT_SOC",   "Battery SOC",            "%"),
    "45": ("BAT_TEMP",  "Battery Temperature",    "°C"),
    "46": ("CHG_CURR",  "Charging Current",       "A"),
    "47": ("MAINS_F",   "Mains Frequency",        "Hz"),

    # ── Earth Leakage ─────────────────────────────────────────────────────────
    "50": ("EL_RES",    "Earth Leakage Resistance", "kΩ"),
    "51": ("EL_CURR",   "Earth Leakage Current",    "mA"),

    # ── Generic / Environmental ───────────────────────────────────────────────
    "F0": ("TEMP",      "Temperature",            "°C"),
    "F1": ("HUMIDITY",  "Humidity",               "%"),
    "F2": ("VIBRATION", "Vibration",              "g"),
    "FF": ("RAW",       "Raw Value",              ""),
}

# Backwards-compat alias — existing imports of PARAMETER_TYPE_MAP keep working.
# See the note above: this is really the asset-specific catalogue, not the
# spec's generic parameter_type_id map (that's GENERIC_PARAMETER_TYPE_MAP).
PARAMETER_TYPE_MAP = ASSET_PARAMETER_CATALOG

# Parameter representation lookup
# Byte 8 of para_id — how the value is encoded / aggregated
PARAMETER_REPR_MAP = {
    "00": ("INSTANT",  "Instantaneous"),
    "01": ("AVG",      "Average"),
    "02": ("MAX",      "Maximum"),
    "03": ("MIN",      "Minimum"),
    "04": ("RMS",      "RMS"),
    "05": ("BOOL",     "Boolean / Status"),
    "06": ("COUNTER",  "Counter"),
    "FF": ("RAW",      "Raw"),
}
