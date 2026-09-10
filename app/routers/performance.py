from typing import List, Optional, Any
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, Query, Body, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db, settings
from app.models.models import Station, Division, Zone, AlertEvent
from app.models.schemas import (
    PerformanceOverviewResponse,
    StationPerformanceItem,
    StandardResponse
)
from app.routers.dashboard import (
    _parse_date_range,
    _resolve_location_ids,
    _parse_list_param
)
from app.services.statistics_service import statistics_service

router = APIRouter(prefix="/api/performance", tags=["Performance Module"])


@router.api_route("", methods=["GET", "POST"])
@router.api_route("/", methods=["GET", "POST"])
async def get_performance_module_report(
    start_date: Optional[str] = Query(None, description="Start date DD/MM/YYYY or YYYY-MM-DD"),
    start_time: Optional[str] = Query(None, description="Start time HH:MM:SS"),
    end_date: Optional[str] = Query(None, description="End date DD/MM/YYYY or YYYY-MM-DD"),
    end_time: Optional[str] = Query(None, description="End time HH:MM:SS"),
    from_date: Optional[str] = Query(None, description="Start date DD/MM/YYYY or YYYY-MM-DD"),
    from_time: Optional[str] = Query(None, description="Start time HH:MM:SS"),
    to_date: Optional[str] = Query(None, description="End date DD/MM/YYYY or YYYY-MM-DD"),
    to_time: Optional[str] = Query(None, description="End time HH:MM:SS"),
    fromDate: Optional[str] = Query(None, description="Start date alias"),
    toDate: Optional[str] = Query(None, description="End date alias"),
    fromTime: Optional[str] = Query(None, description="Start time alias"),
    toTime: Optional[str] = Query(None, description="End time alias"),
    zone: Optional[Any] = Query(None, description="Zone code or ID"),
    division: Optional[Any] = Query(None, description="Division code or ID"),
    station: Optional[Any] = Query(None, description="Station code or ID"),
    zone_id: Optional[Any] = Query(None, description="Zone database ID or code"),
    division_id: Optional[Any] = Query(None, description="Division database ID or code"),
    station_id: Optional[Any] = Query(None, description="Station database ID or code"),
    zoneId: Optional[Any] = Query(None, description="Zone alias ID"),
    divisionId: Optional[Any] = Query(None, description="Division alias ID"),
    stationId: Optional[Any] = Query(None, description="Station alias ID"),
    page: Optional[int] = Query(None, ge=1, description="Page number"),
    page_number: Optional[int] = Query(1, ge=1, description="Page number"),
    page_size: int = Query(50, ge=1, le=500, description="Page size"),
    body: Optional[Any] = Body(None, description="Optional JSON body for POST requests"),
    db: Session = Depends(get_db)
):
    """
    Performance Module API — /performance and /api/performance.
    Returns 3 KPI top average percentages and station-wise performance rows in one call.
    """
    # Merge body payload if provided via POST
    if body and isinstance(body, dict):
        req = body.get("request", body)
        from_date = from_date or req.get("from_date") or req.get("fromDate") or req.get("start_date")
        to_date = to_date or req.get("to_date") or req.get("toDate") or req.get("end_date")
        from_time = from_time or req.get("from_time") or req.get("fromTime") or req.get("start_time")
        to_time = to_time or req.get("to_time") or req.get("toTime") or req.get("end_time")
        zone = zone or req.get("zone") or req.get("zone_id") or req.get("zoneId")
        division = division or req.get("division") or req.get("division_id") or req.get("divisionId")
        station = station or req.get("station") or req.get("station_id") or req.get("stationId")
        if req.get("page"):
            page = req.get("page")
        if req.get("page_size"):
            page_size = req.get("page_size")

    effective_page = page if page is not None else (page_number or 1)

    effective_from_date = from_date or fromDate or start_date
    effective_to_date = to_date or toDate or end_date
    effective_from_time = from_time or fromTime or start_time
    effective_to_time = to_time or toTime or end_time

    start_dt, end_dt = _parse_date_range(effective_from_date, effective_from_time, effective_to_date, effective_to_time)

    # Normalize location filter inputs
    effective_zone = zone_id if zone_id is not None else (zoneId if zoneId is not None else zone)
    effective_division = division_id if division_id is not None else (divisionId if divisionId is not None else division)
    effective_station = station_id if station_id is not None else (stationId if stationId is not None else station)

    zone_ids, division_ids, station_ids = _resolve_location_ids(db, effective_zone, effective_division, effective_station)

    station_query = db.query(Station).join(Division, Division.id == Station.division_id).join(Zone, Zone.id == Division.zone_id)
    if zone_ids is not None:
        station_query = station_query.filter(Zone.id.in_(zone_ids))
    if division_ids is not None:
        station_query = station_query.filter(Division.id.in_(division_ids))
    if station_ids is not None:
        station_query = station_query.filter(Station.id.in_(station_ids))

    stations = station_query.all()
    result_rows = []

    for stn in stations:
        stats = await statistics_service.calculate_alert_statistics(
            station_id=stn.id,
            start_date=start_dt,
            end_date=end_dt,
            db=db
        )

        fail_rate = stats.get("failure_success_rate", 0.0)
        pred_rate = stats.get("predictive_success_rate", 0.0)

        result_rows.append({
            "id": stn.id,
            "zone": stn.division.zone.zone_code if stn.division and stn.division.zone else "",
            "division": stn.division.division_code if stn.division else "",
            "station": stn.station_code,
            "fail_alert_per": round(fail_rate, 1),
            "pred_alert_per": round(pred_rate, 1),
            "actual_fail_alert_per": 0.0
        })

    if result_rows:
        avg_fail_acc = round(sum(r["fail_alert_per"] for r in result_rows) / len(result_rows), 1)
        avg_pred_acc = round(sum(r["pred_alert_per"] for r in result_rows) / len(result_rows), 1)
        avg_actual_cov = round(sum(r["actual_fail_alert_per"] for r in result_rows) / len(result_rows), 1)
    else:
        avg_fail_acc = 0.0
        avg_pred_acc = 0.0
        avg_actual_cov = 0.0

    total_rows = len(result_rows)
    total_pages = (total_rows + page_size - 1) // page_size if total_rows else 0
    offset = (effective_page - 1) * page_size
    paginated_rows = result_rows[offset:offset + page_size]

    return {
        "status": True,
        "message": "Success",
        "data": {
            "avg_failure_alert_accuracy": avg_fail_acc,
            "avg_predictive_alert_accuracy": avg_pred_acc,
            "avg_actual_failure_coverage": avg_actual_cov,
            "start_date": effective_from_date,
            "start_time": effective_from_time,
            "end_date": effective_to_date,
            "end_time": effective_to_time,
            "total_rows": total_rows,
            "total_records": total_rows,
            "total": total_rows,
            "page": effective_page,
            "page_size": page_size,
            "total_pages": total_pages,
            "rows": paginated_rows
        }
    }


# ============ Enter Actual Failure Entry Endpoint ============

from pydantic import BaseModel, Field

class ActualFailureCreate(BaseModel):
    station: str = Field(..., description="Station code or station name, e.g. MJA")
    asset_type: str = Field("Point Machine", description="Asset Type, e.g. Point Machine")
    asset_no: str = Field(..., description="Asset Number, e.g. PT-101")
    failure_date: str = Field(..., description="Failure Date DD/MM/YYYY or YYYY-MM-DD")
    cause: str = Field(..., description="Failure Cause detail")


@router.post("/actual-failure", response_model=StandardResponse[Any])
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
        "status": True,
        "message": "Success",
        "data": {
            "id": event.id,
            "station": payload.station,
            "asset_type": payload.asset_type,
            "asset_no": payload.asset_no,
            "failure_date": payload.failure_date,
            "cause": payload.cause
        }
    }
