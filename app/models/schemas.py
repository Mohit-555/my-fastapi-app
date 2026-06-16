from __future__ import annotations

from pydantic import BaseModel, Field, AliasChoices, model_validator
from typing import List, Optional
from datetime import datetime


# ─── Zone ─────────────────────────────────────────────────────────────────────

class ZoneBase(BaseModel):
    zone_name: str = Field(validation_alias=AliasChoices('zone_name', 'zoneName', 'name'))
    zone_code: str = Field(validation_alias=AliasChoices('zone_code', 'zoneCode'))
    zone_id_hex: Optional[str] = Field(default=None, validation_alias=AliasChoices('zone_id_hex', 'zoneIdHex'))
    headquarters: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = "Active"

class ZoneCreate(ZoneBase):
    pass

class ZoneUpdate(BaseModel):
    zone_name: Optional[str] = Field(default=None, validation_alias=AliasChoices('zone_name', 'zoneName', 'name'))
    zone_code: Optional[str] = Field(default=None, validation_alias=AliasChoices('zone_code', 'zoneCode'))
    zone_id_hex: Optional[str] = Field(default=None, validation_alias=AliasChoices('zone_id_hex', 'zoneIdHex'))
    headquarters: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None

class ZoneResponse(ZoneBase):
    id: int
    zoneName: str = ""
    name: str = ""
    zoneCode: str = ""

    @model_validator(mode="after")
    def populate_aliases(self) -> "ZoneResponse":
        self.zoneName = self.zone_name
        self.name = self.zone_name
        self.zoneCode = self.zone_code
        return self

    class Config:
        from_attributes = True

class ZoneWithDivisions(ZoneResponse):
    divisions: List["DivisionResponse"] = []


# ─── Division ─────────────────────────────────────────────────────────────────

class DivisionBase(BaseModel):
    division_name: str = Field(validation_alias=AliasChoices('division_name', 'divisionName', 'name'))
    division_code: str = Field(validation_alias=AliasChoices('division_code', 'divisionCode'))
    division_id_hex: Optional[str] = Field(default=None, validation_alias=AliasChoices('division_id_hex', 'divisionIdHex'))
    zone_id: Optional[int] = None
    zone: Optional[str] = None
    headquarters: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = "Active"

class DivisionCreate(DivisionBase):
    pass

class DivisionUpdate(BaseModel):
    division_name: Optional[str] = Field(default=None, validation_alias=AliasChoices('division_name', 'divisionName', 'name'))
    division_code: Optional[str] = Field(default=None, validation_alias=AliasChoices('division_code', 'divisionCode'))
    division_id_hex: Optional[str] = Field(default=None, validation_alias=AliasChoices('division_id_hex', 'divisionIdHex'))
    zone_id: Optional[int] = None
    zone: Optional[str] = None
    headquarters: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None

class DivisionResponse(BaseModel):
    id: int
    division_name: str
    division_code: str
    division_id_hex: str
    zone_id: int
    headquarters: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = "Active"

    divisionName: str = ""
    name: str = ""
    divisionCode: str = ""
    zoneCode: str = ""
    zone: str = ""

    @model_validator(mode="before")
    @classmethod
    def pre_validate(cls, data: any) -> any:
        if not isinstance(data, dict):
            zone_code = getattr(data.zone, "zone_code", "") if getattr(data, "zone", None) else ""
            res = {
                "id": data.id,
                "division_name": data.division_name,
                "division_code": data.division_code,
                "division_id_hex": data.division_id_hex,
                "zone_id": data.zone_id,
                "headquarters": data.headquarters,
                "description": data.description,
                "status": data.status or "Active",
                "divisionName": data.division_name,
                "name": data.division_name,
                "divisionCode": data.division_code,
                "zoneCode": zone_code,
                "zone": zone_code,
            }
            if hasattr(data, "stations"):
                res["stations"] = data.stations
            return res
        else:
            data["divisionName"] = data.get("division_name", data.get("divisionName", ""))
            data["name"] = data.get("division_name", data.get("name", ""))
            data["divisionCode"] = data.get("division_code", data.get("divisionCode", ""))
            z_val = data.get("zone", "")
            if isinstance(z_val, str):
                data["zoneCode"] = data.get("zoneCode", z_val)
            return data

    class Config:
        from_attributes = True

class ZoneMinimalResponse(BaseModel):
    id: int
    zone_name: str
    zone_code: str
    zoneName: str = ""
    zoneCode: str = ""
    name: str = ""

    @model_validator(mode="after")
    def populate_aliases(self) -> "ZoneMinimalResponse":
        self.zoneName = self.zone_name
        self.zoneCode = self.zone_code
        self.name = self.zone_name
        return self

    class Config:
        from_attributes = True

class DivisionMinimalResponse(BaseModel):
    id: int
    division_name: str
    division_code: str
    zone_id: int
    divisionName: str = ""
    divisionCode: str = ""
    name: str = ""

    @model_validator(mode="after")
    def populate_aliases(self) -> "DivisionMinimalResponse":
        self.divisionName = self.division_name
        self.divisionCode = self.division_code
        self.name = self.division_name
        return self

    class Config:
        from_attributes = True

class StationMinimalResponse(BaseModel):
    id: int
    station_name: str
    station_code: str
    division_id: int
    stationName: str = ""
    stationCode: str = ""
    name: str = ""

    @model_validator(mode="after")
    def populate_aliases(self) -> "StationMinimalResponse":
        self.stationName = self.station_name
        self.stationCode = self.station_code
        self.name = self.station_name
        return self

    class Config:
        from_attributes = True

class DivisionWithStations(DivisionResponse):
    stations: List["StationResponse"] = []


# ─── Station ──────────────────────────────────────────────────────────────────

class StationBase(BaseModel):
    station_name: str = Field(validation_alias=AliasChoices('station_name', 'stationName', 'name'))
    station_code: str = Field(validation_alias=AliasChoices('station_code', 'stationCode'))
    station_id_hex: Optional[str] = Field(default=None, validation_alias=AliasChoices('station_id_hex', 'stationIdHex'))
    division_id: Optional[int] = None
    division: Optional[str] = None
    zone: Optional[str] = None
    category: Optional[str] = None
    address: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = "Active"

class StationCreate(StationBase):
    pass

class StationUpdate(BaseModel):
    station_name: Optional[str] = Field(default=None, validation_alias=AliasChoices('station_name', 'stationName', 'name'))
    station_code: Optional[str] = Field(default=None, validation_alias=AliasChoices('station_code', 'stationCode'))
    station_id_hex: Optional[str] = Field(default=None, validation_alias=AliasChoices('station_id_hex', 'stationIdHex'))
    division_id: Optional[int] = None
    division: Optional[str] = None
    zone: Optional[str] = None
    category: Optional[str] = None
    address: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None

class StationResponse(BaseModel):
    id: int
    station_name: str
    station_code: str
    station_id_hex: str
    division_id: int
    category: Optional[str] = None
    address: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = "Active"

    stationCode: str = ""
    stationName: str = ""
    name: str = ""
    zone: str = ""
    division: str = ""

    @model_validator(mode="before")
    @classmethod
    def pre_validate(cls, data: any) -> any:
        if not isinstance(data, dict):
            div_code = getattr(data.division, "division_code", "") if getattr(data, "division", None) else ""
            zone_code = getattr(data.division.zone, "zone_code", "") if (getattr(data, "division", None) and getattr(data.division, "zone", None)) else ""
            return {
                "id": data.id,
                "station_name": data.station_name,
                "station_code": data.station_code,
                "station_id_hex": data.station_id_hex,
                "division_id": data.division_id,
                "category": data.category,
                "address": data.address,
                "description": data.description,
                "status": data.status or "Active",
                "stationCode": data.station_code,
                "stationName": data.station_name,
                "name": data.station_name,
                "division": div_code,
                "zone": zone_code,
            }
        else:
            data["stationCode"] = data.get("station_code", data.get("stationCode", ""))
            data["stationName"] = data.get("station_name", data.get("stationName", ""))
            data["name"] = data.get("station_name", data.get("name", ""))
            d_val = data.get("division", "")
            if isinstance(d_val, str):
                data["division"] = d_val
            z_val = data.get("zone", "")
            if isinstance(z_val, str):
                data["zone"] = z_val
            return data

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

# ─── Telemetry History ────────────────────────────────────────────────────────

class TelemetryHistoryRow(BaseModel):
    """One timestamp row in the history table — values keyed by column label."""
    timestamp: str                          # e.g. "2026-06-04T12:10:00"
    asset_number_hex: str                   # e.g. "01"
    stngw_id: str
    values: dict                            # e.g. {"I_AVG (A)": 4.3, "I_PEAK (A)": 5.9}


class TelemetryHistoryColumn(BaseModel):
    """Metadata for one column in the history table."""
    key: str                                # dict key used in TelemetryHistoryRow.values
    parameter_name: str                     # e.g. "Avg Current"
    parameter_unit: str                     # e.g. "A"
    parameter_type_hex: str                 # e.g. "01"
    threshold_warning_low: Optional[float] = None
    threshold_warning_high: Optional[float] = None
    threshold_critical_low: Optional[float] = None
    threshold_critical_high: Optional[float] = None


class TelemetryHistoryResponse(BaseModel):
    station_id: Optional[int]
    station_name: Optional[str]
    asset_type_hex: Optional[str]
    asset_number: Optional[str]
    from_time: Optional[str]
    to_time: Optional[str]
    columns: List[TelemetryHistoryColumn]   # ordered list of columns for table headers
    total: int
    page: int
    page_size: int
    total_pages: int
    rows: List[TelemetryHistoryRow]
# ─── Assets ───────────────────────────────────────────────────────────────────

class AssetTypeOption(BaseModel):
    """One entry in the Asset Type dropdown."""
    id: int
    hex_id: str          # e.g. "00"
    code: str            # e.g. "EOP"
    label: str           # e.g. "Point Machine"
    group_label: str     # display group for the UI, e.g. "Point Machine"


class AssetTypeGroupOption(BaseModel):
    """
    Grouped option for the dashboard Asset Type dropdown.
    Each group maps to one of the friendly labels in ASSET_TYPE_DISPLAY_GROUPS.
    """
    id: int
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


# ─── Asset Inventory / Detail ─────────────────────────────────────────────────

class AssetInventoryBase(BaseModel):
    station_id: int
    asset_type_hex: str
    asset_make: str
    count: int

class AssetInventoryCreate(AssetInventoryBase):
    pass

class AssetInventoryUpdate(BaseModel):
    station_id: Optional[int] = None
    asset_type_hex: Optional[str] = None
    asset_make: Optional[str] = None
    count: Optional[int] = None

class AssetInventoryResponse(AssetInventoryBase):
    id: int
    created_at: datetime
    updated_at: datetime
    asset_type: str = ""
    class Config:
        from_attributes = True

class AssetMakeOption(BaseModel):
    id: int
    label: str
    value: str


class AssetFiltersResponse(BaseModel):
    zones: List[DropdownOption]
    divisions: List[DropdownOption]
    stations: List[DropdownOption]
    asset_types: List[AssetTypeGroupOption]
    asset_makes: List[AssetMakeOption]

class AssetDetailRow(BaseModel):
    id: int
    sr: int
    zone_id: int
    zone: Optional[ZoneMinimalResponse] = None
    division_id: int
    division: Optional[DivisionMinimalResponse] = None
    station_id: int
    station: Optional[StationMinimalResponse] = None
    asset_type_hex: str
    asset_type: str
    asset_make: str
    count: int

class AssetDetailResponse(BaseModel):
    as_on: str
    total: int
    rows: List[AssetDetailRow]

class DropdownOption(BaseModel):
    id: int
    label: str
    code: str
    hex_id: str

# ─── Alert Summary ────────────────────────────────────────────────────────────

class AlertEventBase(BaseModel):
    station_id: int
    alert_type: str
    asset_type_hex: str
    asset_no: str
    cause: str
    alert_status: str = "Active"
    feedback: Optional[str] = None
    acknowledged: bool = False
    remark: Optional[str] = None
    alert_time: Optional[datetime] = None
    rectification_time: Optional[datetime] = None
    feedback_time: Optional[datetime] = None
    maintainer_name: Optional[str] = None
    designation: Optional[str] = None
    mobile: Optional[str] = None


class AlertEventCreate(AlertEventBase):
    pass


class AlertEventUpdate(BaseModel):
    alert_type: Optional[str] = None
    asset_type_hex: Optional[str] = None
    asset_no: Optional[str] = None
    cause: Optional[str] = None
    alert_status: Optional[str] = None
    feedback: Optional[str] = None
    acknowledged: Optional[bool] = None
    remark: Optional[str] = None
    alert_time: Optional[datetime] = None
    rectification_time: Optional[datetime] = None
    feedback_time: Optional[datetime] = None
    maintainer_name: Optional[str] = None
    designation: Optional[str] = None
    mobile: Optional[str] = None


class AlertEventResponse(BaseModel):
    id: int
    station_id: int
    alert_type: str
    asset_type_hex: str
    asset_no: str
    cause: str
    alert_status: str
    feedback: Optional[str]
    acknowledged: bool
    remark: Optional[str]
    alert_time: datetime
    rectification_time: Optional[datetime]
    feedback_time: Optional[datetime]
    maintainer_name: Optional[str]
    designation: Optional[str]
    mobile: Optional[str]
    created_at: datetime
    updated_at: datetime
    class Config:
        from_attributes = True


class AlertHistoryRow(BaseModel):
    sr: int
    id: int
    zone_id: int
    zone: str
    division_id: int
    division: str
    station_id: int
    station: str
    alert_type: str
    asset_type_hex: str
    asset_type: str
    asset_no: str
    alert_status: str
    cause: str
    feedback: Optional[str]
    incidence_date_time: str
    rectification_date_time: Optional[str]
    duration_min: Optional[float]
    feedback_date_time: Optional[str]
    maintainer_name: Optional[str]
    designation: Optional[str]
    mobile: Optional[str]
    remarks: Optional[str]


class AlertHistoryResponse(BaseModel):
    from_time: Optional[str]
    to_time: Optional[str]
    total: int
    page: int
    page_size: int
    total_pages: int
    rows: List[AlertHistoryRow]


class AlertLiveSummary(BaseModel):
    predictive: int
    failure: int
    total: int


class AlertLiveCard(BaseModel):
    id: int
    zone_id: int
    zone: str
    division_id: int
    division: str
    station_id: int
    station: str
    title: str
    alert_type: str
    asset_type_hex: str
    asset_type: str
    asset_no: str
    alert_status: str
    cause: str
    feedback: Optional[str]
    acknowledged: bool
    incidence_date_time: str
    remarks: Optional[str]


class AlertLiveResponse(BaseModel):
    summary: AlertLiveSummary
    alerts: List[AlertLiveCard]


class AlertFeedbackUpdate(BaseModel):
    feedback: str
    feedback_time: Optional[datetime] = None


class AlertRemarkUpdate(BaseModel):
    remark: str


class AlertRectificationUpdate(BaseModel):
    rectification_time: Optional[datetime] = None
    alert_status: str = "Cleared"
    maintainer_name: Optional[str] = None
    designation: Optional[str] = None
    mobile: Optional[str] = None
    remarks: Optional[str] = None


class AlertSummaryRow(BaseModel):
    sr: int
    zone_id: int
    zone: str
    division_id: int
    division: str
    station_id: int
    station: str
    alert_type: str
    asset_type_hex: str
    asset_type: str
    asset_no: str
    cause: str
    total: int
    true: int
    partially_true: int
    percentage: float


class AlertSummaryResponse(BaseModel):
    from_time: Optional[str]
    to_time: Optional[str]
    total: int
    total_rows: int
    page: int
    page_size: int
    total_pages: int
    rows: List[AlertSummaryRow]


class AlertEventsResponse(BaseModel):
    total: int
    page: int
    page_size: int
    total_pages: int
    rows: List[AlertEventResponse]


class AlertFilterOption(BaseModel):
    id: int
    label: str
    value: str


class AlertFiltersResponse(BaseModel):
    zones: List[DropdownOption]
    divisions: List[DropdownOption]
    stations: List[DropdownOption]
    alert_types: List[AlertFilterOption]
    asset_types: List[AssetTypeGroupOption]
    asset_numbers: List[AlertFilterOption]
    causes: List[AlertFilterOption]
    feedbacks: List[AlertFilterOption]
    alert_statuses: List[AlertFilterOption]


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


# ─── Asset (assets table) ─────────────────────────────────────────────────────

class AssetCreate(BaseModel):
    """Register a new physical asset instance (RDSO/SPN/257/2025 Annexure A, Page 40)."""
    smms_asset_code:    str                         # unique SMMS code (g)
    smms_asset_name:    str                         # SMMS name (i)
    asset_number_code:  str                         # label at station e.g. PT-101 (h)
    asset_number_id:    str                         # 1-byte hex 00-FF (f)
    asset_type_hex:     str                         # e.g. "00"
    station_gateway_id: str                         # 8-char stngw_id FK
    station_id:         int
    make:               Optional[str] = None
    model:              Optional[str] = None
    attr1:              Optional[str] = None        # sub-asset type / custom attr
    attr2:              Optional[str] = None
    location:           Optional[str] = None
    is_active:          bool = True


class AssetUpdate(BaseModel):
    """Partial update — all fields optional."""
    smms_asset_code:    Optional[str] = None
    smms_asset_name:    Optional[str] = None
    asset_number_code:  Optional[str] = None
    asset_number_id:    Optional[str] = None
    asset_type_hex:     Optional[str] = None
    station_gateway_id: Optional[str] = None
    station_id:         Optional[int] = None
    make:               Optional[str] = None
    model:              Optional[str] = None
    attr1:              Optional[str] = None
    attr2:              Optional[str] = None
    location:           Optional[str] = None
    is_active:          Optional[bool] = None


class AssetResponse(BaseModel):
    id:                 int
    smms_asset_code:    str
    smms_asset_name:    str
    asset_number_code:  str
    asset_number_id:    str
    asset_type_hex:     str
    asset_type_name:    Optional[str] = None        # resolved
    asset_type_code:    Optional[str] = None        # resolved
    station_gateway_id: str
    station_id:         int
    station_code:       Optional[str] = None        # resolved
    station_name:       Optional[str] = None        # resolved
    make:               Optional[str] = None
    model:              Optional[str] = None
    attr1:              Optional[str] = None
    attr2:              Optional[str] = None
    location:           Optional[str] = None
    is_active:          bool
    created_at:         datetime
    updated_at:         datetime

    class Config:
        from_attributes = True


class AssetListResponse(BaseModel):
    total:       int
    page:        int
    page_size:   int
    total_pages: int
    rows:        List[AssetResponse]


# Forward refs
ZoneWithDivisions.model_rebuild()
DivisionWithStations.model_rebuild()
AlertFiltersResponse.model_rebuild()
# ─── Auth ─────────────────────────────────────────────────────────────────────

class UserLoginRequest(BaseModel):
    employee_id: str
    password: str
    remember_me: bool = False

class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int

class LoginUserResponse(BaseModel):
    id: int
    employee_id: str
    fullName: str
    role: Optional[int] = None
    email: Optional[str] = None
    designation: Optional[str] = None
    zone_id: Optional[int] = None
    division_id: Optional[int] = None
    mobile_number: Optional[str] = None
    reporting_officer_id: Optional[int] = None

class LoginDataResponse(BaseModel):
    token: str
    refresh_token: Optional[str] = None
    user: LoginUserResponse

class LoginResponse(BaseModel):
    status: bool
    message: str
    data: LoginDataResponse

class RefreshTokenRequest(BaseModel):
    refresh_token: str

class LogoutRequest(BaseModel):
    refresh_token: str

class LogoutResponse(BaseModel):
    message: str

class UserResponse(BaseModel):
    id: int
    full_name: str
    employee_id: str
    designation: str
    role_id: Optional[int] = None
    zone_id: Optional[int] = None
    division_id: Optional[int] = None
    email: str
    mobile_number: str
    reporting_officer_id: Optional[int] = None
    is_active: bool
    created_at: datetime
    class Config:
        from_attributes = True
# ─── RBAC ─────────────────────────────────────────────────────────────────────

class MenuBase(BaseModel):
    name: str
    slug: str
    parent_slug: Optional[str] = None
    icon: Optional[str] = None
    sort_order: int = 0
    is_active: bool = True

class MenuCreate(MenuBase):
    pass

class MenuUpdate(BaseModel):
    name: Optional[str] = None
    parent_slug: Optional[str] = None
    icon: Optional[str] = None
    sort_order: Optional[int] = None
    is_active: Optional[bool] = None

class MenuResponse(MenuBase):
    id: int
    path: str
    href: str
    roles: List[int] = []
    class Config:
        from_attributes = True


class MenuTreeResponse(BaseModel):
    id: int
    label: str
    icon: Optional[str] = None
    sort_order: int = 0
    roles: List[int] = []
    href: Optional[str] = None
    children: List["MenuTreeResponse"] = Field(default_factory=list)

    class Config:
        from_attributes = True


class RoleMenuAssign(BaseModel):
    menu_id: int = Field(validation_alias=AliasChoices('menu_id', 'id'))
    permission: str = "view"   # view / edit / full

class RoleMenuResponse(BaseModel):
    menu_id: int
    menu_name: str
    menu_slug: str
    parent_slug: Optional[str]
    permission: str
    class Config:
        from_attributes = True


class RoleBase(BaseModel):
    name: str
    display_name: str
    level: int = 0
    description: Optional[str] = None
    is_active: bool = True

class RoleCreate(RoleBase):
    menus: Optional[List[RoleMenuAssign]] = []   # assign menus at creation time

class RoleUpdate(BaseModel):
    display_name: Optional[str] = None
    level: Optional[int] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None

class RoleResponse(RoleBase):
    id: int
    created_at: datetime
    menus: List[MenuTreeResponse] = []
    class Config:
        from_attributes = True


# ─── User Management ──────────────────────────────────────────────────────────

class RoleMinimalResponse(BaseModel):
    id: int
    name: str
    display_name: str
    level: int

    class Config:
        from_attributes = True



class UserUpdateRequest(BaseModel):
    full_name: Optional[str] = None
    designation: Optional[str] = None
    role_id: Optional[int] = None
    zone_id: Optional[int] = None
    division_id: Optional[int] = None
    mobile_number: Optional[str] = None
    email: Optional[str] = None
    reporting_officer_id: Optional[int] = None
    is_active: Optional[bool] = None

class UserDetailResponse(BaseModel):
    id: int
    full_name: str
    employee_id: str
    designation: str
    role_id: Optional[int]
    role_name: Optional[str]
    role_display_name: Optional[str]
    zone_id: Optional[int]
    division_id: Optional[int]
    mobile_number: str
    email: str
    reporting_officer_id: Optional[int]
    is_active: bool
    created_at: datetime
    menus: List[RoleMenuResponse] = []   # menus this user can access via their role
    role: Optional[RoleMinimalResponse] = None
    zone: Optional[ZoneMinimalResponse] = None
    division: Optional[DivisionMinimalResponse] = None

    class Config:
        from_attributes = True

class UserListResponse(BaseModel):
    total: int
    page: int
    page_size: int
    total_pages: int
    rows: List[UserDetailResponse]

class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str
    confirm_new_password: str

# Update UserRegisterRequest to include role_id
class UserRegisterRequest(BaseModel):
    full_name: str
    employee_id: str
    designation: str
    role_id: Optional[int] = None        # ← NEW
    zone_id: Optional[int] = None
    division_id: Optional[int] = None
    mobile_number: str
    email: str
    password: str
    confirm_password: str
    reporting_officer_id: Optional[int] = None


class EquipmentRoomResponse(BaseModel):
    id: int
    station_id: int
    zone_id: int
    zone_code: str
    zone_name: str
    division_id: int
    division_code: str
    division_name: str
    station_code: str
    station_name: str
    room_type: str
    temperature: Optional[float] = None
    humidity: Optional[float] = None
    updated_at: datetime

    class Config:
        from_attributes = True


class EquipmentRoomHistoryRow(BaseModel):
    id: str
    zone_code: str
    division_code: str
    station_code: str
    station_name: str
    timestamp: datetime
    room_type: str
    temperature: float
    humidity: float

    class Config:
        from_attributes = True


class EquipmentRoomHistoryResponse(BaseModel):
    total: int
    page: int
    page_size: int
    rows: List[EquipmentRoomHistoryRow]


# ─── Maintenance Mode ─────────────────────────────────────────────────────────

class MaintenanceModeRequest(BaseModel):
    station_id: int
    asset_type_hex: str
    asset_no: str
    from_time: datetime
    to_time: datetime


class MaintenanceModeResponse(BaseModel):
    id: int
    zone_id: int
    zone_code: str
    zone_name: str
    division_id: int
    division_code: str
    division_name: str
    station_id: int
    station_code: str
    station_name: str
    asset_type_hex: str
    asset_type_name: str
    asset_no: str
    from_time: datetime
    to_time: datetime
    created_at: datetime

    class Config:
        from_attributes = True


class MaintenanceModeListResponse(BaseModel):
    total: int
    page: int
    page_size: int
    rows: List[MaintenanceModeResponse]


# ─── Alert Causes ─────────────────────────────────────────────────────────────

from enum import Enum as PyEnum

class AlertCategoryEnum(str, PyEnum):
    FAILURE = "FAILURE"
    PREDICTIVE = "PREDICTIVE"

class AlertCauseCreate(BaseModel):
    cause_code: str = Field(..., max_length=50, validation_alias=AliasChoices('cause_code', 'causeCode'))
    cause_detail: str = Field(..., validation_alias=AliasChoices('cause_detail', 'causeDetail'))
    asset_type_id: Optional[str] = Field(None, max_length=2, validation_alias=AliasChoices('asset_type_id', 'assetTypeId'))
    alert_category: AlertCategoryEnum = Field(..., validation_alias=AliasChoices('alert_category', 'alertCategory'))

class AlertCauseUpdate(BaseModel):
    cause_detail: Optional[str] = Field(None, validation_alias=AliasChoices('cause_detail', 'causeDetail'))
    asset_type_id: Optional[str] = Field(None, max_length=2, validation_alias=AliasChoices('asset_type_id', 'assetTypeId'))
    alert_category: Optional[AlertCategoryEnum] = Field(None, validation_alias=AliasChoices('alert_category', 'alertCategory'))

class AlertCauseResponse(BaseModel):
    cause_code: str
    cause_detail: str
    asset_type_id: Optional[str] = None
    alert_category: AlertCategoryEnum
    created_at: datetime

    # CamelCase aliases for frontend compatibility
    causeCode: str = ""
    causeDetail: str = ""
    assetTypeId: Optional[str] = None
    alertCategory: str = ""

    @model_validator(mode="after")
    def populate_aliases(self) -> "AlertCauseResponse":
        self.causeCode = self.cause_code
        self.causeDetail = self.cause_detail
        self.assetTypeId = self.asset_type_id
        self.alertCategory = self.alert_category.value
        return self

    class Config:
        from_attributes = True

class AlertCauseListResponse(BaseModel):
    total: int
    page: int
    page_size: int
    total_pages: int
    rows: List[AlertCauseResponse]


