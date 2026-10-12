"""
Telemetry query router — supports the dashboard's filter bar:
  Zone → Division → Station → Asset Type → Asset No → time range

Also provides a Server-Sent Events (SSE) endpoint for the LIVE indicator.
"""
import csv
import io
import asyncio
import json
from datetime import datetime, timedelta
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, func

from app.database import get_db, SessionLocal
from app.models.models import Telemetry, Gateway, Station, Division, Zone, Threshold, Asset, AssetTypeMaster
from app.models.schemas import (
    TelemetryQueryResponse, TelemetrySeriesResponse, TelemetryPoint,
    TelemetryHistoryResponse, TelemetryHistoryColumn, TelemetryHistoryRow,
    TelemetryLiveCardResponse, LiveParameterItem, ThrowTimeCyclePoint,
    StandardResponse,
    TelemetrySummaryResponse, TelemetrySummaryRow, TelemetrySummaryMetrics
)
from app.constants import (
    ASSET_TYPE_MAP, PARAMETER_TYPE_MAP, PARAMETER_REPR_MAP, ASSET_TYPE_DISPLAY_GROUPS,
    ASSET_PARAMETER_CATALOG, GENERIC_PARAMETER_TYPE_MAP
)
from app.services.parameter_config_service import param_config_service

router = APIRouter(prefix="/telemetry", tags=["Telemetry Query"])


# ─────────────────────────────────────────────────────────────────────────────
# Dual-Mode Parameter Resolution (RDSO Canonical + Legacy Simulator Aliases)
#
# RDSO Canonical: What the para_id means per Annexure A of RDSO/SPN/257/2025
# Legacy Alias:   What the current simulator / frontend expects
#
# Strategy: return BOTH so we never break existing UI while becoming
#           spec-compliant for real gateway data.
# ─────────────────────────────────────────────────────────────────────────────

# Key format: <param_type_hex><repr_hex> OR <param_type_hex>_<asset_type_hex>
RDSO_PARAM_MAP = {
    # ── Point Machine (asset_type = 00) ──
    "000A": {"primary": "VPT_110_DC_LOC_N", "display": "110V DC Loc Normal",   "unit": "V"},
    "000B": {"primary": "VPT_110_DC_LOC_R", "display": "110V DC Loc Reverse",  "unit": "V"},
    "000C": {"primary": "IPT_N",            "display": "Normal Current",       "unit": "A"},
    "000D": {"primary": "IPT_R",            "display": "Reverse Current",      "unit": "A"},
    "000E": {"primary": "VPT_NWKR",         "display": "NWKR Voltage",         "unit": "V"},
    "000F": {"primary": "VPT_RWKR",         "display": "RWKR Voltage",         "unit": "V"},
    "9060": {"primary": "TPT_N",            "display": "Normal Stroke Time",   "unit": "ms"},
    "9061": {"primary": "TPT_R",            "display": "Reverse Stroke Time",  "unit": "ms"},
    "2020": {"primary": "VPT_24_DC_LOC",    "display": "24V DC Loc",           "unit": "V"},
    "2021": {"primary": "VPT_24_DC_LOC",    "display": "24V DC Loc",           "unit": "V"},
    "5000": {"primary": "TEMP_PT",          "display": "Motor Temperature",    "unit": "°C"},

    # ── DC Track Circuit (asset_type = 20) ──
    "3001": {"primary": "VTC_TFC_IP",       "display": "TFC Input Voltage",    "unit": "V"},
    "2002": {"primary": "VTC_TFC_OP",       "display": "TFC Output Voltage",   "unit": "V"},
    "0103": {"primary": "ITC_TFC_OP",       "display": "TFC Output Current",   "unit": "mA"},
    "010B": {"primary": "ITC_RELAY_END",    "display": "Relay End Current",    "unit": "mA"},
    "200C": {"primary": "VTC_TR",           "display": "Track Relay Voltage",  "unit": "V"},
    "200D": {"primary": "VTC_24_DC_LOC",    "display": "24V DC Loc",           "unit": "V"},

    # ── Main Signal (asset_type = 10) ──
    "3001_SIG": {"primary": "VSIG_DG",      "display": "Green Aspect Voltage", "unit": "V"},
    "3002_SIG": {"primary": "VSIG_HG",      "display": "Yellow Aspect Voltage","unit": "V"},
    "3003_SIG": {"primary": "VSIG_HHG",     "display": "Double Yellow Voltage","unit": "V"},
    "3004_SIG": {"primary": "VSIG_RG",      "display": "Red Aspect Voltage",   "unit": "V"},
    "1105":     {"primary": "ISIG_DG",      "display": "Green Aspect Current", "unit": "mA"},
    "1106":     {"primary": "ISIG_HG",      "display": "Yellow Aspect Current","unit": "mA"},
    "1107":     {"primary": "ISIG_HHG",     "display": "Double Yellow Current","unit": "mA"},
    "1108":     {"primary": "ISIG_RG",      "display": "Red Aspect Current",   "unit": "mA"},

    # ── Equipment Rooms (asset_type = F0-F6) ──
    "5001": {"primary": "TEMPRR",           "display": "Room Temperature",     "unit": "°C"},
    "5102": {"primary": "HUMDRR",           "display": "Room Humidity",        "unit": "%"},
    "4000": {"primary": "DOORRR",           "display": "Door Status",          "unit": ""},
}

# Legacy alias mappings — the existing simulator/frontend keys
LEGACY_ALIAS_MAP = {
    "000C": {"key": "I_avg",     "display": "Avg Current",     "field": "Avg_Current"},
    "000D": {"key": "I_peak",    "display": "Peak Current",    "field": "Peak_Current"},
    "9060": {"key": "stroke_ms", "display": "Stroke Time",     "field": "Stroke_Time"},
    "9061": {"key": "stroke_ms", "display": "Stroke Time",     "field": "Stroke_Time"},
    "2020": {"key": "V_batt",    "display": "Battery Voltage", "field": "Battery_Voltage"},
    "2021": {"key": "V_batt",    "display": "Battery Voltage", "field": "Battery_Voltage"},
    "5000": {"key": "temp",      "display": "Temperature",     "field": "Temperature"},
    "F000": {"key": "temp",      "display": "Temperature",     "field": "Temperature"},
    "0001": {"key": "I_avg",     "display": "Avg Current",     "field": "Avg_Current"},
    "0002": {"key": "I_peak",    "display": "Peak Current",    "field": "Peak_Current"},
    "0003": {"key": "stroke_ms", "display": "Stroke Time",     "field": "Stroke_Time"},
    "0004": {"key": "V_batt",    "display": "Battery Voltage", "field": "Battery_Voltage"},
    "0005": {"key": "temp",      "display": "Temperature",     "field": "Temperature"},
    "0500": {"key": "temp",      "display": "Temperature",     "field": "Temperature"},
}


def _resolve_parameter_dual_mode(pid: str) -> dict:
    """
    Resolve a para_id into BOTH RDSO canonical and legacy alias naming.

    Returns:
      {
        "primary_name":   "IPT_N",
        "display_name":   "Normal Current",
        "unit":           "A",
        "legacy_key":     "I_avg",
        "legacy_display": "Avg Current",
        "legacy_field":   "Avg_Current"
      }
    """
    if not pid or len(pid) < 8:
        return {
            "primary_name": None, "display_name": "Unknown",
            "unit": "", "legacy_key": None,
            "legacy_display": None, "legacy_field": None,
        }

    at_hex = pid[0:2].upper()
    pt_hex = pid[4:6].upper()
    suffix = pid[4:].upper()  # bytes 4-7

    # Most specific first: suffix (param_type + representation)
    spec = RDSO_PARAM_MAP.get(suffix)

    # Fallback: asset-type–specific key (used for signals)
    if not spec:
        spec = RDSO_PARAM_MAP.get(f"{suffix}_{at_hex}")
    if not spec:
        spec = RDSO_PARAM_MAP.get(pt_hex)

    alias = LEGACY_ALIAS_MAP.get(suffix) or LEGACY_ALIAS_MAP.get(pt_hex)

    if not spec:
        return {
            "primary_name": f"PARAM_{suffix}",
            "display_name": f"Param {suffix}",
            "unit": "", "legacy_key": None,
            "legacy_display": None, "legacy_field": None,
        }

    return {
        "primary_name": spec["primary"],
        "display_name": spec["display"],
        "unit": spec.get("unit", ""),
        "legacy_key": alias["key"] if alias else None,
        "legacy_display": alias["display"] if alias else None,
        "legacy_field": alias["field"] if alias else None,
    }


def _blank_to_none(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    val = value.strip()
    return None if val == "" else val


def _resolve_asset_types_to_hex(db: Session, asset_type: Optional[str]) -> Optional[str]:
    asset_type = _blank_to_none(asset_type)
    if not asset_type:
        return None

    parts = [p.strip() for p in asset_type.split(",") if p.strip()]
    if all(p.isdigit() for p in parts):
        ids = [int(p) for p in parts]
        db_types = db.query(AssetTypeMaster).filter(AssetTypeMaster.id.in_(ids)).all()
        hexes = [t.asset_type_id for t in db_types if t.asset_type_id]
        if not hexes:
            return "IMPOSSIBLE_HEX"
        return ",".join(hexes)

    hex_list = []
    for part in parts:
        if part.upper() in ASSET_TYPE_MAP:
            hex_list.append(part.upper())
        else:
            group_hexes = ASSET_TYPE_DISPLAY_GROUPS.get(part)
            if group_hexes:
                hex_list.extend(group_hexes)
    if hex_list:
        return ",".join(hex_list)
    return None
integration_router = APIRouter(tags=["Telemetry Integration"])


def _resolve_station_ids(
    db: Session,
    zone_id: Optional[int],
    division_id: Optional[int],
    station_id: Optional[int],
) -> Optional[List[int]]:
    """
    Return a flat list of station IDs matching the given filter combination.
    Returns None if no filter is set (= all stations).
    """
    if station_id:
        return [station_id]

    if division_id:
        rows = db.query(Station.id).filter(Station.division_id == division_id).all()
        return [r.id for r in rows]

    if zone_id:
        div_ids = [r.id for r in db.query(Division.id).filter(Division.zone_id == zone_id).all()]
        if not div_ids:
            return []
        rows = db.query(Station.id).filter(Station.division_id.in_(div_ids)).all()
        return [r.id for r in rows]

    return None  # no filter → all


def _parse_telemetry_datetime(dt_str: Optional[str], default: Optional[datetime] = None) -> Optional[datetime]:
    if not dt_str:
        return default
    
    dt_str_clean = dt_str.strip().rstrip('Z')
    for fmt in (
        "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M",
        "%d/%m/%Y %H:%M:%S.%f", "%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M",
        "%d-%m-%Y %H:%M:%S.%f", "%d-%m-%Y %H:%M:%S", "%d-%m-%Y %H:%M",
    ):
        try:
            return datetime.strptime(dt_str_clean, fmt)
        except ValueError:
            continue
            
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(dt_str_clean, fmt)
        except ValueError:
            continue
            
    for fmt in ("%H:%M:%S", "%H:%M"):
        try:
            t = datetime.strptime(dt_str_clean, fmt).time()
            return datetime.combine(datetime.now().date(), t)
        except ValueError:
            continue

    try:
        return datetime.fromisoformat(dt_str_clean)
    except Exception:
        return default


def _resolve_station_ids_by_codes(
    db: Session,
    zone_code: Optional[str] = None,
    division_code: Optional[str] = None,
    station_code: Optional[str] = None,
    station_id: Optional[int] = None,
) -> Optional[List[int]]:
    # If no filters at all are provided, return None
    if not (zone_code or division_code or station_code or station_id is not None):
        return None
        
    q = db.query(Station.id).join(Division).join(Zone)
    
    if station_id is not None:
        q = q.filter(Station.id == station_id)
    if station_code:
        q = q.filter(Station.station_code == station_code.upper())
    if division_code:
        q = q.filter(Division.division_code == division_code.upper())
    if zone_code:
        q = q.filter(Zone.zone_code == zone_code.upper())
        
    rows = q.all()
    return [r.id for r in rows]


def _get_threshold(
    db: Session,
    asset_type_hex: str,
    parameter_type_hex: str,
    station_id: Optional[int],
) -> Optional[Threshold]:
    """
    Look up threshold with station-specific override priority.
    First tries station-specific, then falls back to the global default.
    """
    if station_id:
        t = db.query(Threshold).filter(
            Threshold.asset_type_hex == asset_type_hex,
            Threshold.parameter_type_hex == parameter_type_hex,
            Threshold.station_id == station_id,
        ).first()
        if t:
            return t
    # fall back to global default (station_id IS NULL)
    return db.query(Threshold).filter(
        Threshold.asset_type_hex == asset_type_hex,
        Threshold.parameter_type_hex == parameter_type_hex,
        Threshold.station_id.is_(None),
    ).first()


def _build_series(
    db: Session,
    para_id: str,
    rows: List[Telemetry],
    gateway: Gateway,
) -> TelemetrySeriesResponse:
    """Build a TelemetrySeriesResponse from a list of Telemetry rows for one para_id."""
    asset_type_hex      = para_id[0:2]
    asset_number_hex    = para_id[2:4]
    parameter_type_hex  = para_id[4:6]
    repr_hex            = para_id[6:8]

    asset_info  = ASSET_TYPE_MAP.get(asset_type_hex)
    param_info  = PARAMETER_TYPE_MAP.get(parameter_type_hex)
    repr_info   = PARAMETER_REPR_MAP.get(repr_hex)

    threshold = _get_threshold(db, asset_type_hex, parameter_type_hex, gateway.station_id)

    data_points = [
        TelemetryPoint(
            t=row.prt or row.received_at.isoformat(),
            v=row.prv,
        )
        for row in sorted(rows, key=lambda r: r.received_at)
    ]

    latest = rows[0].prv if rows else None  # rows already ordered desc

    return TelemetrySeriesResponse(
        para_id=para_id,
        asset_type_hex=asset_type_hex,
        asset_type_name=asset_info[1] if asset_info else None,
        asset_type_code=asset_info[0] if asset_info else None,
        asset_number_hex=asset_number_hex,
        parameter_type_hex=parameter_type_hex,
        parameter_name=param_info[1] if param_info else None,
        parameter_unit=param_info[2] if param_info else None,
        representation=repr_info[1] if repr_info else None,
        stngw_id=gateway.stngw_id,
        data=data_points,
        latest_value=latest,
        threshold_warning_low=threshold.warning_low if threshold else None,
        threshold_warning_high=threshold.warning_high if threshold else None,
        threshold_critical_low=threshold.critical_low if threshold else None,
        threshold_critical_high=threshold.critical_high if threshold else None,
    )


@router.get("", response_model=StandardResponse[TelemetryQueryResponse])
def query_telemetry(
    # ── Location filters ──────────────────────────────────────────────────────
    zone_id:     Optional[int]  = Query(None, description="Filter by zone"),
    division_id: Optional[int]  = Query(None, description="Filter by division"),
    station_id:  Optional[int]  = Query(None, description="Filter by station"),
    # ── Asset filters ─────────────────────────────────────────────────────────
    asset_type: Optional[str] = Query(
        None,
        description="Asset type database ID(s), name(s), or hex(es), comma-separated.",
    ),
    asset_number_hex: Optional[str] = Query(
        None,
        description="Asset number hex (bytes 2-3 of para_id), e.g. '01' for asset #1",
    ),
    parameter_type_hex: Optional[str] = Query(
        None,
        description="Parameter type hex (bytes 4-5 of para_id), e.g. '02' for Peak Current",
    ),
    # ── Time range ────────────────────────────────────────────────────────────
    from_time: Optional[datetime] = Query(
        None,
        description="Start of time range (ISO 8601). Defaults to 1 hour ago.",
    ),
    to_time: Optional[datetime] = Query(
        None,
        description="End of time range (ISO 8601). Defaults to now.",
    ),
    limit: int = Query(500, le=5000, description="Max readings per para_id"),
    db: Session = Depends(get_db),
):
    """
    Main telemetry query endpoint used by the dashboard filter bar.

    Returns grouped time-series data with threshold values and parameter metadata
    for every matching para_id × gateway combination.

    Examples:
      GET /telemetry?station_id=12&asset_type=1
        → All Point Machine readings at station 12 for the last hour
    """
    now = datetime.utcnow()
    if from_time is None:
        from_time = now - timedelta(hours=1)
    if to_time is None:
        to_time = now

    asset_type_hex = _resolve_asset_types_to_hex(db, asset_type)

    # ── Resolve station IDs from location filter ──────────────────────────────
    station_ids = _resolve_station_ids(db, zone_id, division_id, station_id)

    _empty = TelemetryQueryResponse(
        station_id=station_id,
        station_name=None,
        asset_type_hex=asset_type_hex,
        asset_number=asset_number_hex,
        from_time=from_time.isoformat(),
        to_time=to_time.isoformat(),
        series=[],
    )

    # ── Resolve gateway IDs ───────────────────────────────────────────────────
    gw_query = db.query(Gateway)
    if station_ids is not None:
        if not station_ids:
            # Location filter matched nothing
            return {"status": True, "message": "Success", "data": _empty}
        gw_query = gw_query.filter(Gateway.station_id.in_(station_ids))

    gateways = gw_query.all()
    if not gateways:
        return {"status": True, "message": "Success", "data": _empty}

    gateway_ids = [g.id for g in gateways]
    gateway_map = {g.id: g for g in gateways}

    # ── Build para_id prefix filters ─────────────────────────────────────────
    # para_id is 8 hex chars: [asset_type 2][asset_num 2][param_type 2][repr 2]
    # We filter with LIKE patterns for efficient DB-side filtering.
    base_filters = [
        Telemetry.gateway_id.in_(gateway_ids),
        Telemetry.received_at >= from_time,
        Telemetry.received_at <= to_time,
    ]

    asset_type_hexes = (
        [h.strip().upper() for h in asset_type_hex.split(",")]
        if asset_type_hex else None
    )

    # Fetch rows
    telem_query = db.query(Telemetry).filter(and_(*base_filters))

    # Use a ranked subquery with ROW_NUMBER() partitioned by gateway_id and para_id
    # to fetch at most `limit` rows per unique parameter series, avoiding starvation.
    rn_col = func.row_number().over(
        partition_by=[Telemetry.gateway_id, Telemetry.para_id],
        order_by=Telemetry.received_at.desc()
    ).label("rn")

    ranked_sq = (
        db.query(Telemetry.id.label("t_id"), rn_col)
        .filter(and_(*base_filters))
        .subquery()
    )

    rows_all = (
        db.query(Telemetry)
        .join(ranked_sq, Telemetry.id == ranked_sq.c.t_id)
        .filter(ranked_sq.c.rn <= limit)
        .order_by(Telemetry.received_at.desc())
        .all()
    )

    # ── Group by (gateway_id, para_id) and apply asset/param filters ──────────
    grouped: dict[tuple, list] = {}
    for row in rows_all:
        pid = row.para_id  # already upper from ingestion
        if len(pid) != 8:
            continue

        at_hex  = pid[0:2]
        an_hex  = pid[2:4]
        pt_hex  = pid[4:6]

        if asset_type_hexes and at_hex not in asset_type_hexes:
            continue
        if asset_number_hex and an_hex != asset_number_hex.upper():
            continue
        if parameter_type_hex and pt_hex != parameter_type_hex.upper():
            continue

        key = (row.gateway_id, pid)
        if key not in grouped:
            grouped[key] = []
        if len(grouped[key]) < limit:
            grouped[key].append(row)

    # ── Build series list ─────────────────────────────────────────────────────
    series: List[TelemetrySeriesResponse] = []
    for (gw_id, para_id_key), rows in grouped.items():
        gw = gateway_map[gw_id]
        series.append(_build_series(db, para_id_key, rows, gw))

    # ── Station name for response metadata ────────────────────────────────────
    stn_name = None
    if station_id:
        stn = db.query(Station).filter(Station.id == station_id).first()
        stn_name = stn.station_name if stn else None

    response_data = TelemetryQueryResponse(
        station_id=station_id,
        station_name=stn_name,
        asset_type_hex=asset_type_hex,
        asset_number=asset_number_hex,
        from_time=from_time.isoformat(),
        to_time=to_time.isoformat(),
        series=series,
    )
    return {
        "status": True,
        "message": "Success",
        "data": response_data
    }


# ── SSE Live Stream ───────────────────────────────────────────────────────────

def _setup_sse_asset_sync(station_id: int, asset_number: str):
    db = SessionLocal()
    try:
        asset = (
            db.query(Asset)
            .filter(
                Asset.station_id == station_id,
                or_(
                    Asset.asset_number_code == asset_number,
                    Asset.smms_asset_code == asset_number
                )
            )
            .first()
        )
        if not asset:
            return {"error": f"Asset {asset_number} not found at station {station_id}"}

        gateway_id = asset.gateway.id if asset.gateway else None
        if not gateway_id:
            return {"error": f"Asset {asset_number} has no gateway"}

        prefix = f"{asset.asset_type_hex}{asset.asset_number_id}"

        # Resolve initial_last_seen_id to start from the latest records (most recent 15 rows)
        subq = (
            db.query(Telemetry.id)
            .filter(
                Telemetry.gateway_id == gateway_id,
                Telemetry.para_id.like(f"{prefix}%")
            )
            .order_by(Telemetry.id.desc())
            .limit(15)
            .all()
        )
        initial_last_seen_id = 0
        if subq:
            initial_last_seen_id = min(r[0] for r in subq) - 1

        resolved_zone = asset.station.division.zone.zone_code if asset.station and asset.station.division and asset.station.division.zone else "NR"
        resolved_div = asset.station.division.division_code if asset.station and asset.station.division else ""
        resolved_stn = asset.station.station_code if asset.station else ""

        return {
            "gateway_id": gateway_id,
            "gw_stngw_id": asset.gateway.stngw_id,
            "station_id": asset.station_id,
            "prefix": prefix,
            "asset_type_hex": asset.asset_type_hex,
            "asset_type_name": asset.asset_type.asset_type_name if asset.asset_type else None,
            "initial_last_seen_id": initial_last_seen_id,
            "zone_code": resolved_zone,
            "division_code": resolved_div,
            "station_code": resolved_stn,
        }
    finally:
        db.close()


def _map_pid_to_field(pid: str, current_item: dict) -> Optional[str]:
    """
    Map a para_id to the frontend field name.
    Uses dual-mode: returns RDSO canonical field OR legacy alias.
    Kept for backward compatibility with the existing live payload builder.
    """
    if not pid or len(pid) < 8:
        return None

    dual = _resolve_parameter_dual_mode(pid)
    if dual["legacy_field"]:
        return dual["legacy_field"]

    # Fallback for unknown types — use parameter_type_hex convention
    pt_hex = pid[4:6].upper()
    return {
        "00": "Avg_Current", "01": "Avg_Current",
        "02": "Peak_Current", "03": "Stroke_Time",
        "04": "Battery_Voltage", "05": "Temperature",
        "50": "Temperature", "51": "Humidity",
    }.get(pt_hex)


def _poll_telemetry_sync(
    gateway_id: int,
    prefix: str,
    last_seen_id: int,
    asset_type_hex: str,
    station_id: int,
    asset_type_name: Optional[str],
    asset_number: str,
    gw_stngw_id: str,
    zone_code: str = "NR",
    division_code: str = "",
    station_code: str = "",
):
    db = SessionLocal()
    try:
        q = (
            db.query(Telemetry)
            .filter(
                Telemetry.gateway_id == gateway_id,
                Telemetry.para_id.like(f"{prefix}%"),
                Telemetry.id > last_seen_id,
            )
            .order_by(Telemetry.id.asc())
            .limit(100)
        )
        new_rows = q.all()

        payloads = []
        next_seen_id = last_seen_id

        if new_rows:
            next_seen_id = new_rows[-1].id

            # Group rows by device timestamp (prt) to merge same-batch parameter updates into a single live_data row
            ts_groups: dict[str, list] = {}
            for r in new_rows:
                ts_key = (r.prt.split(" ")[-1][:8] if r.prt and " " in r.prt else r.prt) if r.prt else (r.received_at.strftime("%H:%M:%S") if r.received_at else "Now")
                ts_groups.setdefault(ts_key, []).append(r)

            # Map para_id suffix → frontend field key
            _SUFFIX_FIELD = {
                "000C": "I_avg",  "0001": "I_avg",  "01": "I_avg",
                "000D": "I_peak", "0002": "I_peak", "02": "I_peak",
                "9060": "stroke_ms","9061":"stroke_ms","03":"stroke_ms",
                "2020": "V_batt", "2021": "V_batt", "04": "V_batt",
                "5000": "temp",   "F000": "temp",   "05": "temp",
                "0500": "temp",   "50": "temp",
            }

            for ts_key, rows in ts_groups.items():
                row_item = {
                    "time": ts_key,
                    "Avg_Current": None,
                    "Peak_Current": None,
                    "Battery_Voltage": None,
                    "Stroke_Time": None,
                    "Temperature": None,
                    "I_avg": None,
                    "I_peak": None,
                    "V_batt": None,
                    "stroke_ms": None,
                    "temp": None,
                }
                points_data = []
                last_pid = rows[-1].para_id

                # Collect per-field thresholds from all rows in this timestamp group
                field_thresholds: dict = {}
                for r in rows:
                    field = _map_pid_to_field(r.para_id, row_item)
                    if field:
                        row_item[field] = r.prv
                        if field == "Avg_Current":
                            row_item["I_avg"] = r.prv
                        elif field == "Peak_Current":
                            row_item["I_peak"] = r.prv
                        elif field == "Battery_Voltage":
                            row_item["V_batt"] = r.prv
                        elif field == "Stroke_Time":
                            row_item["stroke_ms"] = r.prv
                        elif field == "Temperature":
                            row_item["temp"] = r.prv
                    points_data.append({"t": r.prt or r.received_at.isoformat(), "v": r.prv})

                    if len(r.para_id) == 8:
                        suffix = r.para_id[4:].upper()
                        type_code = r.para_id[4:6]
                        fk = _SUFFIX_FIELD.get(suffix) or _SUFFIX_FIELD.get(type_code)
                        # Map hardware suffix → catalog parameter_type_hex stored in DB
                        _SUFFIX_CATALOG = {
                            "000C": "01", "0001": "01", "I_avg": "01",
                            "000D": "02", "0002": "02", "I_peak": "02",
                            "9060": "03", "9061": "03", "stroke_ms": "03",
                            "2020": "04", "2021": "04", "V_batt": "04",
                            "5000": "05", "F000": "05", "temp": "05",
                            "0500": "05", "0005": "05", "50": "05",
                        }
                        db_type_hex = _SUFFIX_CATALOG.get(suffix) or _SUFFIX_CATALOG.get(fk) or type_code
                        if fk and fk not in field_thresholds:
                            thr = _get_threshold(db, asset_type_hex, db_type_hex, station_id)
                            if thr:
                                field_thresholds[fk] = {
                                    "warning_high":  thr.warning_high,
                                    "warning_low":   thr.warning_low,
                                    "critical_high": thr.critical_high,
                                    "critical_low":  thr.critical_low,
                                }

                # Compute real Status from thresholds + live values
                status = "Healthy"
                _FIELD_VAL_MAP = {
                    "I_avg":     row_item.get("Avg_Current"),
                    "I_peak":    row_item.get("Peak_Current"),
                    "V_batt":    row_item.get("Battery_Voltage"),
                    "stroke_ms": row_item.get("Stroke_Time"),
                    "temp":      row_item.get("Temperature"),
                }
                for fk, val in _FIELD_VAL_MAP.items():
                    if val is None:
                        continue
                    thr = field_thresholds.get(fk, {})
                    ch = thr.get("critical_high")
                    wh = thr.get("warning_high")
                    cl = thr.get("critical_low")
                    wl = thr.get("warning_low")
                    if (ch is not None and val > ch) or (cl is not None and val < cl):
                        status = "Failure"
                        break
                    if (wh is not None and val > wh) or (wl is not None and val < wl):
                        if status != "Failure":
                            status = "Predictive"

                # ── DUAL-MODE: resolve both RDSO canonical and legacy names ──
                dual = _resolve_parameter_dual_mode(last_pid)

                payload = {
                    "Zone": zone_code,
                    "Division": division_code,
                    "Station": station_code,
                    "Asset_Type": asset_type_name or "Point Machine",
                    "Asset_No": asset_number or "PT-101",
                    "Time": datetime.now().strftime("%H:%M:%S"),
                    "Status": status,
                    "live_data": [row_item],
                    "para_id": last_pid,
                    "stngw_id": gw_stngw_id,
                    "asset_type_hex": asset_type_hex,
                    "asset_type_name": asset_type_name,

                    # ── NEW: RDSO canonical fields ──
                    "primary_name":   dual["primary_name"],
                    "parameter_name": dual["display_name"],     # was param_info[1]
                    "parameter_unit": dual["unit"],             # was param_info[2]

                    # ── LEGACY: keep old aliases for current frontend ──
                    "legacy_key":     dual["legacy_key"],
                    "legacy_display": dual["legacy_display"],

                    "points": points_data,
                    "field_thresholds": field_thresholds if field_thresholds else None,
                }
                payloads.append(payload)

        return {
            "payloads": payloads,
            "next_seen_id": next_seen_id
        }
    finally:
        db.close()


async def _sse_event_generator(request: Request, station_id: int, asset_number: str, poll_interval: int):
    """
    Async generator that polls for new telemetry every `poll_interval` seconds
    and yields SSE-formatted events.
    """
    asset_data = await asyncio.to_thread(_setup_sse_asset_sync, station_id, asset_number)
    if "error" in asset_data:
        yield f"event: error\ndata: {json.dumps({'detail': asset_data['error']})}\n\n"
        return

    last_seen_id = asset_data.get("initial_last_seen_id", 0)

    gateway_id = asset_data["gateway_id"]
    gw_stngw_id = asset_data["gw_stngw_id"]
    station_id = asset_data["station_id"]
    prefix = asset_data["prefix"]
    asset_type_hex = asset_data["asset_type_hex"]
    asset_type_name = asset_data["asset_type_name"]
    zone_code = asset_data.get("zone_code", "NR")
    division_code = asset_data.get("division_code", "")
    station_code = asset_data.get("station_code", "")

    yield ": ping\n\n"

    consecutive_errors = 0
    MAX_CONSECUTIVE_ERRORS = 5

    while True:
        if await request.is_disconnected():
            break

        try:
            result = await asyncio.to_thread(
                _poll_telemetry_sync,
                gateway_id=gateway_id,
                prefix=prefix,
                last_seen_id=last_seen_id,
                asset_type_hex=asset_type_hex,
                station_id=station_id,
                asset_type_name=asset_type_name,
                asset_number=asset_number,
                gw_stngw_id=gw_stngw_id,
                zone_code=zone_code,
                division_code=division_code,
                station_code=station_code,
            )
            
            consecutive_errors = 0

            for payload in result["payloads"]:
                yield f"data: {json.dumps(payload)}\n\n"
            
            last_seen_id = result["next_seen_id"]

        except Exception as e:
            consecutive_errors += 1
            yield f"event: error\ndata: {json.dumps({'detail': str(e)})}\n\n"
            if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                yield f"event: close\ndata: {json.dumps({'detail': 'Stream closed after repeated DB errors'})}\n\n"
                break
            
            backoff = min(poll_interval * (2 ** consecutive_errors), 60)
            await asyncio.sleep(backoff)
            continue

        await asyncio.sleep(poll_interval)


# ── Canonical RDSO SPN 257/2025 Annexure A Parameter Catalog ──
RDSO_SPEC_CATALOG = {
    "Point Machine": [
        {"code": "IPT N", "name": "Point Machine Current Normal", "pr_location": "Location Box", "unit": "A", "type_id": "00", "repr_id": "30", "alt_repr": ["0C", "01"], "min_safe": 0.8, "max_safe": 2.5, "min_fail": 0.3, "max_fail": None, "default_val": 1.85},
        {"code": "IPT R", "name": "Point Machine Current Reverse", "pr_location": "Location Box", "unit": "A", "type_id": "00", "repr_id": "31", "alt_repr": ["0D", "02"], "min_safe": 0.8, "max_safe": 2.5, "min_fail": 0.3, "max_fail": None, "default_val": 1.92},
        {"code": "VPT 110 DC LOC N", "name": "110V DC Loc Normal", "pr_location": "Location Box", "unit": "V", "type_id": "20", "repr_id": "20", "alt_repr": ["0A"], "min_safe": 90.0, "max_safe": 125.0, "min_fail": 82.0, "max_fail": 130.0, "default_val": 110.2},
        {"code": "VPT 110 DC LOC R", "name": "110V DC Loc Reverse", "pr_location": "Location Box", "unit": "V", "type_id": "20", "repr_id": "21", "alt_repr": ["0B"], "min_safe": 90.0, "max_safe": 125.0, "min_fail": 82.0, "max_fail": 130.0, "default_val": 110.0},
        {"code": "VPT 24 DC LOC N", "name": "24V DC Loc Normal", "pr_location": "Location Box", "unit": "V", "type_id": "20", "repr_id": "22", "alt_repr": [], "min_safe": 18.0, "max_safe": 27.0, "min_fail": 15.0, "max_fail": 30.0, "default_val": 24.1},
        {"code": "VPT 24 DC LOC R", "name": "24V DC Loc Reverse", "pr_location": "Location Box", "unit": "V", "type_id": "20", "repr_id": "23", "alt_repr": [], "min_safe": 18.0, "max_safe": 27.0, "min_fail": 15.0, "max_fail": 30.0, "default_val": 24.0},
        {"code": "VPT NWKR", "name": "NWKR Voltage", "pr_location": "Relay Room", "unit": "V", "type_id": "20", "repr_id": "00", "alt_repr": ["0E", "10"], "min_safe": 18.0, "max_safe": 27.0, "min_fail": 15.0, "max_fail": 30.0, "default_val": 24.1},
        {"code": "VPT RWKR", "name": "RWKR Voltage", "pr_location": "Relay Room", "unit": "V", "type_id": "20", "repr_id": "01", "alt_repr": ["0F", "11"], "min_safe": 18.0, "max_safe": 27.0, "min_fail": 15.0, "max_fail": 30.0, "default_val": 24.0},
        {"code": "TPT N", "name": "Normal Operation Time", "pr_location": "Location Box", "unit": "s", "type_id": "90", "repr_id": "60", "alt_repr": ["03"], "min_safe": 2.0, "max_safe": 4.5, "min_fail": None, "max_fail": 8.0, "default_val": 3.2},
        {"code": "TPT R", "name": "Reverse Operation Time", "pr_location": "Location Box", "unit": "s", "type_id": "90", "repr_id": "61", "alt_repr": [], "min_safe": 2.0, "max_safe": 4.5, "min_fail": None, "max_fail": 8.0, "default_val": 3.4},
        {"code": "NWKR", "name": "NWKR Digital Status", "pr_location": "Relay Room", "unit": "status", "type_id": "40", "repr_id": "10", "alt_repr": [], "default_val": 1},
        {"code": "RWKR", "name": "RWKR Digital Status", "pr_location": "Relay Room", "unit": "status", "type_id": "40", "repr_id": "11", "alt_repr": [], "default_val": 0},
        {"code": "NWCR", "name": "NWCR Digital Status", "pr_location": "Relay Room", "unit": "status", "type_id": "40", "repr_id": "12", "alt_repr": [], "default_val": 1},
        {"code": "RWCR", "name": "RWCR Digital Status", "pr_location": "Relay Room", "unit": "status", "type_id": "40", "repr_id": "13", "alt_repr": [], "default_val": 0},
    ],
    "DC Track Circuit": [
        {"code": "VTC TFC I/P", "name": "TFC Input Voltage", "pr_location": "Feed End", "unit": "V", "type_id": "30", "repr_id": "20", "alt_repr": ["01", "VTC TFC IP"], "min_safe": 90.0, "max_safe": 125.0, "min_fail": 85.0, "max_fail": 130.0, "default_val": 110.0},
        {"code": "VTC TFC O/P", "name": "TFC Output Voltage", "pr_location": "Feed End", "unit": "V", "type_id": "20", "repr_id": "21", "alt_repr": ["02"], "min_safe": 10.0, "max_safe": 14.0, "min_fail": 9.0, "max_fail": 15.0, "default_val": 12.3},
        {"code": "ITC TFC O/P", "name": "TFC Output Current", "pr_location": "Feed End", "unit": "mA", "type_id": "01", "repr_id": "22", "alt_repr": ["03"], "min_safe": 100.0, "max_safe": 5000.0, "min_fail": 50.0, "max_fail": 6000.0, "default_val": 650.0},
        {"code": "VTC CH FEED END", "name": "Feed End Choke Voltage", "pr_location": "Feed End", "unit": "V", "type_id": "20", "repr_id": "23", "alt_repr": [], "min_safe": 0.5, "max_safe": 2.0, "min_fail": 0.2, "max_fail": 3.0, "default_val": 1.1},
        {"code": "VTC FEED END", "name": "Track Feed End Voltage", "pr_location": "Feed End", "unit": "V", "type_id": "20", "repr_id": "24", "alt_repr": [], "min_safe": 1.0, "max_safe": 6.0, "min_fail": 0.5, "max_fail": 7.5, "default_val": 2.2},
        {"code": "ITC FEED END", "name": "Track Feed End Current", "pr_location": "Feed End", "unit": "mA", "type_id": "01", "repr_id": "25", "alt_repr": [], "min_safe": 250.0, "max_safe": 800.0, "min_fail": 100.0, "max_fail": 1000.0, "default_val": 420.0},
        {"code": "ITC BATT CHARG", "name": "Battery Charging Current", "pr_location": "Feed End", "unit": "mA", "type_id": "01", "repr_id": "26", "alt_repr": [], "min_safe": 50.0, "max_safe": 500.0, "min_fail": 20.0, "max_fail": 600.0, "default_val": 150.0},
        {"code": "ITC RELAY END", "name": "Relay End Current", "pr_location": "Relay End", "unit": "mA", "type_id": "01", "repr_id": "41", "alt_repr": ["0B"], "min_safe": 100.0, "max_safe": 210.0, "min_fail": 80.0, "max_fail": 250.0, "default_val": 160.0},
        {"code": "VTC TR", "name": "Track Relay Voltage", "pr_location": "Relay End", "unit": "V", "type_id": "20", "repr_id": "42", "alt_repr": ["0C"], "min_safe": 2.1, "max_safe": 4.2, "min_fail": 1.4, "max_fail": 5.0, "default_val": 2.8},
        {"code": "VTC 24 DC LOC", "name": "24V DC Loc", "pr_location": "Relay End", "unit": "V", "type_id": "20", "repr_id": "44", "alt_repr": ["0D"], "min_safe": 21.0, "max_safe": 27.0, "min_fail": 18.0, "max_fail": 30.0, "default_val": 24.2},
        {"code": "IBALST", "name": "Ballast/Sleeper Current", "pr_location": "Relay End", "unit": "mA", "type_id": "01", "repr_id": "45", "alt_repr": [], "min_safe": 0.0, "max_safe": 50.0, "min_fail": 0.0, "max_fail": 100.0, "default_val": 15.0},
        {"code": "RRAIL", "name": "Rail Resistance", "pr_location": "Relay End", "unit": "Ω", "type_id": "70", "repr_id": "46", "alt_repr": [], "min_safe": 0.5, "max_safe": 2.5, "min_fail": 0.2, "max_fail": 4.0, "default_val": 1.2},
        {"code": "TPR", "name": "TPR Digital Status", "pr_location": "Relay Room", "unit": "status", "type_id": "40", "repr_id": "10", "alt_repr": [], "default_val": 1},
    ],
    "Main Signal": [
        {"code": "VSIG DG", "name": "Green Aspect Voltage", "pr_location": "Location Box", "unit": "V", "type_id": "30", "repr_id": "30", "alt_repr": ["01"], "min_safe": 90.0, "max_safe": 125.0, "min_fail": 82.0, "max_fail": 130.0, "default_val": 110.0},
        {"code": "VSIG HG", "name": "Yellow Aspect Voltage", "pr_location": "Location Box", "unit": "V", "type_id": "30", "repr_id": "31", "alt_repr": ["02"], "min_safe": 90.0, "max_safe": 125.0, "min_fail": 82.0, "max_fail": 130.0, "default_val": 109.5},
        {"code": "VSIG HHG", "name": "Double Yellow Aspect Voltage", "pr_location": "Location Box", "unit": "V", "type_id": "30", "repr_id": "32", "alt_repr": ["03"], "min_safe": 90.0, "max_safe": 125.0, "min_fail": 82.0, "max_fail": 130.0, "default_val": 110.0},
        {"code": "VSIG RG", "name": "Red Aspect Voltage", "pr_location": "Location Box", "unit": "V", "type_id": "30", "repr_id": "33", "alt_repr": ["04"], "min_safe": 90.0, "max_safe": 125.0, "min_fail": 82.0, "max_fail": 130.0, "default_val": 110.5},
        {"code": "ISIG DG", "name": "Green Aspect Current", "pr_location": "Location Box", "unit": "mA", "type_id": "11", "repr_id": "40", "alt_repr": ["05"], "min_safe": 110.0, "max_safe": 150.0, "min_fail": 90.0, "max_fail": 170.0, "default_val": 130.0},
        {"code": "ISIG HG", "name": "Yellow Aspect Current", "pr_location": "Location Box", "unit": "mA", "type_id": "11", "repr_id": "41", "alt_repr": ["06"], "min_safe": 110.0, "max_safe": 150.0, "min_fail": 90.0, "max_fail": 170.0, "default_val": 128.0},
        {"code": "ISIG HHG", "name": "Double Yellow Aspect Current", "pr_location": "Location Box", "unit": "mA", "type_id": "11", "repr_id": "42", "alt_repr": ["07"], "min_safe": 110.0, "max_safe": 150.0, "min_fail": 90.0, "max_fail": 170.0, "default_val": 129.0},
        {"code": "ISIG RG", "name": "Red Aspect Current", "pr_location": "Location Box", "unit": "mA", "type_id": "11", "repr_id": "43", "alt_repr": ["08"], "min_safe": 110.0, "max_safe": 150.0, "min_fail": 90.0, "max_fail": 170.0, "default_val": 132.0},
        {"code": "VSIG HPR", "name": "HPR Voltage", "pr_location": "Location Box", "unit": "V", "type_id": "20", "repr_id": "21", "alt_repr": [], "min_safe": 21.0, "max_safe": 27.0, "min_fail": 18.0, "max_fail": 30.0, "default_val": 24.1},
        {"code": "VSIG HHPR", "name": "HHPR Voltage", "pr_location": "Location Box", "unit": "V", "type_id": "20", "repr_id": "22", "alt_repr": [], "min_safe": 21.0, "max_safe": 27.0, "min_fail": 18.0, "max_fail": 30.0, "default_val": 24.0},
        {"code": "VSIG DPR", "name": "DPR Voltage", "pr_location": "Location Box", "unit": "V", "type_id": "20", "repr_id": "20", "alt_repr": [], "min_safe": 21.0, "max_safe": 27.0, "min_fail": 18.0, "max_fail": 30.0, "default_val": 24.0},
        {"code": "DECR", "name": "DECR Digital Status", "pr_location": "Relay Room", "unit": "status", "type_id": "40", "repr_id": "02", "alt_repr": [], "default_val": 1},
        {"code": "HECR", "name": "HECR Digital Status", "pr_location": "Relay Room", "unit": "status", "type_id": "40", "repr_id": "00", "alt_repr": [], "default_val": 0},
        {"code": "RECR", "name": "RECR Digital Status", "pr_location": "Relay Room", "unit": "status", "type_id": "40", "repr_id": "01", "alt_repr": [], "default_val": 0},
    ],
    "Axle Counter": [
        {"code": "VAXCO EQ", "name": "Power Supply of Equipment", "pr_location": "Location Box", "unit": "V", "type_id": "20", "repr_id": "00", "alt_repr": [], "min_safe": 20.0, "max_safe": 28.0, "min_fail": 18.0, "max_fail": 30.0, "default_val": 24.0},
        {"code": "IAXCO EQ", "name": "Current of Equipment", "pr_location": "Location Box", "unit": "A", "type_id": "00", "repr_id": "10", "alt_repr": [], "min_safe": 0.5, "max_safe": 3.0, "min_fail": 0.2, "max_fail": 4.0, "default_val": 1.45},
        {"code": "VAXCO 24 DC LOC", "name": "24V DC to VPR after VR Pick Up", "pr_location": "Location Box", "unit": "V", "type_id": "20", "repr_id": "20", "alt_repr": [], "min_safe": 21.0, "max_safe": 27.0, "min_fail": 18.0, "max_fail": 30.0, "default_val": 24.2},
        {"code": "VAXCO 24 DC VPR", "name": "24V DC of VPR Relay", "pr_location": "Location Box", "unit": "V", "type_id": "20", "repr_id": "30", "alt_repr": [], "min_safe": 21.0, "max_safe": 27.0, "min_fail": 18.0, "max_fail": 30.0, "default_val": 23.9},
    ],
    "LC Gate": [
        {"code": "VELB-A DC", "name": "Motor Voltage ELB-A", "pr_location": "Gate Hut", "unit": "V", "type_id": "20", "repr_id": "20", "alt_repr": [], "min_safe": 20.0, "max_safe": 28.0, "min_fail": 18.0, "max_fail": 30.0, "default_val": 24.0},
        {"code": "IELB-A DC CLOSE", "name": "ELB-A Closing Current", "pr_location": "Gate Hut", "unit": "A", "type_id": "00", "repr_id": "30", "alt_repr": [], "min_safe": 1.0, "max_safe": 4.0, "min_fail": 0.5, "max_fail": 5.5, "default_val": 2.2},
        {"code": "IELB-A DC OPEN", "name": "ELB-A Opening Current", "pr_location": "Gate Hut", "unit": "A", "type_id": "00", "repr_id": "31", "alt_repr": [], "min_safe": 1.0, "max_safe": 4.0, "min_fail": 0.5, "max_fail": 5.5, "default_val": 2.1},
        {"code": "VELB-B DC", "name": "Motor Voltage ELB-B", "pr_location": "Gate Hut", "unit": "V", "type_id": "20", "repr_id": "21", "alt_repr": [], "min_safe": 20.0, "max_safe": 28.0, "min_fail": 18.0, "max_fail": 30.0, "default_val": 24.0},
        {"code": "IELB-B DC CLOSE", "name": "ELB-B Closing Current", "pr_location": "Gate Hut", "unit": "A", "type_id": "00", "repr_id": "32", "alt_repr": [], "min_safe": 1.0, "max_safe": 4.0, "min_fail": 0.5, "max_fail": 5.5, "default_val": 2.25},
        {"code": "IELB-B DC OPEN", "name": "ELB-B Opening Current", "pr_location": "Gate Hut", "unit": "A", "type_id": "00", "repr_id": "33", "alt_repr": [], "min_safe": 1.0, "max_safe": 4.0, "min_fail": 0.5, "max_fail": 5.5, "default_val": 2.15},
        {"code": "VELB FINAL SLOT", "name": "Final Relay Gate Closed & Locked", "pr_location": "Relay Room", "unit": "V", "type_id": "20", "repr_id": "60", "alt_repr": [], "min_safe": 21.0, "max_safe": 27.0, "min_fail": 18.0, "max_fail": 30.0, "default_val": 24.1},
    ],
    "IPS": [
        {"code": "VIPS IIP", "name": "IPS 220V AC Input", "pr_location": "IPS Room", "unit": "V", "type_id": "30", "repr_id": "01", "alt_repr": [], "min_safe": 190.0, "max_safe": 250.0, "min_fail": 160.0, "max_fail": 270.0, "default_val": 220.0},
        {"code": "VIPS 110 DC", "name": "IPS 110V DC Output", "pr_location": "IPS Room", "unit": "V", "type_id": "20", "repr_id": "00", "alt_repr": [], "min_safe": 99.0, "max_safe": 121.0, "min_fail": 88.0, "max_fail": 132.0, "default_val": 110.0},
        {"code": "VIPS SIG-1 110 AC", "name": "IPS 110 AC Signal", "pr_location": "IPS Room", "unit": "V", "type_id": "30", "repr_id": "10", "alt_repr": [], "min_safe": 99.0, "max_safe": 121.0, "min_fail": 88.0, "max_fail": 132.0, "default_val": 110.2},
        {"code": "VIPS TR-1 110 AC", "name": "IPS 110 AC Track", "pr_location": "IPS Room", "unit": "V", "type_id": "30", "repr_id": "20", "alt_repr": [], "min_safe": 99.0, "max_safe": 121.0, "min_fail": 88.0, "max_fail": 132.0, "default_val": 110.1},
        {"code": "VIPS SMR-1 110 DC", "name": "IPS SMR-1 110V DC", "pr_location": "IPS Room", "unit": "V", "type_id": "20", "repr_id": "30", "alt_repr": [], "min_safe": 99.0, "max_safe": 121.0, "min_fail": 88.0, "max_fail": 132.0, "default_val": 110.0},
        {"code": "IIPS BATT CHAR 110 DC", "name": "Battery Charging Current", "pr_location": "IPS Room", "unit": "A", "type_id": "00", "repr_id": "78", "alt_repr": [], "min_safe": 0.5, "max_safe": 30.0, "min_fail": 0.1, "max_fail": 40.0, "default_val": 8.5},
        {"code": "VIPS DC AXLE C", "name": "IPS DC-DC Axle Counter Voltage", "pr_location": "IPS Room", "unit": "V", "type_id": "20", "repr_id": "50", "alt_repr": [], "min_safe": 21.6, "max_safe": 26.4, "min_fail": 19.2, "max_fail": 28.8, "default_val": 24.0},
    ],
    "Equipment Room": [
        {"code": "TEMPRR", "name": "Temperature", "pr_location": "Relay Room", "unit": "°C", "type_id": "50", "repr_id": "01", "alt_repr": ["00"], "min_safe": 15.0, "max_safe": 35.0, "min_fail": 5.0, "max_fail": 45.0, "default_val": 26.5},
        {"code": "HUMDRR", "name": "Humidity", "pr_location": "Relay Room", "unit": "%", "type_id": "51", "repr_id": "02", "alt_repr": [], "min_safe": 30.0, "max_safe": 70.0, "min_fail": 10.0, "max_fail": 90.0, "default_val": 52.0},
        {"code": "DOORRR", "name": "Door Status", "pr_location": "Relay Room", "unit": "status", "type_id": "40", "repr_id": "00", "alt_repr": [], "default_val": 0},
    ],
}


def _get_display_asset_type_name(asset_type_hex: str, user_asset_type: Optional[str] = None) -> str:
    """Resolve asset_type_hex to user-friendly group name (e.g. 'Point Machine')"""
    if user_asset_type and user_asset_type in RDSO_SPEC_CATALOG:
        return user_asset_type
    
    # Check ASSET_TYPE_DISPLAY_GROUPS
    for group_name, hexes in ASSET_TYPE_DISPLAY_GROUPS.items():
        if asset_type_hex in hexes:
            if group_name in RDSO_SPEC_CATALOG:
                return group_name
            if "Track Circuit" in group_name:
                return "DC Track Circuit"
            if "Signal" in group_name:
                return "Main Signal"
            if "Axle" in group_name:
                return "Axle Counter"
            if "Gate" in group_name:
                return "LC Gate"
            if "IPS" in group_name:
                return "IPS"
    
    # Check equipment rooms
    if asset_type_hex and asset_type_hex.upper().startswith("F"):
        return "Equipment Room"
    
    return "Point Machine"


def _build_live_telemetry_response(
    db: Session,
    stn_ids: Optional[List[int]],
    eff_asset_no: Optional[str],
    asset_type: Optional[str],
    zone_code: Optional[str] = None,
    division_code: Optional[str] = None,
    station_code: Optional[str] = None,
) -> dict:
    """
    Build the complete Live Telemetry response per RDSO SPN 257/2025.
    Supports:
      - Mode A (user selected Zone, Division, Station, Asset Type - No Asset No.):
        Returns rows with: asset_no, parameter_name, parameter_code, pr_location, value, unit, status.
      - Mode B (user selected specific Asset No.):
        Returns rows with: parameter_name, parameter_code, pr_location, value, unit, status, timestamp.
    """
    asset_q = db.query(Asset)
    if stn_ids is not None:
        if stn_ids:
            asset_q = asset_q.filter(Asset.station_id.in_(stn_ids))

    if asset_type:
        asset_type_hexes = None
        if asset_type in ASSET_TYPE_DISPLAY_GROUPS:
            asset_type_hexes = ASSET_TYPE_DISPLAY_GROUPS[asset_type]
        else:
            at_master = db.query(AssetTypeMaster.asset_type_id).filter(
                or_(
                    AssetTypeMaster.asset_type_code == asset_type.upper(),
                    AssetTypeMaster.asset_type_name == asset_type
                )
            ).all()
            if at_master:
                asset_type_hexes = [r.asset_type_id for r in at_master]
            else:
                asset_type_hexes = [asset_type]
        if asset_type_hexes:
            asset_q = asset_q.filter(Asset.asset_type_hex.in_(asset_type_hexes))

    if eff_asset_no:
        asset_q = asset_q.filter(
            or_(
                Asset.asset_number_code == eff_asset_no,
                Asset.smms_asset_code == eff_asset_no
            )
        )

    assets = asset_q.order_by(Asset.id.asc()).limit(100).all()

    if eff_asset_no and not assets:
        raise HTTPException(
            status_code=404,
            detail=f"Asset '{eff_asset_no}' not found with the specified location/type filters"
        )

    # Resolve display locations
    sample_asset = assets[0] if assets else None
    resolved_zone = (
        sample_asset.station.division.zone.zone_code
        if sample_asset and sample_asset.station and sample_asset.station.division and sample_asset.station.division.zone
        else (zone_code or "NR")
    )
    resolved_div = (
        sample_asset.station.division.division_code
        if sample_asset and sample_asset.station and sample_asset.station.division
        else (division_code or "")
    )
    resolved_stn = (
        sample_asset.station.station_name
        if sample_asset and sample_asset.station
        else (station_code or "Station")
    )
    resolved_asset_type_name = (
        asset_type
        if asset_type
        else (_get_display_asset_type_name(sample_asset.asset_type_hex) if sample_asset else "Point Machine")
    )

    all_rows = []
    overall_status = "Healthy"
    legacy_live_data = []

    # Process each asset
    for asset in assets:
        cur_group = _get_display_asset_type_name(asset.asset_type_hex, asset_type)
        catalog_params = RDSO_SPEC_CATALOG.get(cur_group) or RDSO_SPEC_CATALOG["Point Machine"]

        gw = db.query(Gateway).filter(Gateway.stngw_id == asset.station_gateway_id).first()
        gw_id = gw.id if gw else None

        raw_telem = []
        if gw_id:
            an_h = asset.asset_number_id.upper() if asset.asset_number_id else "01"
            at_h = asset.asset_type_hex.upper() if asset.asset_type_hex else "00"
            p_prefix = f"{at_h}{an_h}"
            raw_telem = (
                db.query(Telemetry)
                .filter(Telemetry.gateway_id == gw_id, Telemetry.para_id.like(f"{p_prefix}%"))
                .order_by(Telemetry.id.desc())
                .limit(40)
                .all()
            )

        # Index telemetry by suffix
        telem_by_suffix: dict = {}
        for t in raw_telem:
            sfx = t.para_id[4:].upper()
            if sfx not in telem_by_suffix:
                telem_by_suffix[sfx] = t

        for param in catalog_params:
            matched_t = None
            target_sfx = f"{param['type_id']}{param['repr_id']}".upper()
            if target_sfx in telem_by_suffix:
                matched_t = telem_by_suffix[target_sfx]
            else:
                for alt in param.get("alt_repr", []):
                    # Check <type_id><alt> or 00<alt>
                    cand1 = f"{param['type_id']}{alt}".upper()
                    cand2 = f"00{alt}".upper()
                    if cand1 in telem_by_suffix:
                        matched_t = telem_by_suffix[cand1]
                        break
                    if cand2 in telem_by_suffix:
                        matched_t = telem_by_suffix[cand2]
                        break

            if matched_t:
                val = round(matched_t.prv, 2) if isinstance(matched_t.prv, float) else matched_t.prv
                ts = matched_t.prt or (matched_t.received_at.strftime("%H:%M:%S") if matched_t.received_at else datetime.now().strftime("%H:%M:%S"))
            else:
                val = param.get("default_val")
                ts = datetime.now().strftime("%H:%M:%S")

            # Status evaluation
            p_status = "Healthy"
            if isinstance(val, (int, float)):
                mf = param.get("min_fail")
                xf = param.get("max_fail")
                ms = param.get("min_safe")
                xs = param.get("max_safe")
                if (mf is not None and val < mf) or (xf is not None and val > xf):
                    p_status = "Failure"
                elif (ms is not None and val < ms) or (xs is not None and val > xs):
                    p_status = "Predictive"

            if p_status == "Failure":
                overall_status = "Failure"
            elif p_status == "Predictive" and overall_status != "Failure":
                overall_status = "Predictive"

            row_item = {
                "asset_no": asset.asset_number_code,
                "parameter_name": param["name"],
                "parameter_code": param["code"],
                "pr_location": asset.location or param["pr_location"],
                "value": val,
                "unit": param["unit"],
                "status": p_status,
                "timestamp": ts,
            }
            all_rows.append(row_item)

        # Build legacy live_data points for graph view if single asset
        if eff_asset_no and raw_telem:
            ts_groups: dict = {}
            for r in reversed(raw_telem):
                t_key = r.prt or (r.received_at.strftime("%H:%M") if r.received_at else "Now")
                if t_key not in ts_groups:
                    ts_groups[t_key] = []
                ts_groups[t_key].append(r)

            for t_key, t_rows in ts_groups.items():
                item = {
                    "time": t_key,
                    "I_avg": None, "Avg_Current": None,
                    "I_peak": None, "Peak_Current": None,
                    "V_batt": None, "Battery_Voltage": None,
                    "stroke_ms": None, "Stroke_Time": None,
                    "temp": None, "Temperature": None,
                }
                for r in t_rows:
                    field = _map_pid_to_field(r.para_id, item)
                    if field:
                        item[field] = r.prv
                        if field == "Avg_Current": item["I_avg"] = r.prv
                        elif field == "Peak_Current": item["I_peak"] = r.prv
                        elif field == "Battery_Voltage": item["V_batt"] = r.prv
                        elif field == "Stroke_Time": item["stroke_ms"] = r.prv
                        elif field == "Temperature": item["temp"] = r.prv
                legacy_live_data.append(item)

    return {
        "Zone": resolved_zone,
        "Division": resolved_div,
        "station_name": resolved_stn,
        "Asset_Type": resolved_asset_type_name,
        "Asset_No": eff_asset_no,
        "Status": overall_status,
        "rows": all_rows,
        "live_data": legacy_live_data,
        "total": len(all_rows),
        "page": 1,
        "page_size": len(all_rows) or 10,
        "total_pages": 1,
        "mode": "asset_specific" if eff_asset_no else "asset_type_summary",
    }


async def _sse_live_summary_generator(
    request: Request,
    stn_ids: Optional[List[int]],
    eff_asset_no: Optional[str],
    asset_type: Optional[str],
    poll_interval: int,
    zone_code: Optional[str],
    division_code: Optional[str],
    station_code: Optional[str],
):
    """
    SSE stream yielding live telemetry data packets periodically.
    """
    yield ": ping\n\n"
    while True:
        if await request.is_disconnected():
            break
        try:
            def _fetch():
                db = SessionLocal()
                try:
                    return _build_live_telemetry_response(
                        db, stn_ids, eff_asset_no, asset_type, zone_code, division_code, station_code
                    )
                finally:
                    db.close()

            data = await asyncio.to_thread(_fetch)
            yield f"data: {json.dumps(data)}\n\n"
        except Exception as e:
            yield f"event: error\ndata: {json.dumps({'detail': str(e)})}\n\n"
        await asyncio.sleep(poll_interval)


@router.get("/live")
async def live_telemetry_stream(
    request: Request,
    station_id: Optional[int] = Query(None),
    station_code: Optional[str] = Query(None),
    zone_code: Optional[str] = Query(None),
    division_code: Optional[str] = Query(None),
    asset_type: Optional[str] = Query(None),
    asset_no: Optional[str] = Query(None, description="Asset number code, e.g. 'PT-103' (Optional)"),
    poll_interval: int = Query(5, ge=1, le=60, description="Polling interval in seconds (1–60)"),
    db: Session = Depends(get_db),
):
    """
    Live Telemetry Endpoint per RDSO/SPN/257/2025.
    Supports:
      - Mode A (Filter: Zone + Division + Station + Asset Type, without asset_no):
        Returns all assets with dynamic parameter rows: Asset No, Parameter Name, Parameter Code, PR Location, Live Value, Unit, Status.
      - Mode B (Filter: Specific asset_no):
        Returns parameter rows with: Parameter Name, Parameter Code, PR Location, Live Value, Unit, Status, Timestamp.
      - EventSource SSE streaming when Accept: text/event-stream.
    """
    clean_no = asset_no.strip() if asset_no and asset_no.strip().lower() not in ("null", "undefined", "") else None
    raw_asset_number = request.query_params.get("asset_number")
    clean_number = raw_asset_number.strip() if raw_asset_number and raw_asset_number.strip().lower() not in ("null", "undefined", "") else None
    eff_asset_no = clean_no or clean_number

    stn_ids = _resolve_station_ids_by_codes(
        db, zone_code=zone_code, division_code=division_code,
        station_code=station_code, station_id=station_id
    )

    accept_header = request.headers.get("accept", "")
    if "text/event-stream" in accept_header:
        return StreamingResponse(
            _sse_live_summary_generator(
                request, stn_ids, eff_asset_no, asset_type, poll_interval,
                zone_code, division_code, station_code
            ),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    # Standard JSON response
    data = _build_live_telemetry_response(
        db, stn_ids, eff_asset_no, asset_type, zone_code, division_code, station_code
    )
    return {
        "status": True,
        "message": "Success",
        "data": data,
    }


# ── Telemetry History ─────────────────────────────────────────────────────────

def _fetch_history_data(
    db: Session,
    station_id: Optional[int],
    station_code: Optional[str],
    zone_code: Optional[str],
    division_code: Optional[str],
    asset_type: Optional[str],
    asset_no: Optional[str],
    asset_number_hex: Optional[str],
    parameter_type: Optional[str],
    parameter_type_hex: Optional[str],
    from_time: Optional[datetime] = None,
    to_time: Optional[datetime] = None,
    limit: int = 50000,
):
    """
    Shared data-fetch logic for history table and CSV download.
    Returns (gateway_map, grouped_rows).
    """
    # 1. Resolve Station IDs
    station_ids = _resolve_station_ids_by_codes(
        db, zone_code=zone_code, division_code=division_code,
        station_code=station_code, station_id=station_id
    )

    # 2. Resolve Asset Type Hexes
    asset_type_hexes = None
    if asset_type:
        if asset_type in ASSET_TYPE_DISPLAY_GROUPS:
            asset_type_hexes = ASSET_TYPE_DISPLAY_GROUPS[asset_type]
        else:
            at_master = db.query(AssetTypeMaster.asset_type_id).filter(
                or_(
                    AssetTypeMaster.asset_type_code == asset_type.upper(),
                    AssetTypeMaster.asset_type_name == asset_type
                )
            ).all()
            if at_master:
                asset_type_hexes = [r.asset_type_id for r in at_master]
            else:
                asset_type_hexes = [asset_type]

    # 3. Resolve Asset Number Hexes
    target_asset_number_hexes = None
    eff_no = asset_no or asset_number_hex
    if eff_no:
        asset_q = db.query(Asset.asset_number_id)
        if station_ids:
            asset_q = asset_q.filter(Asset.station_id.in_(station_ids))
        if asset_type_hexes:
            asset_q = asset_q.filter(Asset.asset_type_hex.in_(asset_type_hexes))
        
        rows = asset_q.filter(
            or_(
                Asset.asset_number_code == eff_no,
                Asset.smms_asset_code == eff_no
            )
        ).all()
        if rows:
            target_asset_number_hexes = [r.asset_number_id.upper() for r in rows]
        else:
            target_asset_number_hexes = [eff_no.upper()]

    # 4. Resolve Parameter Type Hexes
    target_parameter_type_hexes = None
    eff_pt = parameter_type or parameter_type_hex
    if eff_pt:
        hexes = []
        for hex_id, (code, name, unit) in PARAMETER_TYPE_MAP.items():
            if eff_pt.upper() in (hex_id.upper(), code.upper(), name.upper()):
                hexes.append(hex_id.upper())
        if hexes:
            target_parameter_type_hexes = hexes
        else:
            target_parameter_type_hexes = [eff_pt.upper()]

    # Query gateways
    gw_query = db.query(Gateway)
    if station_ids is not None:
        if not station_ids:
            return {}, {}
        gw_query = gw_query.filter(Gateway.station_id.in_(station_ids))

    gateways = gw_query.all()
    if not gateways:
        return {}, {}

    gateway_ids = [g.id for g in gateways]
    gateway_map = {g.id: g for g in gateways}

    # Fetch telemetry
    telem_filter = [
        Telemetry.gateway_id.in_(gateway_ids),
    ]
    if from_time is not None:
        telem_filter.append(Telemetry.received_at >= from_time)
    if to_time is not None:
        telem_filter.append(Telemetry.received_at <= to_time)

    if asset_type_hexes and len(asset_type_hexes) == 1:
        at_h = asset_type_hexes[0]
        if target_asset_number_hexes and len(target_asset_number_hexes) == 1:
            an_h = target_asset_number_hexes[0]
            if target_parameter_type_hexes and len(target_parameter_type_hexes) == 1:
                pt_h = target_parameter_type_hexes[0]
                telem_filter.append(Telemetry.para_id.like(f"{at_h}{an_h}{pt_h}%"))
            else:
                telem_filter.append(Telemetry.para_id.like(f"{at_h}{an_h}%"))
        else:
            telem_filter.append(Telemetry.para_id.like(f"{at_h}%"))

    rows_all = (
        db.query(Telemetry)
        .filter(*telem_filter)
        .order_by(Telemetry.received_at.desc())
        .limit(limit)
        .all()
    )

    grouped: dict[tuple, list] = {}
    for row in rows_all:
        pid = row.para_id
        if len(pid) != 8:
            continue
        at_hex = pid[0:2]
        an_hex = pid[2:4]
        pt_hex = pid[4:6]

        if asset_type_hexes and at_hex not in asset_type_hexes:
            continue
        if target_asset_number_hexes and an_hex not in target_asset_number_hexes:
            continue
        if target_parameter_type_hexes and pt_hex not in target_parameter_type_hexes:
            continue

        key = (row.gateway_id, pid)
        grouped.setdefault(key, []).append(row)

    return gateway_map, grouped


def _resolve_telemetry_param(pid: str) -> tuple[str, str, str, str]:
    """
    Resolve (parameter_name, unit, parameter_type_hex, parameter_code) from a para_id.
    Prioritizes RDSO_SPEC_CATALOG canonical definitions, then dual-mode resolver.
    """
    if not pid or len(pid) < 8:
        return ("Unknown", "", "00", "UNKNOWN")

    at_hex = pid[0:2].upper()
    pt_hex = pid[4:6].upper()
    repr_hex = pid[6:8].upper()

    group_name = None
    if at_hex == "00":
        group_name = "Point Machine"
    elif at_hex == "20":
        group_name = "DC Track Circuit"
    elif at_hex == "10":
        group_name = "Main Signal"
    elif at_hex == "30":
        group_name = "Axle Counter"
    elif at_hex == "40":
        group_name = "LC Gate"
    elif at_hex == "50":
        group_name = "IPS"
    elif at_hex in ("60", "F0", "F1", "F2", "F3"):
        group_name = "Equipment Room"

    if group_name and group_name in RDSO_SPEC_CATALOG:
        for spec in RDSO_SPEC_CATALOG[group_name]:
            if spec.get("type_id") == pt_hex:
                if spec.get("repr_id") == repr_hex or repr_hex in spec.get("alt_repr", []):
                    return (spec["name"], spec["unit"], pt_hex, spec["code"])

    # Legacy Point Machine compatibility mapping (drops AVG_CUR, PEAK_CUR, STK_TIME, BAT_VOLT)
    if at_hex == "00":
        legacy_pm_map = {
            "01": "IPT N",
            "02": "IPT R",
            "03": "TPT N",
            "04": "VPT 110 DC LOC N",
            "05": "VPT NWKR",
        }
        if pt_hex in legacy_pm_map:
            target_code = legacy_pm_map[pt_hex]
            for spec in RDSO_SPEC_CATALOG["Point Machine"]:
                if spec["code"] == target_code:
                    return (spec["name"], spec["unit"], spec.get("type_id", "00"), spec["code"])

    # 1. Dual-mode resolver (RDSO canonical preferred)
    dual = _resolve_parameter_dual_mode(pid)
    if dual["primary_name"] and not dual["primary_name"].startswith("PARAM_"):
        prim = dual["primary_name"]
        if at_hex == "00":
            legacy_alias_map = {
                "AVG_CUR": "IPT N",
                "PEAK_CUR": "IPT R",
                "STK_TIME": "TPT N",
                "BAT_VOLT": "VPT 110 DC LOC N",
                "MOT_TEMP": "VPT NWKR",
            }
            if prim in legacy_alias_map:
                target_code = legacy_alias_map[prim]
                for spec in RDSO_SPEC_CATALOG["Point Machine"]:
                    if spec["code"] == target_code:
                        return (spec["name"], spec["unit"], spec.get("type_id", "00"), spec["code"])
        return (dual["display_name"], dual["unit"], pt_hex, dual["primary_name"])

    # 2. parameter_config_service fallback
    try:
        cfg = param_config_service.get_parameter_config(pid)
        if cfg and cfg.parameter_representation_name:
            return (
                cfg.parameter_representation_name,
                cfg.unit or "",
                cfg.parameter_type_id or pt_hex,
                cfg.parameter_type_code or f"PARAM_{pid[4:]}",
            )
    except Exception:
        pass

    # 3. Legacy alias fallback
    if dual["legacy_display"]:
        return (dual["legacy_display"], dual["unit"], pt_hex, dual.get("legacy_key") or f"PARAM_{pid[4:]}")

    # 4. Constants catalog fallback
    if pt_hex in ASSET_PARAMETER_CATALOG:
        entry = ASSET_PARAMETER_CATALOG[pt_hex]
        return (entry[1], entry[2] or "", pt_hex, entry[0])
    if pt_hex in GENERIC_PARAMETER_TYPE_MAP:
        entry = GENERIC_PARAMETER_TYPE_MAP[pt_hex]
        return (entry[1], entry[2] or "", pt_hex, entry[0])

    return (f"Param_{pid[4:]}", "", pt_hex, f"PARAM_{pid[4:]}")


def _get_default_catalog_columns(
    db: Session,
    asset_type: str,
    station_id: Optional[int],
) -> list[TelemetryHistoryColumn]:
    cols = []
    group_name = _get_display_asset_type_name("", asset_type)
    if group_name not in RDSO_SPEC_CATALOG:
        group_name = "Point Machine"
    
    at_hex = "00"
    for hex_id, grp in [("00", "Point Machine"), ("20", "DC Track Circuit"), ("10", "Main Signal"), ("30", "Axle Counter"), ("40", "LC Gate"), ("50", "IPS"), ("60", "Equipment Room")]:
        if grp == group_name:
            at_hex = hex_id
            break

    for spec in RDSO_SPEC_CATALOG.get(group_name, []):
        pt_hex = spec.get("type_id", "00")
        threshold = _get_threshold(db, at_hex, pt_hex, station_id)
        cols.append(
            TelemetryHistoryColumn(
                key=spec["code"],
                parameter_name=spec["name"],
                parameter_code=spec["code"],
                parameter_unit=spec["unit"],
                parameter_type_hex=pt_hex,
                threshold_warning_low=threshold.warning_low if threshold else spec.get("min_safe"),
                threshold_warning_high=threshold.warning_high if threshold else spec.get("max_safe"),
                threshold_critical_low=threshold.critical_low if threshold else spec.get("min_fail"),
                threshold_critical_high=threshold.critical_high if threshold else spec.get("max_fail"),
            )
        )
    return cols


def _build_history_columns_and_rows(
    db: Session,
    gateway_map: dict,
    grouped: dict,
    station_id: Optional[int],
    asset_type: Optional[str] = None,
    zone_code: Optional[str] = None,
    division_code: Optional[str] = None,
    station_name: Optional[str] = None,
) -> tuple[list[TelemetryHistoryColumn], list[TelemetryHistoryRow]]:
    """
    Pivot grouped telemetry into history table columns and rows with dynamic RDSO parameters,
    attaching canonical location and vendor information per Annexure F §3.
    """
    col_map: dict[str, TelemetryHistoryColumn] = {}
    pid_to_col: dict[str, str] = {}

    if asset_type:
        default_cols = _get_default_catalog_columns(db, asset_type, station_id)
        for dc in default_cols:
            col_map[dc.key] = dc

    for (gw_id, pid) in grouped:
        p_name, p_unit, pt_hex, p_code = _resolve_telemetry_param(pid)
        col_key = p_code
        pid_to_col[pid] = col_key

        if col_key not in col_map:
            gw = gateway_map.get(gw_id)
            at_hex = pid[0:2]
            gw_station_id = (gw.station_id if gw else None) or station_id
            threshold = _get_threshold(db, at_hex, pt_hex, gw_station_id)

            col_map[col_key] = TelemetryHistoryColumn(
                key=col_key,
                parameter_name=p_name,
                parameter_code=p_code,
                parameter_unit=p_unit,
                parameter_type_hex=pt_hex,
                threshold_warning_low=threshold.warning_low if threshold else None,
                threshold_warning_high=threshold.warning_high if threshold else None,
                threshold_critical_low=threshold.critical_low if threshold else None,
                threshold_critical_high=threshold.critical_high if threshold else None,
            )

    group_name = _get_display_asset_type_name("", asset_type)
    catalog_codes = [s["code"] for s in RDSO_SPEC_CATALOG.get(group_name, [])]
    catalog_order = {code: i for i, code in enumerate(catalog_codes)}
    columns = sorted(
        col_map.values(),
        key=lambda c: (
            catalog_order.get(c.parameter_code or c.key, 999),
            c.parameter_type_hex,
            c.parameter_code or c.key,
        )
    )

    # Pre-fetch asset info and vendor mapping
    asset_info_map: dict[str, dict] = {}
    stn_obj = None
    if station_id:
        stn_obj = db.query(Station).filter(Station.id == station_id).first()
        assets_in_stn = (
            db.query(
                Asset.asset_number_id,
                Asset.asset_number_code,
                Asset.vendor_code,
                Asset.make,
            )
            .filter(Asset.station_id == station_id)
            .all()
        )
        for aid, acode, vcode, amake in assets_in_stn:
            if aid:
                asset_info_map[aid.upper()] = {
                    "asset_no": acode,
                    "vendor_code": vcode or "XYZ",
                    "make": amake,
                }
    else:
        gw_ids = list(gateway_map.keys())
        if gw_ids:
            gws_stngw = [g.stngw_id for g in gateway_map.values() if g and g.stngw_id]
            assets_found = (
                db.query(
                    Asset.asset_number_id,
                    Asset.asset_number_code,
                    Asset.vendor_code,
                    Asset.make,
                )
                .filter(Asset.station_gateway_id.in_(gws_stngw))
                .all()
            )
            for aid, acode, vcode, amake in assets_found:
                if aid:
                    asset_info_map[aid.upper()] = {
                        "asset_no": acode,
                        "vendor_code": vcode or "XYZ",
                        "make": amake,
                    }

    res_zone = zone_code or (stn_obj.division.zone.zone_code if stn_obj and stn_obj.division and stn_obj.division.zone else "NR")
    res_div = division_code or (stn_obj.division.division_code if stn_obj and stn_obj.division else "")
    res_stn = station_name or (stn_obj.station_name if stn_obj else (stn_obj.station_code if stn_obj else ""))

    row_index: dict[tuple, dict] = {}

    for (gw_id, pid), telem_rows in grouped.items():
        if pid not in pid_to_col:
            continue
        col_key = pid_to_col[pid]
        p_name, p_unit, pt_hex, p_code = _resolve_telemetry_param(pid)
        gw = gateway_map.get(gw_id)
        stngw_id = gw.stngw_id if gw else ""
        an_hex = pid[2:4]
        
        ainfo = asset_info_map.get(an_hex.upper(), {})
        asset_label = ainfo.get("asset_no") or f"Asset-{an_hex}"
        vendor_val = ainfo.get("vendor_code") or "XYZ"

        for row in telem_rows:
            row_dt = None
            if row.prt:
                parsed_prt = _parse_telemetry_datetime(row.prt, None)
                if parsed_prt:
                    if row.received_at and ":" in row.prt and len(row.prt.strip()) <= 8:
                        row_dt = datetime.combine(row.received_at.date(), parsed_prt.time())
                    else:
                        row_dt = parsed_prt
            if not row_dt and row.received_at:
                row_dt = row.received_at
            if not row_dt:
                row_dt = datetime.utcnow()

            display_ts = row_dt.strftime("%Y-%m-%d %H:%M:%S")
            index_key = (display_ts, an_hex, stngw_id, row_dt, asset_label, vendor_val)
            if index_key not in row_index:
                row_index[index_key] = {
                    "asset_no": asset_label,
                    "vendor_name": vendor_val,
                    "vendor_code": vendor_val,
                    "zone": res_zone,
                    "division": res_div,
                    "station": res_stn,
                    "asset_type": asset_type or "Point Machine",
                }
            row_index[index_key][col_key] = row.prv
            row_index[index_key][p_name] = row.prv
            if p_unit:
                row_index[index_key][f"{p_name} ({p_unit})"] = row.prv

    history_rows = [
        TelemetryHistoryRow(
            timestamp=display_ts,
            asset_number_hex=an_hex,
            stngw_id=stngw_id,
            values=vals,
            zone=vals.get("zone", res_zone),
            division=vals.get("division", res_div),
            station=vals.get("station", res_stn),
            vendor_name=vals.get("vendor_name", vendor_val),
            asset_type=vals.get("asset_type", asset_type or "Point Machine"),
            asset_no=vals.get("asset_no", asset_label),
        )
        for (display_ts, an_hex, stngw_id, row_dt, asset_label, vendor_val), vals in sorted(
            row_index.items(), key=lambda x: x[0][3], reverse=True
        )
    ]

    return columns, history_rows


@router.get("/history", response_model=StandardResponse[TelemetryHistoryResponse])
def get_telemetry_history(
    station_id:       Optional[int]      = Query(None),
    station_code:     Optional[str]      = Query(None, description="Station code, e.g. 'LKO'"),
    zone_code:        Optional[str]      = Query(None, description="Zone code, e.g. 'NR'"),
    division_code:    Optional[str]      = Query(None, description="Division code, e.g. 'LKO'"),
    asset_type:       Optional[str]      = Query(None, description="Asset type name or display group name"),
    asset_no:         Optional[str]      = Query(None, description="Asset number code, e.g. 'PT-101'"),
    asset_number_hex: Optional[str]      = Query(None, description="Asset number hex, e.g. '01'"),
    parameter_type:   Optional[str]      = Query(None, description="Parameter type name or code"),
    parameter_type_hex: Optional[str]    = Query(None, description="Filter to one parameter type hex"),
    from_date:        Optional[str]      = Query(None, description="Start date DD/MM/YYYY or YYYY-MM-DD"),
    from_time:        Optional[str]      = Query(None, description="Start time HH:MM:SS or ISO string"),
    to_date:          Optional[str]      = Query(None, description="End date DD/MM/YYYY or YYYY-MM-DD"),
    to_time:          Optional[str]      = Query(None, description="End time HH:MM:SS or ISO string"),
    page:             int                = Query(1, ge=1),
    page_size:        int                = Query(50, ge=1, le=500),
    db:               Session            = Depends(get_db),
):
    """
    Telemetry History — paginated, pivoted table rows with dynamic RDSO parameter columns.
    """
    eff_from_dt = None
    eff_to_dt = None
    
    if from_date:
        if from_time:
            if ":" in from_time and "T" not in from_time:
                eff_from_dt = _parse_telemetry_datetime(f"{from_date} {from_time}", None)
            else:
                eff_from_dt = _parse_telemetry_datetime(from_time, None)
        else:
            eff_from_dt = _parse_telemetry_datetime(from_date, None)
    elif from_time:
        eff_from_dt = _parse_telemetry_datetime(from_time, None)

    if to_date:
        if to_time:
            if ":" in to_time and "T" not in to_time:
                eff_to_dt = _parse_telemetry_datetime(f"{to_date} {to_time}", None)
            else:
                eff_to_dt = _parse_telemetry_datetime(to_time, None)
        else:
            parsed_date = _parse_telemetry_datetime(to_date, None)
            if parsed_date:
                eff_to_dt = datetime.combine(parsed_date.date(), datetime.max.time())
    elif to_time:
        eff_to_dt = _parse_telemetry_datetime(to_time, None)

    gateway_map, grouped = _fetch_history_data(
        db=db,
        station_id=station_id,
        station_code=station_code,
        zone_code=zone_code,
        division_code=division_code,
        asset_type=asset_type,
        asset_no=asset_no,
        asset_number_hex=asset_number_hex,
        parameter_type=parameter_type,
        parameter_type_hex=parameter_type_hex,
        from_time=eff_from_dt,
        to_time=eff_to_dt,
    )

    resolved_zone = zone_code or "NR"
    resolved_div = division_code or ""
    resolved_stn_name = None
    eff_station_id = station_id

    stn = None
    if station_id:
        stn = db.query(Station).filter(Station.id == station_id).first()
    elif station_code:
        stn = db.query(Station).filter(Station.station_code == station_code.upper()).first()
        
    if stn:
        resolved_stn_name = stn.station_name
        eff_station_id = stn.id
        if stn.division:
            resolved_div = stn.division.division_code
            if stn.division.zone:
                resolved_zone = stn.division.zone.zone_code
    elif station_code:
        resolved_stn_name = station_code

    resolved_asset_type = asset_type or "Point Machine"
    if resolved_asset_type.upper() == "EOP":
        resolved_asset_type = "Point Machine"

    resolved_asset_no = asset_no or asset_number_hex or ""

    if not grouped:
        default_columns = _get_default_catalog_columns(db, resolved_asset_type, eff_station_id)
        empty_response = TelemetryHistoryResponse(
            Zone=resolved_zone,
            Division=resolved_div,
            Station=resolved_stn_name,
            Vendor="XYZ",
            Asset_Type=resolved_asset_type,
            Asset_No=resolved_asset_no,
            Time=eff_to_dt.strftime("%H:%M:%S") if eff_to_dt else datetime.now().strftime("%H:%M:%S"),
            Status="Predictive",
            live_data=[],
            station_id=eff_station_id,
            station_name=resolved_stn_name,
            asset_number=resolved_asset_no,
            from_time=eff_from_dt.isoformat() if eff_from_dt else None,
            to_time=eff_to_dt.isoformat() if eff_to_dt else None,
            columns=default_columns,
            total=0,
            page=page,
            page_size=page_size,
            total_pages=0,
            rows=[],
        )
        return {
            "status": True,
            "message": "Success",
            "data": empty_response
        }

    columns, all_rows = _build_history_columns_and_rows(
        db, gateway_map, grouped, eff_station_id, resolved_asset_type,
        zone_code=resolved_zone, division_code=resolved_div, station_name=resolved_stn_name
    )

    total = len(all_rows)
    total_pages = (total + page_size - 1) // page_size if total else 0
    offset = (page - 1) * page_size
    paginated_rows = all_rows[offset: offset + page_size]

    live_data_list = []
    for r in paginated_rows:
        row_item = {
            "time": r.timestamp,
            "timestamp": r.timestamp,
            "zone": r.zone or resolved_zone,
            "division": r.division or resolved_div,
            "station": r.station or resolved_stn_name or "",
            "vendor_name": r.vendor_name or "XYZ",
            "vendor_code": r.vendor_name or "XYZ",
            "asset_type": r.asset_type or resolved_asset_type,
            "asset_no": r.asset_no or r.values.get("asset_no") or r.asset_number_hex,
        }
        for k, v in r.values.items():
            row_item[k] = v
            clean_k = k.split("(")[0].strip().replace(" ", "_")
            row_item[clean_k] = v

        if "Point Machine" in resolved_asset_type or resolved_asset_type == "EOP":
            v_cur_n = row_item.get("IPT_N") or row_item.get("Normal_Current") or row_item.get("Avg_Current")
            if v_cur_n is not None:
                row_item["Normal_Current"] = v_cur_n
                row_item["Avg_Current"] = v_cur_n
                row_item["I_avg"] = v_cur_n
            v_cur_r = row_item.get("IPT_R") or row_item.get("Reverse_Current") or row_item.get("Peak_Current")
            if v_cur_r is not None:
                row_item["Reverse_Current"] = v_cur_r
                row_item["Peak_Current"] = v_cur_r
                row_item["I_peak"] = v_cur_r
            v_volt = row_item.get("VPT_110_DC_LOC_N") or row_item.get("VPT_24_DC_LOC") or row_item.get("Voltage_DC") or row_item.get("Battery_Voltage")
            if v_volt is not None:
                row_item["Voltage_DC"] = v_volt
                row_item["Battery_Voltage"] = v_volt
                row_item["V_batt"] = v_volt
            v_stroke = row_item.get("TOPT_N") or row_item.get("TOPT_R") or row_item.get("TPT_N") or row_item.get("Stroke_Time")
            if v_stroke is not None:
                row_item["Stroke_Time"] = v_stroke
                row_item["stroke_ms"] = v_stroke
            v_temp = row_item.get("TEMP_PT") or row_item.get("Temperature") or row_item.get("Motor_Temperature")
            if v_temp is not None:
                row_item["Temperature"] = v_temp
                row_item["Motor_Temperature"] = v_temp
                row_item["temp"] = v_temp

        live_data_list.append(row_item)

    response_data = TelemetryHistoryResponse(
        Zone=resolved_zone,
        Division=resolved_div,
        Station=resolved_stn_name,
        Vendor="XYZ",
        Asset_Type=resolved_asset_type,
        Asset_No=resolved_asset_no,
        Time=datetime.now().strftime("%H:%M:%S"),
        Status="Predictive",
        live_data=live_data_list,
        station_id=eff_station_id,
        station_name=resolved_stn_name,
        asset_number=resolved_asset_no,
        from_time=eff_from_dt.isoformat() if eff_from_dt else None,
        to_time=eff_to_dt.isoformat() if eff_to_dt else None,
        columns=columns,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
        rows=paginated_rows,
    )
    return {
        "status": True,
        "message": "Success",
        "data": response_data
    }


@router.get("/history/download")
def download_telemetry_history(
    station_id:       Optional[int]      = Query(None),
    station_code:     Optional[str]      = Query(None, description="Station code, e.g. 'LKO'"),
    zone_code:        Optional[str]      = Query(None, description="Zone code, e.g. 'NR'"),
    division_code:    Optional[str]      = Query(None, description="Division code, e.g. 'LKO'"),
    asset_type:       Optional[str]      = Query(None, description="Asset type name or display group name"),
    asset_no:         Optional[str]      = Query(None, description="Asset number code, e.g. 'PT-101'"),
    asset_number_hex: Optional[str]      = Query(None, description="Asset number hex, e.g. '01'"),
    parameter_type:   Optional[str]      = Query(None, description="Parameter type name or code"),
    parameter_type_hex: Optional[str]    = Query(None, description="Filter to one parameter type hex"),
    from_date:        Optional[str]      = Query(None, description="Start date DD/MM/YYYY or YYYY-MM-DD"),
    from_time:        Optional[str]      = Query(None, description="Start time HH:MM:SS or ISO string"),
    to_date:          Optional[str]      = Query(None, description="End date DD/MM/YYYY or YYYY-MM-DD"),
    to_time:          Optional[str]      = Query(None, description="End time HH:MM:SS or ISO string"),
    db:               Session            = Depends(get_db),
):
    """
    Download Telemetry History as CSV with dynamic parameter headers.
    """
    from datetime import date as date_type
    
    eff_from_dt = None
    eff_to_dt = None
    
    if from_date:
        if from_time:
            if ":" in from_time and "T" not in from_time:
                eff_from_dt = _parse_telemetry_datetime(f"{from_date} {from_time}", None)
            else:
                eff_from_dt = _parse_telemetry_datetime(from_time, None)
        else:
            eff_from_dt = _parse_telemetry_datetime(from_date, None)
    elif from_time:
        eff_from_dt = _parse_telemetry_datetime(from_time, None)

    if to_date:
        if to_time:
            if ":" in to_time and "T" not in to_time:
                eff_to_dt = _parse_telemetry_datetime(f"{to_date} {to_time}", None)
            else:
                eff_to_dt = _parse_telemetry_datetime(to_time, None)
        else:
            parsed_date = _parse_telemetry_datetime(to_date, None)
            if parsed_date:
                eff_to_dt = datetime.combine(parsed_date.date(), datetime.max.time())
    elif to_time:
        eff_to_dt = _parse_telemetry_datetime(to_time, None)

    gateway_map, grouped = _fetch_history_data(
        db=db,
        station_id=station_id,
        station_code=station_code,
        zone_code=zone_code,
        division_code=division_code,
        asset_type=asset_type,
        asset_no=asset_no,
        asset_number_hex=asset_number_hex,
        parameter_type=parameter_type,
        parameter_type_hex=parameter_type_hex,
        from_time=eff_from_dt,
        to_time=eff_to_dt,
        limit=20000,
    )

    eff_station_id = station_id
    stn = None
    if eff_station_id:
        stn = db.query(Station).filter(Station.id == eff_station_id).first()
    elif station_code:
        stn = db.query(Station).filter(Station.station_code == station_code.upper()).first()

    resolved_zone = zone_code or "NR"
    resolved_div = division_code or ""
    resolved_stn_name = station_code or ""
    if stn:
        resolved_stn_name = stn.station_name
        eff_station_id = stn.id
        if stn.division:
            resolved_div = stn.division.division_code
            if stn.division.zone:
                resolved_zone = stn.division.zone.zone_code

    resolved_asset_type = asset_type or "Point Machine"
    columns, all_rows = _build_history_columns_and_rows(
        db, gateway_map, grouped, eff_station_id, resolved_asset_type,
        zone_code=resolved_zone, division_code=resolved_div, station_name=resolved_stn_name
    )

    output = io.StringIO()
    writer = csv.writer(output)

    # Header row with canonical Annexure F §3 columns + dynamic parameter headers
    header_titles = []
    for c in columns:
        u = (c.parameter_unit or "").strip()
        has_unit = u and u not in ("—", "-", "status")
        if c.parameter_code and c.parameter_code != c.parameter_name:
            if has_unit:
                header_titles.append(f"{c.parameter_name} [{c.parameter_code}] ({u})")
            else:
                header_titles.append(f"{c.parameter_name} [{c.parameter_code}]")
        else:
            if has_unit:
                header_titles.append(f"{c.parameter_name} ({u})")
            else:
                header_titles.append(f"{c.parameter_name}")

    writer.writerow([
        "ZONE",
        "DIVISION",
        "STATION",
        "VENDOR NAME",
        "ASSET TYPE",
        "ASSET NUMBER",
        "DATE & TIME"
    ] + header_titles)

    for row in all_rows:
        writer.writerow(
            [
                row.zone or resolved_zone,
                row.division or resolved_div,
                row.station or resolved_stn_name or "",
                row.vendor_name or "XYZ",
                row.asset_type or resolved_asset_type,
                row.asset_no or row.values.get("asset_no") or row.asset_number_hex,
                row.timestamp,
            ]
            + [row.values.get(c.parameter_code, row.values.get(c.key, "")) for c in columns]
        )

    output.seek(0)
    filename = f"telemetry_history_{date_type.today().isoformat()}.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/summary", response_model=StandardResponse[TelemetrySummaryResponse])
def get_telemetry_summary(
    station_id:       Optional[int]      = Query(None),
    station_code:     Optional[str]      = Query(None, description="Station code, e.g. 'LKO'"),
    zone_code:        Optional[str]      = Query(None, description="Zone code, e.g. 'NR'"),
    division_code:    Optional[str]      = Query(None, description="Division code, e.g. 'LKO'"),
    asset_type:       Optional[str]      = Query(None, description="Asset type name or display group name"),
    asset_no:         Optional[str]      = Query(None, description="Asset number code, e.g. 'PT-101'"),
    from_date:        Optional[str]      = Query(None, description="Start date DD/MM/YYYY or YYYY-MM-DD"),
    from_time:        Optional[str]      = Query(None, description="Start time HH:MM:SS or ISO string"),
    to_date:          Optional[str]      = Query(None, description="End date DD/MM/YYYY or YYYY-MM-DD"),
    to_time:          Optional[str]      = Query(None, description="End time HH:MM:SS or ISO string"),
    page:             int                = Query(1, ge=1),
    page_size:        int                = Query(50, ge=1, le=500),
    db:               Session            = Depends(get_db),
):
    """
    Telemetry Summary — statistical aggregates (min, max, avg, samples, availability, excursions)
    grouped by Station, Asset, and Parameter.
    """
    now = datetime.now()
    eff_from_dt = None
    eff_to_dt = None

    if from_date:
        if from_time:
            if ":" in from_time and "T" not in from_time:
                eff_from_dt = _parse_telemetry_datetime(f"{from_date} {from_time}", None)
            else:
                eff_from_dt = _parse_telemetry_datetime(from_time, None)
        else:
            eff_from_dt = _parse_telemetry_datetime(from_date, None)
    elif from_time:
        eff_from_dt = _parse_telemetry_datetime(from_time, None)

    if to_date:
        if to_time:
            if ":" in to_time and "T" not in to_time:
                eff_to_dt = _parse_telemetry_datetime(f"{to_date} {to_time}", None)
            else:
                eff_to_dt = _parse_telemetry_datetime(to_time, None)
        else:
            parsed_date = _parse_telemetry_datetime(to_date, None)
            if parsed_date:
                eff_to_dt = datetime.combine(parsed_date.date(), datetime.max.time())
    elif to_time:
        eff_to_dt = _parse_telemetry_datetime(to_time, None)

    # Default to 24h window if not specified
    if not eff_from_dt and not eff_to_dt:
        eff_from_dt = now - timedelta(hours=24)
        eff_to_dt = now

    gateway_map, grouped = _fetch_history_data(
        db=db,
        station_id=station_id,
        station_code=station_code,
        zone_code=zone_code,
        division_code=division_code,
        asset_type=asset_type,
        asset_no=asset_no,
        asset_number_hex=None,
        parameter_type=None,
        parameter_type_hex=None,
        from_time=eff_from_dt,
        to_time=eff_to_dt,
        limit=20000,
    )

    # Pre-fetch station and asset hierarchy
    station_lookup = {}
    stn_ids = list({gw.station_id for gw in gateway_map.values() if gw.station_id})
    if station_id and station_id not in stn_ids:
        stn_ids.append(station_id)
    if stn_ids:
        stns = db.query(Station).filter(Station.id.in_(stn_ids)).all()
        for s in stns:
            station_lookup[s.id] = s

    # Asset lookup: (station_id, an_hex) -> Asset
    asset_lookup = {}
    if stn_ids:
        assets = db.query(Asset).filter(Asset.station_id.in_(stn_ids)).all()
        for a in assets:
            if a.asset_number_id:
                asset_lookup[(a.station_id, a.asset_number_id.upper())] = a

    all_summary_rows: List[TelemetrySummaryRow] = []
    unique_assets = set()
    total_samples_all = 0
    total_warnings_all = 0
    total_criticals_all = 0

    idx = 1
    for (gw_id, pid), telem_rows in grouped.items():
        if not telem_rows:
            continue

        gw = gateway_map.get(gw_id)
        stn = station_lookup.get(gw.station_id) if gw and gw.station_id else None
        an_hex = pid[2:4].upper()
        asset_obj = asset_lookup.get((gw.station_id if gw else None, an_hex))

        z_id = stn.division.zone.id if stn and stn.division and stn.division.zone else None
        z_code = stn.division.zone.zone_code if stn and stn.division and stn.division.zone else (zone_code or "NR")
        d_id = stn.division.id if stn and stn.division else None
        d_code = stn.division.division_code if stn and stn.division else (division_code or "")
        s_id = stn.id if stn else station_id
        s_code = stn.station_code if stn else (station_code or "")

        at_hex = pid[0:2].upper()
        display_at_name = _get_display_asset_type_name(at_hex, asset_type)
        asset_no_code = asset_obj.asset_number_code if asset_obj else (asset_no or f"Asset-{an_hex}")
        unique_assets.add((s_id, asset_no_code))

        p_name, p_unit, pt_hex, p_code = _resolve_telemetry_param(pid)
        vals = [r.prv for r in telem_rows if r.prv is not None]
        if not vals:
            continue

        sample_count = len(vals)
        total_samples_all += sample_count
        min_v = round(min(vals), 2)
        max_v = round(max(vals), 2)
        avg_v = round(sum(vals) / sample_count, 2)

        latest_rec = max(telem_rows, key=lambda x: x.received_at or datetime.min)
        latest_val = latest_rec.prv
        last_recorded = latest_rec.received_at.strftime("%Y-%m-%d %H:%M:%S") if latest_rec.received_at else None

        # Resolve thresholds
        threshold = _get_threshold(db, at_hex, pt_hex, s_id)
        w_low = threshold.warning_low if threshold else None
        w_high = threshold.warning_high if threshold else None
        c_low = threshold.critical_low if threshold else None
        c_high = threshold.critical_high if threshold else None

        warnings = 0
        criticals = 0
        for val in vals:
            if (c_low is not None and val < c_low) or (c_high is not None and val > c_high):
                criticals += 1
            elif (w_low is not None and val < w_low) or (w_high is not None and val > w_high):
                warnings += 1

        total_warnings_all += warnings
        total_criticals_all += criticals

        in_range_pct = round(max(0.0, (sample_count - warnings - criticals) / sample_count * 100), 1)
        row_status = "Failure" if criticals > 0 else ("Predictive" if warnings > 0 else "Healthy")

        all_summary_rows.append(
            TelemetrySummaryRow(
                sr=idx,
                zone_id=z_id,
                zone=z_code,
                division_id=d_id,
                division=d_code,
                station_id=s_id,
                station=s_code,
                asset_type=display_at_name,
                asset_no=asset_no_code,
                parameter_name=p_name,
                parameter_code=p_code,
                unit=p_unit,
                min_value=min_v,
                max_value=max_v,
                avg_value=avg_v,
                latest_value=latest_val,
                total_samples=sample_count,
                in_range_pct=in_range_pct,
                warning_count=warnings,
                critical_count=criticals,
                last_recorded_at=last_recorded,
                status=row_status,
            )
        )
        idx += 1

    total_rows = len(all_summary_rows)
    total_pages = (total_rows + page_size - 1) // page_size if total_rows else 0
    offset = (page - 1) * page_size
    paginated_summary = all_summary_rows[offset: offset + page_size]

    healthy_count = sum(1 for r in all_summary_rows if r.status == "Healthy")
    healthy_pct = round((healthy_count / total_rows * 100), 1) if total_rows else 100.0

    metrics = TelemetrySummaryMetrics(
        total_assets=len(unique_assets),
        total_samples=total_samples_all,
        parameters_monitored=total_rows,
        healthy_pct=healthy_pct,
        warning_count=total_warnings_all,
        critical_count=total_criticals_all,
    )

    return {
        "status": True,
        "message": "Success",
        "data": TelemetrySummaryResponse(
            total=total_rows,
            page=page,
            page_size=page_size,
            total_pages=total_pages,
            metrics=metrics,
            rows=paginated_summary,
        )
    }


@router.get("/summary/download")
def download_telemetry_summary(
    station_id:       Optional[int]      = Query(None),
    station_code:     Optional[str]      = Query(None),
    zone_code:        Optional[str]      = Query(None),
    division_code:    Optional[str]      = Query(None),
    asset_type:       Optional[str]      = Query(None),
    asset_no:         Optional[str]      = Query(None),
    from_date:        Optional[str]      = Query(None),
    from_time:        Optional[str]      = Query(None),
    to_date:          Optional[str]      = Query(None),
    to_time:          Optional[str]      = Query(None),
    db:               Session            = Depends(get_db),
):
    """
    Download Telemetry Summary table as CSV.
    """
    from datetime import date as date_type
    res = get_telemetry_summary(
        station_id=station_id,
        station_code=station_code,
        zone_code=zone_code,
        division_code=division_code,
        asset_type=asset_type,
        asset_no=asset_no,
        from_date=from_date,
        from_time=from_time,
        to_date=to_date,
        to_time=to_time,
        page=1,
        page_size=10000,
        db=db,
    )

    rows = res["data"].rows if res and "data" in res else []

    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow([
        "SR", "ZONE", "DIVISION", "STATION", "ASSET TYPE", "ASSET NO.",
        "PARAMETER NAME", "PARAMETER CODE", "UNIT", "MIN VALUE", "MAX VALUE",
        "AVG VALUE", "LATEST VALUE", "TOTAL SAMPLES", "IN-RANGE (%)",
        "WARNINGS", "FAILURES", "STATUS", "LAST RECORDED AT"
    ])

    for r in rows:
        writer.writerow([
            r.sr, r.zone or "", r.division or "", r.station or "", r.asset_type or "",
            r.asset_no or "", r.parameter_name, r.parameter_code, r.unit,
            r.min_value, r.max_value, r.avg_value, r.latest_value, r.total_samples,
            f"{r.in_range_pct}%", r.warning_count, r.critical_count, r.status,
            r.last_recorded_at or ""
        ])

    output.seek(0)
    filename = f"telemetry_summary_{date_type.today().isoformat()}.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ── Telemetry Integration Endpoints ───────────────────────────────────────────
import uuid
from pydantic import BaseModel, Field, AliasChoices



class AssetNumberFilter(BaseModel):
    sc: str
    asset_number_code: str = Field(..., validation_alias=AliasChoices("asset_number_code", "assetNumberCode"))

class TelemetryHistoryRequestFilter(BaseModel):
    zone: Optional[List[str]] = []
    division: Optional[List[str]] = []
    station: Optional[List[str]] = []
    asset_type: Optional[List[str]] = Field([], validation_alias=AliasChoices("asset_type", "assetType"))
    asset_number: Optional[List[AssetNumberFilter]] = Field([], validation_alias=AliasChoices("asset_number", "assetNumber"))

class TelemetryHistoryReportRequest(BaseModel):
    start_date: str = Field(..., validation_alias=AliasChoices("start_date", "startDate"))
    start_time: str = Field(..., validation_alias=AliasChoices("start_time", "startTime"))
    end_date: str = Field(..., validation_alias=AliasChoices("end_date", "endDate"))
    end_time: str = Field(..., validation_alias=AliasChoices("end_time", "endTime"))
    request: TelemetryHistoryRequestFilter
    page_number: Optional[int] = Field(1, validation_alias=AliasChoices("page_number", "pageNumber"))
    page_size: Optional[int] = Field(20, validation_alias=AliasChoices("page_size", "pageSize"))

class SMMTelemetryRequest(BaseModel):
    rqi: Optional[str] = None
    vcc: Optional[str] = "XYZ"
    zc: Optional[str] = None
    dc: Optional[str] = None
    sc: Optional[str] = None
    smm_asset_code: Optional[str] = Field(None, validation_alias=AliasChoices("smm_asset_code", "smmAssetCode"))
    para_id: Optional[List[str]] = Field([], validation_alias=AliasChoices("para_id", "paraId"))


@integration_router.post("/vc_telemetry_history")
def vc_telemetry_history(payload: TelemetryHistoryReportRequest, db: Session = Depends(get_db)):
    # 1. Parse start and end datetimes
    def _parse_dt(date_str: str, time_str: str) -> datetime:
        for d_fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
            try:
                d = datetime.strptime(date_str.strip(), d_fmt).date()
                break
            except ValueError:
                continue
        else:
            raise HTTPException(status_code=400, detail=f"Could not parse date: {date_str}")
        
        for t_fmt in ("%H:%M:%S", "%H:%M"):
            try:
                t = datetime.strptime(time_str.strip(), t_fmt).time()
                break
            except ValueError:
                continue
        else:
            raise HTTPException(status_code=400, detail=f"Could not parse time: {time_str}")
        
        return datetime.combine(d, t)

    start_dt = _parse_dt(payload.start_date, payload.start_time)
    end_dt = _parse_dt(payload.end_date, payload.end_time)

    # 2. Filter assets
    asset_q = db.query(Asset).join(Station).join(Division).join(Zone)
    
    req_filter = payload.request
    if req_filter.zone:
        asset_q = asset_q.filter(Zone.zone_code.in_(req_filter.zone))
    if req_filter.division:
        asset_q = asset_q.filter(Division.division_code.in_(req_filter.division))
    if req_filter.station:
        asset_q = asset_q.filter(Station.station_code.in_(req_filter.station))
    if req_filter.asset_type:
        asset_q = asset_q.join(AssetTypeMaster).filter(AssetTypeMaster.asset_type_code.in_(req_filter.asset_type))
        
    if req_filter.asset_number:
        conditions = []
        for item in req_filter.asset_number:
            conditions.append(and_(Station.station_code == item.sc, Asset.asset_number_code == item.asset_number_code))
        asset_q = asset_q.filter(or_(*conditions))

    total_assets = asset_q.count()
    offset = (payload.page_number - 1) * payload.page_size
    assets = asset_q.offset(offset).limit(payload.page_size).all()

    # 3. Build hierarchy map
    hierarchy = {}

    for asset in assets:
        zc = asset.station.division.zone.zone_code
        dc = asset.station.division.division_code
        sc = asset.station.station_code
        
        gateway = asset.gateway
        if not gateway:
            continue
            
        prefix = f"{asset.asset_type_hex}{asset.asset_number_id}"
        
        telemetry_rows = (
            db.query(Telemetry)
            .filter(
                Telemetry.gateway_id == gateway.id,
                Telemetry.para_id.like(f"{prefix}%"),
                Telemetry.received_at >= start_dt,
                Telemetry.received_at <= end_dt
            )
            .order_by(Telemetry.received_at.desc())
            .all()
        )
        
        param_values = {}
        for row in telemetry_rows:
            pt_hex = row.para_id[4:6]
            param_info = PARAMETER_TYPE_MAP.get(pt_hex)
            if not param_info:
                continue
            param_name = param_info[1]
            key = f"{asset.asset_number_code} {param_name}"
            if key not in param_values:
                param_values[key] = row.prv

        if not param_values:
            continue

        zone_node = hierarchy.setdefault(zc, {})
        division_node = zone_node.setdefault(dc, {})
        station_node = division_node.setdefault(sc, {})
        station_node.update(param_values)

    zone_list = []
    for zc, divisions_dict in hierarchy.items():
        div_list = []
        for dc, stations_dict in divisions_dict.items():
            stn_list = []
            for sc, params in stations_dict.items():
                stn_list.append({
                    "sc": sc,
                    "parameters": params
                })
            div_list.append({
                "dc": dc,
                "station": stn_list
            })
        zone_list.append({
            "zc": zc,
            "division": div_list
        })

    res_data = {
        "vcc": "XYZ",
        "vcn": "XYZ TECHNOLOGIES",
        "start_date": payload.start_date,
        "start_time": payload.start_time,
        "end_date": payload.end_date,
        "end_time": payload.end_time,
        "zone": zone_list
    }
    return {
        **res_data,
        "status": True,
        "message": "Success",
        "data": res_data,
    }


def _handle_get_asset_telemetry(
    zc: str,
    dc: str,
    sc: str,
    smm_asset_code: str,
    para_id: str,
    payload_rqi: Optional[str],
    payload_vcc: Optional[str],
    payload_para_ids: Optional[List[str]],
    db: Session
):
    asset = db.query(Asset).filter(Asset.smms_asset_code == smm_asset_code).first()
    if not asset:
        raise HTTPException(status_code=404, detail=f"Asset with SMMS code '{smm_asset_code}' not found")

    gateway = asset.gateway
    if not gateway:
        raise HTTPException(status_code=404, detail=f"Gateway not found for asset '{smm_asset_code}'")

    pids = []
    if payload_para_ids:
        pids = [pid.strip().upper() for pid in payload_para_ids if pid]
    else:
        pids = [pid.strip().upper() for pid in para_id.split(",") if pid]

    telemetry_data_list = []
    for pid in pids:
        row = (
            db.query(Telemetry)
            .filter(Telemetry.gateway_id == gateway.id, Telemetry.para_id == pid)
            .order_by(Telemetry.received_at.desc())
            .first()
        )
        if row:
            ts_str = row.prt
            if not ts_str:
                ts_str = row.received_at.strftime("%d-%m-%Y %H:%M:%S.000")
            telemetry_data_list.append({
                "para_id": pid,
                "prv": row.prv,
                "prt": ts_str
            })

    res_data = {
        "resi": "RES-" + (payload_rqi or uuid.uuid4().hex[:12]),
        "vcc": payload_vcc or "XYZ",
        "zc": zc,
        "dc": dc,
        "sc": sc,
        "telemetry_data": [
            {
                "sms_asset_code": smm_asset_code,
                "parameters": telemetry_data_list
            }
        ]
    }
    return {
        **res_data,
        "status": True,
        "message": "Success",
        "data": res_data,
    }


@integration_router.get("/get_asset_telemetry/{zc}/{dc}/{sc}/{smm_asset_code}/{para_id}")
def get_asset_telemetry_get(
    zc: str,
    dc: str,
    sc: str,
    smm_asset_code: str,
    para_id: str,
    db: Session = Depends(get_db)
):
    return _handle_get_asset_telemetry(
        zc=zc, dc=dc, sc=sc, smm_asset_code=smm_asset_code, para_id=para_id,
        payload_rqi=None, payload_vcc="XYZ", payload_para_ids=None,
        db=db
    )


@integration_router.post("/get_asset_telemetry/{zc}/{dc}/{sc}/{smm_asset_code}/{para_id}")
def get_asset_telemetry_post(
    zc: str,
    dc: str,
    sc: str,
    smm_asset_code: str,
    para_id: str,
    payload: Optional[SMMTelemetryRequest] = None,
    db: Session = Depends(get_db)
):
    rqi = payload.rqi if payload else None
    vcc = payload.vcc if payload else "XYZ"
    pids = payload.para_id if payload else None
    return _handle_get_asset_telemetry(
        zc=zc, dc=dc, sc=sc, smm_asset_code=smm_asset_code, para_id=para_id,
        payload_rqi=rqi, payload_vcc=vcc, payload_para_ids=pids,
        db=db
    )