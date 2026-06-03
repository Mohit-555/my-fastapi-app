from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime


# ─── Zone ─────────────────────────────────────────────────────────────────────

class ZoneBase(BaseModel):
    zone_name: str
    zone_code: str
    zone_id_hex: str

class ZoneCreate(ZoneBase):
    pass

class ZoneUpdate(BaseModel):
    zone_name: Optional[str] = None
    zone_code: Optional[str] = None
    zone_id_hex: Optional[str] = None

class ZoneResponse(ZoneBase):
    id: int
    class Config:
        from_attributes = True

class ZoneWithDivisions(ZoneResponse):
    divisions: List["DivisionResponse"] = []


# ─── Division ─────────────────────────────────────────────────────────────────

class DivisionBase(BaseModel):
    division_name: str
    division_code: str
    division_id_hex: str
    zone_id: int

class DivisionCreate(DivisionBase):
    pass

class DivisionUpdate(BaseModel):
    division_name: Optional[str] = None
    division_code: Optional[str] = None
    division_id_hex: Optional[str] = None
    zone_id: Optional[int] = None

class DivisionResponse(BaseModel):
    id: int
    division_name: str
    division_code: str
    division_id_hex: str
    zone_id: int
    class Config:
        from_attributes = True

class DivisionWithStations(DivisionResponse):
    stations: List["StationResponse"] = []


# ─── Station ──────────────────────────────────────────────────────────────────

class StationBase(BaseModel):
    station_name: str
    station_code: str
    station_id_hex: str
    division_id: int

class StationCreate(StationBase):
    pass

class StationUpdate(BaseModel):
    station_name: Optional[str] = None
    station_code: Optional[str] = None
    station_id_hex: Optional[str] = None
    division_id: Optional[int] = None

class StationResponse(BaseModel):
    id: int
    station_name: str
    station_code: str
    station_id_hex: str
    division_id: int
    class Config:
        from_attributes = True


# ─── Gateway ──────────────────────────────────────────────────────────────────

class GatewayResponse(BaseModel):
    id: int
    stngw_id: str
    imei: Optional[str]
    station_id: Optional[int]
    created_at: datetime
    class Config:
        from_attributes = True


# ─── Telemetry (Gateway Ingestion) ────────────────────────────────────────────

class ParameterPayload(BaseModel):
    para_id: str
    prv: List[float]
    prt: List[str]

class GatewayDataPayload(BaseModel):
    imei: str
    stngw_id: str
    parameters: List[ParameterPayload]

class TelemetryResponse(BaseModel):
    id: int
    gateway_id: int
    para_id: str
    prv: Optional[float]
    prt: Optional[str]
    received_at: datetime
    class Config:
        from_attributes = True


class TelemetryPoint(BaseModel):
    """Single time-series data point used in chart responses."""
    t: str            # ISO timestamp string (prt from gateway, or received_at)
    v: Optional[float]


class TelemetrySeriesResponse(BaseModel):
    """
    A single parameter series for one asset — returned by the telemetry query endpoint.
    Contains everything the frontend needs to render a chart panel.
    """
    para_id: str
    asset_type_hex: str
    asset_type_name: Optional[str]
    asset_type_code: Optional[str]
    asset_number_hex: str               # bytes 2-3 of para_id
    parameter_type_hex: str             # bytes 4-5 of para_id
    parameter_name: Optional[str]       # e.g. "Peak Current"
    parameter_unit: Optional[str]       # e.g. "A"
    representation: Optional[str]       # e.g. "Maximum"
    stngw_id: str
    data: List[TelemetryPoint]
    latest_value: Optional[float]
    threshold_warning_low: Optional[float] = None
    threshold_warning_high: Optional[float] = None
    threshold_critical_low: Optional[float] = None
    threshold_critical_high: Optional[float] = None


class TelemetryQueryResponse(BaseModel):
    """Top-level response for GET /telemetry — groups series by asset."""
    station_id: Optional[int]
    station_name: Optional[str]
    asset_type_hex: Optional[str]
    asset_number: Optional[str]
    from_time: Optional[str]
    to_time: Optional[str]
    series: List[TelemetrySeriesResponse]


# ─── Assets ───────────────────────────────────────────────────────────────────

class AssetTypeOption(BaseModel):
    """One entry in the Asset Type dropdown."""
    hex_id: str          # e.g. "00"
    code: str            # e.g. "EOP"
    label: str           # e.g. "Point Machine"
    group_label: str     # display group for the UI, e.g. "Point Machine"


class AssetTypeGroupOption(BaseModel):
    """
    Grouped option for the dashboard Asset Type dropdown.
    Each group maps to one of the friendly labels in ASSET_TYPE_DISPLAY_GROUPS.
    """
    group_label: str
    asset_type_hexes: List[str]
    members: List[AssetTypeOption]


class ParameterTypeOption(BaseModel):
    """One entry in a parameter type listing."""
    hex_id: str          # e.g. "02"
    code: str            # e.g. "PEAK_CUR"
    label: str           # e.g. "Peak Current"
    unit: str            # e.g. "A"


class ParameterReprOption(BaseModel):
    """One entry in the representation listing."""
    hex_id: str
    code: str
    label: str


# ─── Thresholds ───────────────────────────────────────────────────────────────

class ThresholdBase(BaseModel):
    asset_type_hex: str
    parameter_type_hex: str
    station_id: Optional[int] = None
    warning_low: Optional[float] = None
    warning_high: Optional[float] = None
    critical_low: Optional[float] = None
    critical_high: Optional[float] = None
    unit: Optional[str] = None
    description: Optional[str] = None

class ThresholdCreate(ThresholdBase):
    pass

class ThresholdUpdate(BaseModel):
    warning_low: Optional[float] = None
    warning_high: Optional[float] = None
    critical_low: Optional[float] = None
    critical_high: Optional[float] = None
    unit: Optional[str] = None
    description: Optional[str] = None

class ThresholdResponse(ThresholdBase):
    id: int
    created_at: datetime
    updated_at: datetime
    class Config:
        from_attributes = True


# ─── Decode ───────────────────────────────────────────────────────────────────

class GatewayDecodeResponse(BaseModel):
    stngw_id: str
    zone_id_hex: str
    division_id_hex: str
    station_id_hex: str
    gateway_number_hex: str
    zone_name: Optional[str] = None
    zone_code: Optional[str] = None
    division_name: Optional[str] = None
    division_code: Optional[str] = None
    station_name: Optional[str] = None
    station_code: Optional[str] = None

class ParaDecodeResponse(BaseModel):
    para_id: str
    asset_type_id_hex: str
    asset_number_id_hex: str
    parameter_type_id_hex: str
    parameter_representation_id_hex: str
    asset_type_name: Optional[str] = None
    asset_type_code: Optional[str] = None
    parameter_name: Optional[str] = None
    parameter_unit: Optional[str] = None
    representation: Optional[str] = None


# ─── Dropdown ─────────────────────────────────────────────────────────────────

class DropdownOption(BaseModel):
    id: int
    label: str
    code: str
    hex_id: str


# Forward refs
ZoneWithDivisions.model_rebuild()
DivisionWithStations.model_rebuild()
