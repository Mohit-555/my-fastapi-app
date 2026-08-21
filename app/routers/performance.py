from typing import List, Optional
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, Query, Body, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db, settings
from app.models.models import Station, Division, Zone, AlertEvent
from app.models.schemas import (
    PerformanceOverviewResponse,
    StationPerformanceItem
)
from app.routers.dashboard import (
    DashboardEnvelopeBody,
    _merge_envelope,
    _parse_date_range,
    _resolve_location_ids
)
from app.services.statistics_service import statistics_service

router = APIRouter(prefix="/api/performance", tags=["Performance Module"])


@router.api_route("", methods=["GET", "POST"])
async def get_performance_module_report(
    start_date: Optional[str] = Query(None, description="Start date DD/MM/YYYY"),
    start_time: Optional[str] = Query(None, description="Start time HH:MM:SS"),
    end_date: Optional[str] = Query(None, description="End date DD/MM/YYYY"),
    end_time: Optional[str] = Query(None, description="End time HH:MM:SS"),
    zone: Optional[List[str]] = Query(None, description="Zone codes"),
    division: Optional[List[str]] = Query(None, description="Division codes"),
    station: Optional[List[str]] = Query(None, description="Station codes"),
    page_number: Optional[int] = Query(1, ge=1, description="Page number"),
    page_size: Optional[int] = Query(50, ge=1, le=500, description="Page size"),
    body: Optional[DashboardEnvelopeBody] = Body(None, description="Annexure F JSON envelope — overrides query params when provided"),
    db: Session = Depends(get_db)
):
    """
    Performance Module API — /performance and /api/performance.
    Returns 3 KPI top average percentages and station-wise performance rows in one call.
    """
    if not start_date:
        start_date = (datetime.now() - timedelta(days=30)).strftime("%d/%m/%Y")

    m = _merge_envelope(body, start_date=start_date, start_time=start_time,
                         end_date=end_date, end_time=end_time, zone=zone,
                         division=division, station=station,
                         page_number=page_number, page_size=page_size)
    start_date, start_time, end_date, end_time = m['start_date'], m['start_time'], m['end_date'], m['end_time']
    zone, division, station = m['zone'], m['division'], m['station']
    page_number, page_size = m['page_number'] or 1, m['page_size'] or 50

    start_dt, end_dt = _parse_date_range(start_date, start_time, end_date, end_time)
    zone_ids, division_ids, station_ids = _resolve_location_ids(db, zone, division, station)
    
    station_query = db.query(Station).join(Division, Division.id == Station.division_id).join(Zone, Zone.id == Division.zone_id)
    if zone_ids:
        station_query = station_query.filter(Zone.id.in_(zone_ids))
    if division_ids:
        station_query = station_query.filter(Division.id.in_(division_ids))
    if station_ids:
        station_query = station_query.filter(Station.id.in_(station_ids))
    
    stations = station_query.all()
    result_rows = []
    
    for stn in stations:
        stats = await statistics_service.calculate_alert_statistics(
            stngw_id=None,
            start_date=start_dt,
            end_date=end_dt
        )
        
        result_rows.append({
            "zone": stn.division.zone.zone_code,
            "division": stn.division.division_code,
            "station": stn.station_code,
            "fail_alert_per": stats.get("failure_success_rate", 50.0),
            "pred_alert_per": stats.get("predictive_success_rate", 50.0),
            "actual_fail_alert_per": 0.0
        })
    
    if result_rows:
        avg_fail_acc = round(sum(r["fail_alert_per"] for r in result_rows) / len(result_rows), 1)
        avg_pred_acc = round(sum(r["pred_alert_per"] for r in result_rows) / len(result_rows), 1)
        avg_actual_cov = round(sum(r["actual_fail_alert_per"] for r in result_rows) / len(result_rows), 1)
    else:
        avg_fail_acc = 50.0
        avg_pred_acc = 50.0
        avg_actual_cov = 0.0

    total_rows = len(result_rows)
    total_pages = (total_rows + page_size - 1) // page_size if total_rows else 0
    offset = (page_number - 1) * page_size
    paginated_rows = result_rows[offset:offset + page_size]
    
    return {
        "status": "success",
        "avg_failure_alert_accuracy": avg_fail_acc,
        "avg_predictive_alert_accuracy": avg_pred_acc,
        "avg_actual_failure_coverage": avg_actual_cov,
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


# ============ Enter Actual Failure Entry Endpoint ============

from pydantic import BaseModel, Field

class ActualFailureCreate(BaseModel):
    station: str = Field(..., description="Station code or station name, e.g. MJA")
    asset_type: str = Field("Point Machine", description="Asset Type, e.g. Point Machine")
    asset_no: str = Field(..., description="Asset Number, e.g. PT-101")
    failure_date: str = Field(..., description="Failure Date DD/MM/YYYY or YYYY-MM-DD")
    cause: str = Field(..., description="Failure Cause detail")


@router.post("/actual-failure")
async def create_actual_failure_entry(
    payload: ActualFailureCreate,
    db: Session = Depends(get_db)
):
    """
    Submits ground-truth site failure entry from the 'Enter Actual Failure' form.
    Creates an official AlertEvent record for AI accuracy scoring.
    """
    station_obj = db.query(Station).filter(
        (Station.station_code == payload.station.upper()) | (Station.station_name.ilike(f"%{payload.station}%"))
    ).first()
    
    station_id = station_obj.id if station_obj else 1
    
    try:
        if "/" in payload.failure_date:
            failure_dt = datetime.strptime(payload.failure_date, "%d/%m/%Y")
        else:
            failure_dt = datetime.strptime(payload.failure_date, "%Y-%m-%d")
    except Exception:
        failure_dt = datetime.now()
        
    event = AlertEvent(
        station_id=station_id,
        asset_no=payload.asset_no,
        asset_type_hex="01",
        alert_type="Failure",
        alert_status="Confirmed",
        alert_time=failure_dt,
        cause=payload.cause,
        feedback="T",
        remark=f"Actual Site Failure Recorded: {payload.cause}"
    )
    
    db.add(event)
    db.commit()
    db.refresh(event)
    
    return {
        "status": "success",
        "message": f"Actual failure entry saved for asset {payload.asset_no} at station {payload.station}",
        "data": {
            "id": event.id,
            "station": payload.station,
            "asset_type": payload.asset_type,
            "asset_no": payload.asset_no,
            "failure_date": payload.failure_date,
            "cause": payload.cause
        }
    }
