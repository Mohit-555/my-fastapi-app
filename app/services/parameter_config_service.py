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
        # ── Point Machine Parameters (Annexure A, asset_type_id=00) ──────────
        self.register_parameter({
            "asset_type_id": "00", "asset_number_id": "01",
            "parameter_type_id": "00",  # DC Current
            "parameter_representation_id": "0C",
            "parameter_representation_code": "IPT N",
            "parameter_representation_name": "Point Machine Current Normal",
            "unit": "A", "standard_value": 1.5,
            "min_safe": 0.8, "max_safe": 2.5, "min_fail": 0.3,
            "sampling_interval_ms": 20, "is_event_based": True
        })

        self.register_parameter({
            "asset_type_id": "00", "asset_number_id": "01",
            "parameter_type_id": "00",
            "parameter_representation_id": "0D",
            "parameter_representation_code": "IPT R",
            "parameter_representation_name": "Point Machine Current Reverse",
            "unit": "A", "standard_value": 1.5,
            "min_safe": 0.8, "max_safe": 2.5, "min_fail": 0.3,
            "sampling_interval_ms": 20, "is_event_based": True
        })

        self.register_parameter({
            "asset_type_id": "00", "asset_number_id": "01",
            "parameter_type_id": "20",  # DC Voltage
            "parameter_representation_id": "0A",
            "parameter_representation_code": "VPT 110 DC LOC N",
            "parameter_representation_name": "110 DC at Loc box for Normal",
            "unit": "V", "standard_value": 110,
            "min_safe": 90, "max_safe": 120, "min_fail": 80,
            "sampling_interval_ms": 20, "is_event_based": True
        })

        # ── DC Track Circuit Parameters (asset_type_id=20) ───────────────────
        self.register_parameter({
            "asset_type_id": "20", "asset_number_id": "01",
            "parameter_type_id": "20",
            "parameter_representation_id": "01",
            "parameter_representation_code": "VTC TFC IP",
            "parameter_representation_name": "Track Feed Charger Input Voltage",
            "unit": "V", "standard_value": 110,
            "min_safe": 90, "max_safe": 120, "min_fail": 80
        })

        self.register_parameter({
            "asset_type_id": "20", "asset_number_id": "01",
            "parameter_type_id": "20",
            "parameter_representation_id": "02",
            "parameter_representation_code": "VTC TFC O/P",
            "parameter_representation_name": "Track Feed Charger Output Voltage",
            "unit": "V", "standard_value": 10,
            "min_safe": 8, "max_safe": 12, "min_fail": 6
        })

        # ── Main Signal Parameters (asset_type_id=10) ────────────────────────
        self.register_parameter({
            "asset_type_id": "10", "asset_number_id": "01",
            "parameter_type_id": "30",  # AC Voltage
            "parameter_representation_id": "01",
            "parameter_representation_code": "VSIG DG",
            "parameter_representation_name": "Green Aspect Voltage",
            "unit": "V", "standard_value": 110,
            "min_safe": 90, "max_safe": 120, "min_fail": 80
        })

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
