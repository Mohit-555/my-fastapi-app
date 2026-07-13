import json
import logging
from typing import Optional, Dict, List, Any
from app.services.redis_service import redis_service
from app.services.database_service import db_service
from app.models.database_models import ParameterConfig

logger = logging.getLogger("parameter_config")

class ParameterConfigService:
    """Service for managing parameter configurations"""
    
    def __init__(self):
        self.config_cache = {}  # In-memory cache
        self._load_default_config()
    
    def _load_default_config(self):
        """Load default parameter configurations from Annexure A"""
        self._load_point_machine_config()

        self._load_track_circuit_config()

        self._load_main_signal_config()

        # ── Relay Room Parameters (eqpmntroom_type_id=F0, used as asset_type_id) ──
        self.register_parameter({
            "asset_type_id": "F0", "asset_number_id": "01",
            "parameter_type_id": "50",  # Temperature
            "parameter_representation_id": "01",
            "parameter_representation_code": "TEMPRR",
            "parameter_representation_name": "Relay Room Temperature",
            "unit": "°C",
            "min_safe": 15, "max_safe": 40, "min_fail": 5, "max_fail": 50
        })

        self.register_parameter({
            "asset_type_id": "F0", "asset_number_id": "01",
            "parameter_type_id": "51",  # Humidity
            "parameter_representation_id": "02",
            "parameter_representation_code": "HUMDRR",
            "parameter_representation_name": "Relay Room Humidity",
            "unit": "%",
            "min_safe": 30, "max_safe": 70, "min_fail": 10, "max_fail": 90
        })

        self._load_ips_config()

    def _load_main_signal_config(self):
        """
        Main Signal parameters — Annexure A §3(n), "Nomenclature of
        Parameters of Main Signal" (18 rows). asset_type_id is always "10".

        Voltage/current codes (VSIG DG/HG/HHG/RG, ISIG DG/HG/HHG/RG) match
        the substring checks in app/services/logics/signal.py exactly.
        """
        # (repr_id, type_id, code, name, unit, min_safe, max_safe, min_fail)
        sig_params = [
            ("00", "40", "HECR",       "Digital status of HECR (Yellow lit)",       None, None, None, None),
            ("01", "40", "RECR",       "Digital status of RECR (Red lit)",          None, None, None, None),
            ("02", "40", "DECR",       "Digital status of DECR (Green lit)",        None, None, None, None),
            ("03", "40", "HHECR",      "Digital status of HHECR (Double Yellow lit)", None, None, None, None),
            ("10", "40", "DR",         "Digital status of DR (Green feed extended)", None, None, None, None),
            ("11", "40", "HR",         "Digital status of HR (Yellow feed extended)", None, None, None, None),
            ("12", "40", "HHR",        "Digital status of HHR (Double Yellow feed extended)", None, None, None, None),
            ("20", "20", "VSIG DPR",   "DPR Voltage",                 "V", 18, 21, None),
            ("21", "20", "VSIG HPR",   "HPR Voltage",                 "V", 18, 21, None),
            ("22", "20", "VSIG HHPR",  "HHPR Voltage",                "V", 18, 21, None),
            ("30", "30", "VSIG DG",    "Green Aspect Voltage",        "V", 82, 90, None),
            ("31", "30", "VSIG HG",    "Yellow Aspect Voltage",       "V", 82, 90, None),
            ("32", "30", "VSIG HHG",   "Double Yellow Aspect Voltage","V", 82, 90, None),
            ("33", "30", "VSIG RG",    "Red Aspect Voltage",          "V", 82, 90, None),
            ("40", "11", "ISIG DG",    "Green Aspect Current",        "mA", 110, 150, 90),
            ("41", "11", "ISIG HG",    "Yellow Aspect Current",       "mA", 110, 150, 90),
            ("42", "11", "ISIG HHG",   "Double Yellow Aspect Current","mA", 110, 150, 90),
            ("43", "11", "ISIG RG",    "Red Aspect Current",          "mA", 110, 150, 90),
        ]
        for repr_id, type_id, code, name, unit, min_safe, max_safe, min_fail in sig_params:
            self.register_parameter({
                "asset_type_id": "10", "asset_number_id": "01",
                "parameter_type_id": type_id,
                "parameter_representation_id": repr_id,
                "parameter_representation_code": code,
                "parameter_representation_name": name,
                "unit": unit,
                "min_safe": min_safe, "max_safe": max_safe, "min_fail": min_fail,
            })

    def _load_point_machine_config(self):
        """
        Point Machine parameters — Annexure A §3(n), "Nomenclature of
        Parameter of Point Machine" (15 rows). asset_type_id is always "00".

        Rows 14-15 (TPT N / TPT R, derived operation time) drive the
        obstruction-detection cause codes PT_N_OBS/PT_R_OBS in
        app/services/logics/point_machine.py — without these registered,
        that logic can never fire.

        min_safe/min_fail marked "*" or "__" in spec are left None/omitted
        here — configure per site (operation-time max-safe in particular
        should be ~1.5s less than the WJR timer time, per the spec's own
        note, not a generic default).
        """
        # (repr_id, type_id, code, name, unit, min_safe, max_safe, min_fail)
        pm_params = [
            ("00", "20", "VPT NWKR N",       "24VDC at RR from Loc — NWKR Normal",        "V", 18, 21, None),
            ("01", "20", "VPT RWKR R",       "24VDC at RR from Loc — RWKR Reverse",       "V", 18, 21, None),
            ("10", "40", "NWKR",             "Digital status of NWKR",                     None, None, None, None),
            ("11", "40", "RWKR",             "Digital status of RWKR",                     None, None, None, None),
            ("12", "40", "NWCR",             "Digital status of NWCR",                     None, None, None, None),
            ("13", "40", "RWCR",             "Digital status of RWCR",                     None, None, None, None),
            ("20", "20", "VPT 110 DC LOC N", "110 DC at Loc box for Normal",               "V", 82, 90, None),
            ("21", "20", "VPT110 DC LOC R",  "110 DC at Loc box for Reverse",              "V", 82, 90, None),
            ("30", "00", "IPT N",            "Point Machine Current Normal",               "A", None, None, None),
            ("31", "00", "IPT R",            "Point Machine Current Reverse",              "A", None, None, None),
            ("40", "20", "VPT 24 DC LOC N",  "24V DC to Relay Room after detection — Normal", "V", None, None, None),
            ("41", "20", "VPT 24 DC LOC R",  "24V DC to Relay Room after detection — Reverse", "V", None, None, None),
            ("50", "60", "XPT",              "Vibration (Optional)",                       None, None, None, None),
            ("60", "90", "TPT N",            "Normal Operation Time (derived, obstruction check)", "sec", None, None, 8),
            ("61", "90", "TPT R",            "Reverse Operation Time (derived, obstruction check)", "sec", None, None, 8),
        ]
        for repr_id, type_id, code, name, unit, min_safe, max_safe, min_fail in pm_params:
            self.register_parameter({
                "asset_type_id": "00", "asset_number_id": "01",
                "parameter_type_id": type_id,
                "parameter_representation_id": repr_id,
                "parameter_representation_code": code,
                "parameter_representation_name": name,
                "unit": unit,
                "min_safe": min_safe, "max_safe": max_safe, "min_fail": min_fail,
                "sampling_interval_ms": 20, "is_event_based": True,
            })

    def _load_track_circuit_config(self):
        """
        DC Track Circuit parameters — Annexure A §3(n), "Nomenclature of
        Parameters of DC Track Circuit" (17 rows). asset_type_id is always "20".

        Codes match the cause_map in app/services/logics/track_circuit.py
        exactly (VTC TFC IP, VTC TFC O/P, ITC BATT CHARG, VTC TR,
        RTC CH FEED END, ITC RELAY END) so that logic engine actually fires.
        """
        # (repr_id, type_id, code, name, unit, min_safe, max_safe, min_fail)
        tc_params = [
            ("00", "20", "VTC 24 DC TPR IP",  "24V DC TPR Input at Relay Room",     "V", 18, 21, None),
            ("10", "40", "TPR",               "Digital status of TPR (Repeater Relay)", None, None, None, None),
            ("20", "30", "VTC TFC IP",        "Track Feed Charger Input Voltage",   "V", None, None, None),
            ("21", "20", "VTC TFC O/P",       "Track Feed Charger Output Voltage (on load)", "V", None, None, None),
            ("22", "01", "ITC TFC O/P",       "Track Feed Charger Output Current",  "mA", None, None, None),
            ("23", "20", "VTC CH FEED END",   "Voltage drop at feed end choke",     "V", None, None, None),
            ("24", "20", "VTC FEED END",      "Track Feed end voltage (going to Rails)", "V", None, None, None),
            ("25", "01", "ITC FEED END",      "Track Feed Current",                 "mA", None, None, None),
            ("26", "01", "ITC BATT CHARG",    "Battery Charging Current (derived)", "mA", None, None, None),
            ("27", "20", "VTC VAR RES",       "Voltage at Variable Track Resistance (derived)", "V", None, None, None),
            ("28", "80", "RTC CH FEED END",   "Feed end choke resistance (derived)", "Ohm", None, None, None),
            ("29", "80", "RTC VAR RES",       "Variable resistance (derived)",      "Ohm", None, None, None),
            ("41", "01", "ITC RELAY END",     "Track Relay end Current",            "mA", 100, 210, None),
            ("42", "20", "VTC TR",            "Track Relay Voltage (derived, QTA2 ref 1.4V)", "V", 2.1, 4.2, None),
            ("44", "20", "VTC 24 DC LOC",     "24V DC to TPR after TR pick-up contact", "V", None, None, None),
            ("60", "01", "IBALST",            "Ballast/Sleeper Current (derived)",   "mA", None, None, None),
            ("61", "80", "RRAIL",             "Rail Resistance (derived)",           "Ohm", None, None, None),
        ]
        for repr_id, type_id, code, name, unit, min_safe, max_safe, min_fail in tc_params:
            self.register_parameter({
                "asset_type_id": "20", "asset_number_id": "01",
                "parameter_type_id": type_id,
                "parameter_representation_id": repr_id,
                "parameter_representation_code": code,
                "parameter_representation_name": name,
                "unit": unit,
                "min_safe": min_safe, "max_safe": max_safe, "min_fail": min_fail,
            })

    def _load_ips_config(self):
        """
        Integrated Power Supply parameters — Annexure A (Nomenclature of Parameters
        of IPS) x Annexure C §2.1 (a)/(b) (min_safe/min_fail thresholds).

        Every value the spec marks with "*" is left to Zonal Railway/site
        commissioning; we default those to None here (meaning: not yet
        configured) rather than inventing a number. Set real min_safe/min_fail
        per site via the parameter-config admin API/DB before relying on
        predictive/failure alerts for that parameter.

        Representation codes are prefixed V/I to match the cause_map keys
        already used in app/services/logics/ips.py.
        """
        # (repr_id, type_id, spec_code, unit) — asset_type_id is always "50" (IPS)
        ips_params = [
            ("00", "20", "IPS 110 DC",           "V"),  # 1
            ("10", "30", "IPS SIG-1 110 AC",      "V"),  # 2
            ("11", "30", "IPS SIG-2 110 AC",      "V"),  # 3
            ("12", "30", "IPS SIG-3 110 AC",      "V"),  # 4
            ("13", "30", "IPS SIG-4 110 AC",      "V"),  # 5
            ("20", "30", "IPS TR-1 110 AC",       "V"),  # 6
            ("21", "30", "IPS TR-2 110 AC",       "V"),  # 7
            ("22", "30", "IPS TR-3 110 AC",       "V"),  # 8
            ("23", "30", "IPS TR-4 110 AC",       "V"),  # 9
            ("30", "20", "IPS SMR-1 110 DC",      "V"),  # 10
            ("31", "20", "IPS SMR-2 110 DC",      "V"),  # 11
            ("32", "20", "IPS SMR-3 110 DC",      "V"),  # 12
            ("34", "20", "IPS SMR-4 110 DC",      "V"),  # 13
            ("35", "20", "IPS SMR-5 110 DC",      "V"),  # 14
            ("40", "20", "IPS DC R INT",          "V"),  # 15
            ("48", "20", "IPS DC R EXT",          "V"),  # 16
            ("50", "20", "IPS DC AXLE C",         "V"),  # 17
            ("58", "20", "IPS DC PAN IND",        "V"),  # 18
            ("5C", "20", "IPS DC BLOCK LOCAL",    "V"),  # 19
            ("60", "20", "IPS DC HKT MAG",        "V"),  # 20
            ("62", "20", "IPS DC BLOCK LINE UP",  "V"),  # 21
            ("63", "20", "IPS DC BLOCK LINE DN",  "V"),  # 22
            ("65", "20", "IPS DC BLOCK TEL UP",   "V"),  # 23
            ("66", "20", "IPS DC BLOCK TEL DN",   "V"),  # 24
            ("68", "20", "IPS DC DATALOG",        "V"),  # 25
            ("70", "20", "IPS DC EI",             "V"),  # 26
            ("78", "00", "IPS BATT CHAR 110 DC",  "I"),  # 27 (current, bidirectional)
            ("79", "30", "IPS IIP",               "V"),  # 28 (220 AC input to IPS)
        ]
        for repr_id, type_id, spec_code, kind in ips_params:
            self.register_parameter({
                "asset_type_id": "50", "asset_number_id": "01",
                "parameter_type_id": type_id,
                "parameter_representation_id": repr_id,
                "parameter_representation_code": f"{kind}{spec_code}",
                "parameter_representation_name": spec_code,
                "unit": "A" if kind == "I" else "V",
                # Thresholds intentionally None ("*" in spec) — configure per site.
                "min_safe": None, "max_safe": None, "min_fail": None, "max_fail": None,
            })
    
    def register_parameter(self, config: Dict[str, Any]):
        """
        Register a parameter configuration.

        para_id is ALWAYS derived from its four constituent hex bytes
        (Annexure A §3): asset_type_id + asset_number_id + parameter_type_id +
        parameter_representation_id. Any "para_id" passed in explicitly is
        ignored/overwritten, to prevent drift from non-hex placeholder ids
        (e.g. "DCT00201", "SIG00301") that broke the standard encoding.
        """
        required = ("asset_type_id", "asset_number_id", "parameter_type_id", "parameter_representation_id")
        missing = [f for f in required if f not in config or config[f] is None]
        if missing:
            logger.error(f"Parameter config missing required id byte(s) {missing}: {config}")
            return

        for f in required:
            v = config[f]
            if not (isinstance(v, str) and len(v) == 2):
                logger.error(f"{f}={v!r} must be a 2-char hex string (one byte)")
                return
            try:
                int(v, 16)
            except ValueError:
                logger.error(f"{f}={v!r} is not valid hexadecimal")
                return

        para_id = (
            config["asset_type_id"]
            + config["asset_number_id"]
            + config["parameter_type_id"]
            + config["parameter_representation_id"]
        ).upper()
        config["para_id"] = para_id

        self.config_cache[para_id] = ParameterConfig(**config)
        logger.debug(f"Registered parameter config: {para_id}")
    
    def get_parameter_config(self, para_id: str) -> Optional[ParameterConfig]:
        """Get parameter configuration by para_id"""
        return self.config_cache.get(para_id)
    
    def get_parameters_by_asset_type(self, asset_type_id: str) -> List[ParameterConfig]:
        """Get all parameters for an asset type"""
        return [
            config for config in self.config_cache.values()
            if config.asset_type_id == asset_type_id
        ]
    
    def get_event_based_parameters(self) -> List[ParameterConfig]:
        """Get all event-based parameters"""
        return [
            config for config in self.config_cache.values()
            if config.is_event_based
        ]
    
    def calculate_average_value(
        self, 
        para_id: str, 
        values: List[float], 
        exclude_outliers: bool = True
    ) -> float:
        """Calculate average value for a parameter with optional outlier removal"""
        if not values:
            return 0.0
        
        config = self.get_parameter_config(para_id)
        if not config:
            return sum(values) / len(values)
        
        filtered_values = values
        
        if exclude_outliers:
            # Remove values outside min_safe/max_safe (failure values)
            if config.min_safe is not None:
                filtered_values = [v for v in filtered_values if v >= config.min_safe]
            if config.max_safe is not None:
                filtered_values = [v for v in filtered_values if v <= config.max_safe]
        
        if not filtered_values:
            return sum(values) / len(values) if values else 0.0
        
        return sum(filtered_values) / len(filtered_values)
    
    def check_parameter_health(
        self, 
        para_id: str, 
        value: float
    ) -> Dict[str, Any]:
        """Check if a parameter value is healthy, warning, or failure"""
        config = self.get_parameter_config(para_id)
        if not config:
            return {"status": "unknown", "message": "No configuration found"}
        
        result = {
            "status": "healthy",
            "message": "Parameter within safe range",
            "value": value
        }
        
        # Check failure conditions
        if config.min_fail is not None and value < config.min_fail:
            result["status"] = "failure"
            result["message"] = f"Value {value} below minimum fail threshold {config.min_fail}"
        elif config.max_fail is not None and value > config.max_fail:
            result["status"] = "failure"
            result["message"] = f"Value {value} above maximum fail threshold {config.max_fail}"
        
        # Check warning conditions (predictive)
        elif config.min_safe is not None and value < config.min_safe:
            result["status"] = "warning"
            result["message"] = f"Value {value} below minimum safe threshold {config.min_safe}"
        elif config.max_safe is not None and value > config.max_safe:
            result["status"] = "warning"
            result["message"] = f"Value {value} above maximum safe threshold {config.max_safe}"
        
        return result

# Singleton instance
param_config_service = ParameterConfigService()
