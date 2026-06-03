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
}

# Parameter type lookup from RDSO/SPN/257/2025 Annexure B
# Maps parameter_type_id hex → (param_code, param_name, unit)
# Bytes 5–6 of para_id
PARAMETER_TYPE_MAP = {
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
