# app/routers/dashboard.py
import json
from fastapi import APIRouter, Depends, HTTPException, Query, Body
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import func, and_, or_, case

from app.database import get_db, settings
from app.models.models import AlertEvent, Asset, Station, Division, Zone, AlertCauseMaster, Gateway, Telemetry
from app.services.statistics_service import statistics_service
from app.services.redis_service import redis_service
from app.routers.webhook import verify_api_key
import logging
logger = logging.getLogger("dashboard")

router = APIRouter(prefix="/api/dashboard", tags=["Common Dashboard"])


# ============ Annexure F §1(a) JSON-envelope request format ============
# Spec mandates: {"start_date":.., "start_time":.., "end_date":.., "end_time":..,
#   "request": {"zone":[...], "division":[...], "station":[...],
#   "alert_type":[...], "asset_type":[...],
#   "asset_number":[{"sc":.., "asset_number_code":..}, ...],
#   "cause":[...], "page_number":.., "page_size":..}}
# All 5 endpoints below accept this as an OPTIONAL JSON body in addition to
# the flat query params they already supported — body values win when
# present, so existing query-param callers are unaffected.

class AssetNumberFilter(BaseModel):
    """Station-keyed asset number, since the same asset_number_code can repeat across stations (Annexure F §1(a))."""
    sc: str
    asset_number_code: str

class DashboardRequestFilters(BaseModel):
    zone: Optional[List[str]] = None
    division: Optional[List[str]] = None
    station: Optional[List[str]] = None
    alert_type: Optional[List[str]] = None
    asset_type: Optional[List[str]] = None
    asset_number: Optional[List[AssetNumberFilter]] = None
    cause: Optional[List[str]] = None
    feedback: Optional[List[str]] = None
    alert_status: Optional[List[str]] = None
    page_number: Optional[int] = None
    page_size: Optional[int] = None

class DashboardEnvelopeBody(BaseModel):
    start_date: Optional[str] = None
    start_time: Optional[str] = None
    end_date: Optional[str] = None
    end_time: Optional[str] = None
    request: Optional[DashboardRequestFilters] = None

def _merge_envelope(body: Optional[DashboardEnvelopeBody], **query_values) -> dict:
    """
    Overlay JSON-envelope body values (if provided) onto the existing
    flat query-param values. Any field not set in the body falls back to
    whatever came in via query params, so this is purely additive.
    """
    merged = dict(query_values)
    if body is None:
        return merged

    if body.start_date is not None:
        merged['start_date'] = body.start_date
    if body.start_time is not None:
        merged['start_time'] = body.start_time
    if body.end_date is not None:
        merged['end_date'] = body.end_date
    if body.end_time is not None:
        merged['end_time'] = body.end_time

    req = body.request
    if req is not None:
        for field in ('zone', 'division', 'station', 'alert_type', 'asset_type',
                       'cause', 'feedback', 'alert_status', 'page_number', 'page_size'):
            val = getattr(req, field, None)
            if val is not None:
                merged[field] = val
        if req.asset_number is not None:
            merged['asset_number'] = req.asset_number

    return merged


# ============ Helper Functions ============

def _parse_date_range(
    start_date: Optional[str],
    start_time: Optional[str],
    end_date: Optional[str],
    end_time: Optional[str]
) -> tuple[Optional[datetime], Optional[datetime]]:
    """Parse date/time strings into datetime objects"""
    start_dt = None
    end_dt = None
    
    if start_date:
        if start_time:
            start_dt = datetime.strptime(f"{start_date} {start_time}", '%d/%m/%Y %H:%M:%S')
        else:
            start_dt = datetime.strptime(start_date, '%d/%m/%Y')
    
    if end_date:
        if end_time:
            end_dt = datetime.strptime(f"{end_date} {end_time}", '%d/%m/%Y %H:%M:%S')
        else:
            end_dt = datetime.strptime(end_date, '%d/%m/%Y') + timedelta(days=1) - timedelta(seconds=1)
    
    return start_dt, end_dt


def _resolve_location_ids(
    db: Session,
    zones: Optional[List[str]] = None,
    divisions: Optional[List[str]] = None,
    stations: Optional[List[str]] = None
) -> tuple[Optional[List[int]], Optional[List[int]], Optional[List[int]]]:
    """Resolve zone/division/station codes to IDs"""
    zone_ids = None
    division_ids = None
    station_ids = None
    
    if zones:
        zone_records = db.query(Zone).filter(Zone.zone_code.in_(zones)).all()
        zone_ids = [z.id for z in zone_records]
    
    if divisions:
        division_records = db.query(Division).filter(Division.division_code.in_(divisions)).all()
        division_ids = [d.id for d in division_records]
    
    if stations:
        station_records = db.query(Station).filter(Station.station_code.in_(stations)).all()
        station_ids = [s.id for s in station_records]
    
    return zone_ids, division_ids, station_ids


# ============ 1. Alert Summary Report ============

@router.post("/alert_summary")
async def get_alert_summary_report(
    start_date: Optional[str] = Query(None, description="Start date DD/MM/YYYY (or use JSON body)"),
    start_time: Optional[str] = Query(None, description="Start time HH:MM:SS"),
    end_date: Optional[str] = Query(None, description="End date DD/MM/YYYY"),
    end_time: Optional[str] = Query(None, description="End time HH:MM:SS"),
    zone: Optional[List[str]] = Query(None, description="Zone codes"),
    division: Optional[List[str]] = Query(None, description="Division codes"),
    station: Optional[List[str]] = Query(None, description="Station codes"),
    alert_type: Optional[List[str]] = Query(None, description="Alert types"),
    asset_type: Optional[List[str]] = Query(None, description="Asset type codes"),
    cause: Optional[List[str]] = Query(None, description="Cause codes"),
    page_number: Optional[int] = Query(1, ge=1, description="Page number"),
    page_size: Optional[int] = Query(50, ge=1, le=500, description="Page size"),
    body: Optional[DashboardEnvelopeBody] = Body(None, description="Annexure F §1(a) JSON envelope — overrides query params when provided"),
    api_key: bool = Depends(verify_api_key),
    db: Session = Depends(get_db)
):
    """
    Alert Summary Report - Annexure F §1

    Returns summarized alert counts grouped by Zone, Division, Station, Alert Type, Asset Type, Asset Number, and Cause.

    Accepts filters either as flat query params, or as the spec's JSON body
    envelope: {"start_date":.., "request": {"zone": [...], "cause": [...], ...}}.
    """
    m = _merge_envelope(body, start_date=start_date, start_time=start_time,
                         end_date=end_date, end_time=end_time, zone=zone,
                         division=division, station=station, alert_type=alert_type,
                         asset_type=asset_type, cause=cause,
                         page_number=page_number, page_size=page_size)
    start_date, start_time, end_date, end_time = m['start_date'], m['start_time'], m['end_date'], m['end_time']
    zone, division, station = m['zone'], m['division'], m['station']
    alert_type, asset_type, cause = m['alert_type'], m['asset_type'], m['cause']
    page_number, page_size = m['page_number'] or 1, m['page_size'] or 50

    if not start_date:
        raise HTTPException(status_code=422, detail="start_date is required (as a query param or in the JSON body)")

    # Parse dates
    start_dt, end_dt = _parse_date_range(start_date, start_time, end_date, end_time)
    
    # Resolve location IDs
    zone_ids, division_ids, station_ids = _resolve_location_ids(db, zone, division, station)
    
    # Build query
    query = db.query(
        Zone.zone_code.label("zone"),
        Division.division_code.label("division"),
        Station.station_code.label("station"),
        AlertEvent.vendor_code.label("vendor_code"),
        AlertEvent.alert_type.label("alert_type"),
        AlertEvent.asset_type_hex.label("asset_type_hex"),
        AlertEvent.asset_no.label("asset_no"),
        AlertEvent.cause.label("cause"),
        func.count(AlertEvent.id).label("total_count"),
        func.sum(case((AlertEvent.feedback == "T", 1), else_=0)).label("true_count"),
        func.sum(case((AlertEvent.feedback == "PT", 1), else_=0)).label("partial_count")
    ).join(Station, Station.id == AlertEvent.station_id)\
     .join(Division, Division.id == Station.division_id)\
     .join(Zone, Zone.id == Division.zone_id)
    
    # Apply filters
    if zone_ids:
        query = query.filter(Zone.id.in_(zone_ids))
    if division_ids:
        query = query.filter(Division.id.in_(division_ids))
    if station_ids:
        query = query.filter(Station.id.in_(station_ids))
    if alert_type:
        query = query.filter(AlertEvent.alert_type.in_(alert_type))
    if asset_type:
        query = query.filter(AlertEvent.asset_type_hex.in_(asset_type))
    if cause:
        query = query.filter(AlertEvent.cause.in_(cause))
    if start_dt:
        query = query.filter(AlertEvent.alert_time >= start_dt)
    if end_dt:
        query = query.filter(AlertEvent.alert_time <= end_dt)
    
    # Group by
    query = query.group_by(
        Zone.zone_code,
        Division.division_code,
        Station.station_code,
        AlertEvent.vendor_code,
        AlertEvent.alert_type,
        AlertEvent.asset_type_hex,
        AlertEvent.asset_no,
        AlertEvent.cause
    ).order_by(
        Zone.zone_code,
        Division.division_code,
        Station.station_code,
        AlertEvent.alert_type,
        AlertEvent.asset_type_hex,
        AlertEvent.asset_no,
        AlertEvent.cause
    )
    
    # Pagination
    total_rows = query.count()
    total_pages = (total_rows + page_size - 1) // page_size if total_rows else 0
    offset = (page_number - 1) * page_size
    rows = query.offset(offset).limit(page_size).all()
    
    # Build response
    result_rows = []
    for row in rows:
        total = row.total_count or 0
        true_count = row.true_count or 0
        partial_count = row.partial_count or 0
        percentage = round(((true_count + partial_count) / total) * 100, 1) if total > 0 else 0.0
        
        result_rows.append({
            "zone": row.zone,
            "division": row.division,
            "station": row.station,
            "vendor_code": row.vendor_code,
            "alert_type": row.alert_type,
            "asset_type_hex": row.asset_type_hex,
            "asset_no": row.asset_no,
            "cause": row.cause,
            "total_count": total,
            "true_count": true_count,
            "partial_count": partial_count,
            "success_percentage": percentage
        })
    
    return {
        "status": "success",
        "vendor_code": settings.VENDOR_CODE,
        "vendor_name": settings.VENDOR_NAME,
        "start_date": start_date,
        "start_time": start_time,
        "end_date": end_date,
        "end_time": end_time,
        "total_rows": total_rows,
        "page": page_number,
        "page_size": page_size,
        "total_pages": total_pages,
        "rows": result_rows
    }


# ============ 2. Alert History Report ============

@router.post("/alert_history")
async def get_alert_history_report(
    start_date: Optional[str] = Query(None, description="Start date DD/MM/YYYY (or use JSON body)"),
    start_time: Optional[str] = Query(None, description="Start time HH:MM:SS"),
    end_date: Optional[str] = Query(None, description="End date DD/MM/YYYY"),
    end_time: Optional[str] = Query(None, description="End time HH:MM:SS"),
    zone: Optional[List[str]] = Query(None, description="Zone codes"),
    division: Optional[List[str]] = Query(None, description="Division codes"),
    station: Optional[List[str]] = Query(None, description="Station codes"),
    alert_type: Optional[List[str]] = Query(None, description="Alert types"),
    asset_type: Optional[List[str]] = Query(None, description="Asset type codes"),
    cause: Optional[List[str]] = Query(None, description="Cause codes"),
    feedback: Optional[List[str]] = Query(None, description="Feedback types (T, PT, F, M)"),
    alert_status: Optional[List[str]] = Query(None, description="Alert status"),
    page_number: Optional[int] = Query(1, ge=1, description="Page number"),
    page_size: Optional[int] = Query(50, ge=1, le=500, description="Page size"),
    body: Optional[DashboardEnvelopeBody] = Body(None, description="Annexure F JSON envelope — overrides query params when provided"),
    api_key: bool = Depends(verify_api_key),
    db: Session = Depends(get_db)
):
    """
    Alert History Report - Annexure F §2
    
    Returns detailed alert records with all fields. Accepts filters either as
    flat query params or the spec's JSON body envelope (see alert_summary).
    """
    m = _merge_envelope(body, start_date=start_date, start_time=start_time,
                         end_date=end_date, end_time=end_time, zone=zone,
                         division=division, station=station, alert_type=alert_type,
                         asset_type=asset_type, cause=cause, feedback=feedback,
                         alert_status=alert_status, page_number=page_number, page_size=page_size)
    start_date, start_time, end_date, end_time = m['start_date'], m['start_time'], m['end_date'], m['end_time']
    zone, division, station = m['zone'], m['division'], m['station']
    alert_type, asset_type, cause = m['alert_type'], m['asset_type'], m['cause']
    feedback, alert_status = m['feedback'], m['alert_status']
    page_number, page_size = m['page_number'] or 1, m['page_size'] or 50

    if not start_date:
        raise HTTPException(status_code=422, detail="start_date is required (as a query param or in the JSON body)")

    # Parse dates
    start_dt, end_dt = _parse_date_range(start_date, start_time, end_date, end_time)
    
    # Resolve location IDs
    zone_ids, division_ids, station_ids = _resolve_location_ids(db, zone, division, station)
    
    # Build query
    query = db.query(
        AlertEvent.id,
        Zone.zone_code.label("zone"),
        Division.division_code.label("division"),
        Station.station_code.label("station"),
        AlertEvent.vendor_code.label("vendor_code"),
        AlertEvent.alert_type.label("alert_type"),
        AlertEvent.asset_type_hex.label("asset_type_hex"),
        AlertEvent.asset_no.label("asset_no"),
        AlertEvent.alert_status.label("alert_status"),
        AlertEvent.cause.label("cause"),
        AlertEvent.feedback.label("feedback"),
        AlertEvent.alert_time.label("incidence_date_time"),
        AlertEvent.rectification_time.label("rectification_date_time"),
        AlertEvent.feedback_time.label("feedback_date_time"),
        AlertEvent.maintainer_name.label("maintainer_name"),
        AlertEvent.designation.label("designation"),
        AlertEvent.mobile.label("mobile"),
        AlertEvent.remark.label("remarks")
    ).join(Station, Station.id == AlertEvent.station_id)\
     .join(Division, Division.id == Station.division_id)\
     .join(Zone, Zone.id == Division.zone_id)
    
    # Apply filters
    if zone_ids:
        query = query.filter(Zone.id.in_(zone_ids))
    if division_ids:
        query = query.filter(Division.id.in_(division_ids))
    if station_ids:
        query = query.filter(Station.id.in_(station_ids))
    if alert_type:
        query = query.filter(AlertEvent.alert_type.in_(alert_type))
    if asset_type:
        query = query.filter(AlertEvent.asset_type_hex.in_(asset_type))
    if cause:
        query = query.filter(AlertEvent.cause.in_(cause))
    if feedback:
        query = query.filter(AlertEvent.feedback.in_(feedback))
    if alert_status:
        query = query.filter(AlertEvent.alert_status.in_(alert_status))
    if start_dt:
        query = query.filter(AlertEvent.alert_time >= start_dt)
    if end_dt:
        query = query.filter(AlertEvent.alert_time <= end_dt)
    
    # Order by incidence date time descending
    query = query.order_by(AlertEvent.alert_time.desc())
    
    # Pagination
    total_rows = query.count()
    total_pages = (total_rows + page_size - 1) // page_size if total_rows else 0
    offset = (page_number - 1) * page_size
    rows = query.offset(offset).limit(page_size).all()
    
    # Build response
    result_rows = []
    for row in rows:
        # Calculate duration in minutes
        duration_min = None
        if row.rectification_date_time and row.incidence_date_time:
            duration_min = round((row.rectification_date_time - row.incidence_date_time).total_seconds() / 60, 2)
        
        result_rows.append({
            "id": row.id,
            "zone": row.zone,
            "division": row.division,
            "station": row.station,
            "vendor_code": row.vendor_code,
            "alert_type": row.alert_type,
            "asset_type_hex": row.asset_type_hex,
            "asset_no": row.asset_no,
            "alert_status": row.alert_status,
            "cause": row.cause,
            "feedback": row.feedback,
            "incidence_date_time": row.incidence_date_time.isoformat() if row.incidence_date_time else None,
            "rectification_date_time": row.rectification_date_time.isoformat() if row.rectification_date_time else None,
            "incidence_duration_minutes": duration_min,
            "feedback_date_time": row.feedback_date_time.isoformat() if row.feedback_date_time else None,
            "maintainer_name": row.maintainer_name,
            "designation": row.designation,
            "mobile": row.mobile,
            "remarks": row.remarks
        })
    
    return {
        "status": "success",
        "vendor_code": settings.VENDOR_CODE,
        "vendor_name": settings.VENDOR_NAME,
        "start_date": start_date,
        "start_time": start_time,
        "end_date": end_date,
        "end_time": end_time,
        "total_rows": total_rows,
        "page": page_number,
        "page_size": page_size,
        "total_pages": total_pages,
        "rows": result_rows
    }


# ============ 3. Telemetry History Report ============

@router.post("/telemetry_history")
async def get_telemetry_history_report(
    start_date: Optional[str] = Query(None, description="Start date DD/MM/YYYY (or use JSON body)"),
    start_time: Optional[str] = Query(None, description="Start time HH:MM:SS"),
    end_date: Optional[str] = Query(None, description="End date DD/MM/YYYY"),
    end_time: Optional[str] = Query(None, description="End time HH:MM:SS"),
    zone: Optional[List[str]] = Query(None, description="Zone codes"),
    division: Optional[List[str]] = Query(None, description="Division codes"),
    station: Optional[List[str]] = Query(None, description="Station codes"),
    asset_type: Optional[List[str]] = Query(None, description="Asset type codes"),
    asset_number: Optional[str] = Query(None, description="JSON string list of asset numbers with station codes: '[{\"sc\": \"STN\", \"asset_number_code\": \"PT-101\"}]'"),
    page_number: Optional[int] = Query(1, ge=1, description="Page number"),
    page_size: Optional[int] = Query(50, ge=1, le=500, description="Page size"),
    body: Optional[DashboardEnvelopeBody] = Body(None, description="Annexure F JSON envelope — overrides query params when provided. asset_number here is a proper array of {sc, asset_number_code} objects, not a JSON string."),
    api_key: bool = Depends(verify_api_key),
    db: Session = Depends(get_db)
):
    """
    Telemetry History Report - Annexure F §3
    
    Returns historical telemetry data for assets. Accepts filters either as
    flat query params or the spec's JSON body envelope (see alert_summary).
    """
    m = _merge_envelope(body, start_date=start_date, start_time=start_time,
                         end_date=end_date, end_time=end_time, zone=zone,
                         division=division, station=station, asset_type=asset_type,
                         page_number=page_number, page_size=page_size)
    start_date, start_time, end_date, end_time = m['start_date'], m['start_time'], m['end_date'], m['end_time']
    zone, division, station, asset_type = m['zone'], m['division'], m['station'], m['asset_type']
    page_number, page_size = m['page_number'] or 1, m['page_size'] or 50

    # asset_number from the JSON body comes as a list of AssetNumberFilter
    # objects; convert to the same JSON-string shape the existing downstream
    # code already parses, so nothing else needs to change.
    if body is not None and body.request is not None and body.request.asset_number is not None:
        asset_number = json.dumps([a.model_dump() for a in body.request.asset_number])

    if not start_date:
        raise HTTPException(status_code=422, detail="start_date is required (as a query param or in the JSON body)")

    # Parse dates
    start_dt, end_dt = _parse_date_range(start_date, start_time, end_date, end_time)
    
    # Resolve location IDs
    zone_ids, division_ids, station_ids = _resolve_location_ids(db, zone, division, station)
    
    # Build query
    query = db.query(Telemetry).join(
        Gateway, Gateway.id == Telemetry.gateway_id
    ).join(
        Station, Station.id == Gateway.station_id
    ).join(
        Division, Division.id == Station.division_id
    ).join(
        Zone, Zone.id == Division.zone_id
    )
    
    # Apply location filters
    if zone_ids:
        query = query.filter(Zone.id.in_(zone_ids))
    if division_ids:
        query = query.filter(Division.id.in_(division_ids))
    if station_ids:
        query = query.filter(Station.id.in_(station_ids))
    
    # Apply asset type filter
    if asset_type:
        # Get parameter IDs for asset types
        asset_params = db.query(AssetParameter).join(
            Asset, Asset.id == AssetParameter.asset_id
        ).filter(Asset.asset_type_hex.in_(asset_type)).all()
        para_ids = [ap.para_id for ap in asset_params]
        if para_ids:
            query = query.filter(Telemetry.para_id.in_(para_ids))
    
    # Apply asset number filter
    if asset_number:
        import json
        try:
            asset_number_list = json.loads(asset_number)
        except Exception:
            asset_number_list = []
            
        para_ids = []
        for item in asset_number_list:
            sc = item.get("sc")
            asset_no = item.get("asset_number_code")
            if sc and asset_no:
                # Get station
                stn = db.query(Station).filter(Station.station_code == sc).first()
                if stn:
                    # Get asset
                    ast = db.query(Asset).filter(
                        Asset.station_id == stn.id,
                        Asset.asset_number_code == asset_no
                    ).first()
                    if ast:
                        asset_params = db.query(AssetParameter).filter(
                            AssetParameter.asset_id == ast.id
                        ).all()
                        para_ids.extend([ap.para_id for ap in asset_params])
        
        if para_ids:
            query = query.filter(Telemetry.para_id.in_(para_ids))
    
    # Apply date range
    if start_dt:
        query = query.filter(Telemetry.prt >= start_dt.strftime("%d-%m-%Y %H:%M:%S.000"))
    if end_dt:
        query = query.filter(Telemetry.prt <= end_dt.strftime("%d-%m-%Y %H:%M:%S.999"))
    
    # Order by timestamp
    query = query.order_by(Telemetry.prt.desc())
    
    # Pagination
    total_rows = query.count()
    total_pages = (total_rows + page_size - 1) // page_size if total_rows else 0
    offset = (page_number - 1) * page_size
    rows = query.offset(offset).limit(page_size).all()
    
    # Build response
    result_rows = []
    for row in rows:
        result_rows.append({
            "stngw_id": row.gateway.stngw_id if row.gateway else "UNKNOWN",
            "para_id": row.para_id,
            "value": row.prv,
            "timestamp": row.prt
        })
    
    return {
        "status": "success",
        "vendor_code": settings.VENDOR_CODE,
        "vendor_name": settings.VENDOR_NAME,
        "start_date": start_date,
        "start_time": start_time,
        "end_date": end_date,
        "end_time": end_time,
        "total_rows": total_rows,
        "page": page_number,
        "page_size": page_size,
        "total_pages": total_pages,
        "rows": result_rows
    }


# ============ 4. Asset Detail Report ============

@router.post("/asset_detail")
async def get_asset_detail_report(
    zone: Optional[List[str]] = Query(None, description="Zone codes"),
    division: Optional[List[str]] = Query(None, description="Division codes"),
    station: Optional[List[str]] = Query(None, description="Station codes"),
    asset_type: Optional[List[str]] = Query(None, description="Asset type codes"),
    page_number: Optional[int] = Query(1, ge=1, description="Page number"),
    page_size: Optional[int] = Query(50, ge=1, le=500, description="Page size"),
    body: Optional[DashboardEnvelopeBody] = Body(None, description="Annexure F JSON envelope — overrides query params when provided"),
    api_key: bool = Depends(verify_api_key),
    db: Session = Depends(get_db)
):
    """
    Asset Detail Report - Annexure F §4
    
    Returns asset counts grouped by Zone, Division, Station, Asset Type, and Make.
    Accepts filters either as flat query params or the spec's JSON body
    envelope (see alert_summary). This report has no date range.
    """
    m = _merge_envelope(body, zone=zone, division=division, station=station,
                         asset_type=asset_type, page_number=page_number, page_size=page_size)
    zone, division, station, asset_type = m['zone'], m['division'], m['station'], m['asset_type']
    page_number, page_size = m['page_number'] or 1, m['page_size'] or 50

    # Resolve location IDs
    zone_ids, division_ids, station_ids = _resolve_location_ids(db, zone, division, station)
    
    # Build query
    query = db.query(
        Zone.zone_code.label("zone"),
        Division.division_code.label("division"),
        Station.station_code.label("station"),
        Asset.vendor_code.label("vendor_code"),
        Asset.asset_type_hex.label("asset_type_hex"),
        Asset.make.label("make"),
        func.count(Asset.id).label("count")
    ).join(Station, Station.id == Asset.station_id)\
     .join(Division, Division.id == Station.division_id)\
     .join(Zone, Zone.id == Division.zone_id)
    
    # Apply filters
    if zone_ids:
        query = query.filter(Zone.id.in_(zone_ids))
    if division_ids:
        query = query.filter(Division.id.in_(division_ids))
    if station_ids:
        query = query.filter(Station.id.in_(station_ids))
    if asset_type:
        query = query.filter(Asset.asset_type_hex.in_(asset_type))
    
    # Group by
    query = query.group_by(
        Zone.zone_code,
        Division.division_code,
        Station.station_code,
        Asset.vendor_code,
        Asset.asset_type_hex,
        Asset.make
    ).order_by(
        Zone.zone_code,
        Division.division_code,
        Station.station_code,
        Asset.asset_type_hex,
        Asset.make
    )
    
    # Pagination
    total_rows = query.count()
    total_pages = (total_rows + page_size - 1) // page_size if total_rows else 0
    offset = (page_number - 1) * page_size
    rows = query.offset(offset).limit(page_size).all()
    
    # Build response
    result_rows = []
    for row in rows:
        result_rows.append({
            "zone": row.zone,
            "division": row.division,
            "station": row.station,
            "vendor_code": row.vendor_code,
            "asset_type_hex": row.asset_type_hex,
            "make": row.make or "Unknown",
            "count": row.count
        })
    
    return {
        "status": "success",
        "vendor_code": settings.VENDOR_CODE,
        "vendor_name": settings.VENDOR_NAME,
        "as_on_date": datetime.now().strftime('%d/%m/%Y'),
        "total_rows": total_rows,
        "page": page_number,
        "page_size": page_size,
        "total_pages": total_pages,
        "rows": result_rows
    }


# ============ 5. Performance Report ============

@router.post("/performance")
async def get_performance_report(
    start_date: Optional[str] = Query(None, description="Start date DD/MM/YYYY (or use JSON body)"),
    start_time: Optional[str] = Query(None, description="Start time HH:MM:SS"),
    end_date: Optional[str] = Query(None, description="End date DD/MM/YYYY"),
    end_time: Optional[str] = Query(None, description="End time HH:MM:SS"),
    zone: Optional[List[str]] = Query(None, description="Zone codes"),
    division: Optional[List[str]] = Query(None, description="Division codes"),
    station: Optional[List[str]] = Query(None, description="Station codes"),
    page_number: Optional[int] = Query(1, ge=1, description="Page number"),
    page_size: Optional[int] = Query(50, ge=1, le=500, description="Page size"),
    body: Optional[DashboardEnvelopeBody] = Body(None, description="Annexure F JSON envelope — overrides query params when provided"),
    api_key: bool = Depends(verify_api_key),
    db: Session = Depends(get_db)
):
    """
    Performance Report - Annexure F §5
    
    Returns performance metrics for each station. Accepts filters either as
    flat query params or the spec's JSON body envelope (see alert_summary).
    """
    m = _merge_envelope(body, start_date=start_date, start_time=start_time,
                         end_date=end_date, end_time=end_time, zone=zone,
                         division=division, station=station,
                         page_number=page_number, page_size=page_size)
    start_date, start_time, end_date, end_time = m['start_date'], m['start_time'], m['end_date'], m['end_time']
    zone, division, station = m['zone'], m['division'], m['station']
    page_number, page_size = m['page_number'] or 1, m['page_size'] or 50

    if not start_date:
        raise HTTPException(status_code=422, detail="start_date is required (as a query param or in the JSON body)")

    # Parse dates
    start_dt, end_dt = _parse_date_range(start_date, start_time, end_date, end_time)
    
    # Resolve location IDs
    zone_ids, division_ids, station_ids = _resolve_location_ids(db, zone, division, station)
    
    # Get all stations matching filters
    station_query = db.query(Station).join(Division, Division.id == Station.division_id).join(Zone, Zone.id == Division.zone_id)
    
    if zone_ids:
        station_query = station_query.filter(Zone.id.in_(zone_ids))
    if division_ids:
        station_query = station_query.filter(Division.id.in_(division_ids))
    if station_ids:
        station_query = station_query.filter(Station.id.in_(station_ids))
    
    stations = station_query.all()
    
    # Calculate performance for each station
    result_rows = []
    
    for stn in stations:
        # Get alert statistics
        stats = await statistics_service.calculate_alert_statistics(
            stngw_id=None,
            start_date=start_dt,
            end_date=end_dt
        )
        
        result_rows.append({
            "zone": stn.division.zone.zone_code,
            "division": stn.division.division_code,
            "station": stn.station_code,
            "vendor_code": settings.VENDOR_CODE,
            "vendor_name": settings.VENDOR_NAME,
            "fail_alert_per": stats.get("failure_success_rate", 0.0),
            "pred_alert_per": stats.get("predictive_success_rate", 0.0),
            "actual_fail_alert_per": 0.0
        })
    
    # Pagination
    total_rows = len(result_rows)
    total_pages = (total_rows + page_size - 1) // page_size if total_rows else 0
    offset = (page_number - 1) * page_size
    paginated_rows = result_rows[offset:offset + page_size]
    
    return {
        "status": "success",
        "vendor_code": settings.VENDOR_CODE,
        "vendor_name": settings.VENDOR_NAME,
        "start_date": start_date,
        "start_time": start_time,
        "end_date": end_date,
        "end_time": end_time,
        "total_rows": total_rows,
        "page": page_number,
        "page_size": page_size,
        "total_pages": total_pages,
        "rows": paginated_rows
    }
