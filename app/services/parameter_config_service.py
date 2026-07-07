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
        # Point Machine Parameters
        self.register_parameter({
            "para_id": "0001000C",
            "parameter_type_id": "00",  # DC Current
            "parameter_representation_id": "0C",
            "parameter_representation_code": "IPT N",
            "parameter_representation_name": "Point Machine Current Normal",
            "asset_type_id": "00",  # Point Machine
            "unit": "A",
            "standard_value": 1.5,
            "min_safe": 0.8,
            "max_safe": 2.5,
            "min_fail": 0.3,
            "sampling_interval_ms": 20,
            "is_event_based": True
        })
        
        self.register_parameter({
            "para_id": "0001000D",
            "parameter_type_id": "00",
            "parameter_representation_id": "0D",
            "parameter_representation_code": "IPT R",
            "parameter_representation_name": "Point Machine Current Reverse",
            "asset_type_id": "00",
            "unit": "A",
            "standard_value": 1.5,
            "min_safe": 0.8,
            "max_safe": 2.5,
            "min_fail": 0.3,
            "sampling_interval_ms": 20,
            "is_event_based": True
        })
        
        self.register_parameter({
            "para_id": "0001120A",
            "parameter_type_id": "20",  # DC Voltage
            "parameter_representation_id": "0A",
            "parameter_representation_code": "VPT 110 DC LOC N",
            "parameter_representation_name": "110 DC at Loc box for Normal",
            "asset_type_id": "00",
            "unit": "V",
            "standard_value": 110,
            "min_safe": 90,
            "max_safe": 120,
            "min_fail": 80,
            "sampling_interval_ms": 20,
            "is_event_based": True
        })
        
        # Track Circuit Parameters
        self.register_parameter({
            "para_id": "DCT00201",
            "parameter_type_id": "20",
            "parameter_representation_id": "01",
            "parameter_representation_code": "VTC TFC IP",
            "parameter_representation_name": "Track Feed Charger Input Voltage",
            "asset_type_id": "20",  # DC Track Circuit
            "unit": "V",
            "standard_value": 110,
            "min_safe": 90,
            "max_safe": 120,
            "min_fail": 80
        })
        
        self.register_parameter({
            "para_id": "DCT00202",
            "parameter_type_id": "20",
            "parameter_representation_id": "02",
            "parameter_representation_code": "VTC TFC O/P",
            "parameter_representation_name": "Track Feed Charger Output Voltage",
            "asset_type_id": "20",
            "unit": "V",
            "standard_value": 10,
            "min_safe": 8,
            "max_safe": 12,
            "min_fail": 6
        })
        
        # Signal Parameters
        self.register_parameter({
            "para_id": "SIG00301",
            "parameter_type_id": "30",  # AC Voltage
            "parameter_representation_id": "01",
            "parameter_representation_code": "VSIG DG",
            "parameter_representation_name": "Green Aspect Voltage",
            "asset_type_id": "10",  # Main Signal
            "unit": "V",
            "standard_value": 110,
            "min_safe": 90,
            "max_safe": 120,
            "min_fail": 80
        })
        
        # Temperature Parameters
        self.register_parameter({
            "para_id": "RR000101",
            "parameter_type_id": "50",  # Temperature
            "parameter_representation_id": "01",
            "parameter_representation_code": "TEMPRR",
            "parameter_representation_name": "Relay Room Temperature",
            "asset_type_id": "F0",  # Relay Room
            "unit": "°C",
            "min_safe": 15,
            "max_safe": 40,
            "min_fail": 5,
            "max_fail": 50
        })
        
        # Humidity Parameters
        self.register_parameter({
            "para_id": "RR000102",
            "parameter_type_id": "51",  # Humidity
            "parameter_representation_id": "02",
            "parameter_representation_code": "HUMDRR",
            "parameter_representation_name": "Relay Room Humidity",
            "asset_type_id": "F0",
            "unit": "%",
            "min_safe": 30,
            "max_safe": 70,
            "min_fail": 10,
            "max_fail": 90
        })
    
    def register_parameter(self, config: Dict[str, Any]):
        """Register a parameter configuration"""
        para_id = config.get("para_id")
        if not para_id:
            logger.error("Parameter config missing para_id")
            return
        
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
