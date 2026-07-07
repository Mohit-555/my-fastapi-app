# app/models/database_models.py
from datetime import datetime, date
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field
from enum import Enum

class AlertType(str, Enum):
    FAILURE = "Failure"
    PREDICTIVE = "Predictive"

class AlertStatus(str, Enum):
    PENDING = "pending"
    CLEARED = "cleared"

class FeedbackType(str, Enum):
    TRUE = "T"
    PARTIALLY_TRUE = "PT"
    FALSE = "F"
    MAINTENANCE = "M"

class ParameterHistory(BaseModel):
    """Model for storing parameter history in TimescaleDB"""
    id: Optional[int] = None
    stngw_id: str
    para_id: str
    value: float
    timestamp: datetime
    
    class Config:
        from_attributes = True

class LatestParameter(BaseModel):
    """Model for storing latest parameter value in Redis"""
    stngw_id: str
    para_id: str
    value: float
    timestamp: datetime

class Asset(BaseModel):
    """Asset model with parameter mapping"""
    smms_asset_code: str
    smms_asset_name: str
    asset_number_id: str  # One byte hex
    asset_number_code: str
    asset_type_id: str  # One byte hex
    asset_type_code: str
    station_id: str
    make: Optional[str] = None
    model: Optional[str] = None
    prloc: Optional[str] = None
    para_ids: Optional[List[str]] = []

class Alert(BaseModel):
    """Alert model"""
    id: Optional[int] = None
    stngw_id: str
    asset_number_code: str
    alert_type: AlertType
    cause_code: str
    cause_detail: str
    incidence_date_time: datetime
    status: AlertStatus = AlertStatus.PENDING
    feedback: Optional[FeedbackType] = None
    feedback_date_time: Optional[datetime] = None
    rectification_date_time: Optional[datetime] = None
    remarks: Optional[str] = None
    maintainer_name: Optional[str] = None
    maintainer_mobile: Optional[str] = None

class GatewayHealth(BaseModel):
    """Gateway health model"""
    stngw_id: str
    status: bool  # True = Healthy, False = Faulty
    last_heartbeat: datetime
    version: str

class SensorHealth(BaseModel):
    """Sensor health model"""
    stngw_id: str
    para_id: str
    status: bool  # True = Healthy, False = Faulty
    timestamp: datetime

class IoTHealth(BaseModel):
    """IoT device health model"""
    stngw_id: str
    imei: str
    status: bool  # True = Healthy, False = Faulty
    timestamp: datetime

class NetworkHealth(BaseModel):
    """Network health model"""
    stngw_id: str
    network_id: str
    description: str
    status: bool  # True = Healthy, False = Faulty
    timestamp: datetime

# ============ Parameter Configuration ============

class ParameterConfig(BaseModel):
    """Configuration for each parameter type"""
    para_id: str
    parameter_type_id: str  # One byte hex
    parameter_representation_id: str  # One byte hex
    parameter_representation_code: str
    parameter_representation_name: str
    asset_type_id: str
    unit: Optional[str] = None
    standard_value: Optional[float] = None
    min_safe: Optional[float] = None
    max_safe: Optional[float] = None
    min_fail: Optional[float] = None
    max_fail: Optional[float] = None
    sampling_interval_ms: Optional[int] = None
    is_event_based: bool = False
    is_digital: bool = False

# ============ Station Gateway ============

class StationGateway(BaseModel):
    stngw_id: str
    zone_id: str
    division_id: str
    station_id: str
    vcc: str  # Vendor code
    vgc: str  # Gateway vendor code
    version: str
    last_seen: datetime
    is_active: bool = True

# ============ Daily Statistics ============

class DailyStats(BaseModel):
    """Daily statistics for performance calculations"""
    date: date
    stngw_id: str
    asset_number_code: str
    alert_type: AlertType
    total_alerts: int = 0
    true_alerts: int = 0
    partially_true_alerts: int = 0
    false_alerts: int = 0
    maintenance_alerts: int = 0
    
    @property
    def success_rate(self) -> float:
        """Calculate (True + Partially True) / Total"""
        if self.total_alerts == 0:
            return 0.0
        return (self.true_alerts + self.partially_true_alerts) / self.total_alerts * 100
