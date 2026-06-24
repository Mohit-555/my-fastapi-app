import csv
import io
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.models import MaintenanceMode, Station, Division, Zone, Asset
from app.models.schemas import MaintenanceModeRequest, MaintenanceModeResponse, MaintenanceModeListResponse
from app.constants import ASSET_TYPE_MAP

router = APIRouter(prefix="/maintenance", tags=["Maintenance"])


def _build_response_row(row: MaintenanceMode, index: int) -> MaintenanceModeResponse:
    station = row.station
    division = station.division if station else None
    zone = division.zone if division else None

    asset_info = ASSET_TYPE_MAP.get(row.asset_type_hex)
    asset_name = asset_info[1] if asset_info else "Unknown"

    return MaintenanceModeResponse(
        id=row.id,
        zone_id=zone.id if zone else 0,
        zone_code=zone.zone_code if zone else "",
        zone_name=zone.zone_name if zone else "",
        division_id=division.id if division else 0,
        division_code=division.division_code if division else "",
        division_name=division.division_name if division else "",
        station_id=station.id if station else 0,
        station_code=station.station_code if station else "",
        station_name=station.station_name if station else "",
        asset_type_hex=row.asset_type_hex,
        asset_type_name=asset_name,
        asset_no=row.asset_no,
        from_time=row.from_time,
        to_time=row.to_time,
        from_date=row.from_time,
        to_date=row.to_time,
        created_at=row.created_at
    )


def _base_query(
    db: Session,
    zone_id: Optional[int],
    division_id: Optional[int],
    station_id: Optional[int],
    asset_type_hex: Optional[str],
    asset_no: Optional[str],
    from_time: Optional[datetime],
    to_time: Optional[datetime],
):
    q = db.query(MaintenanceMode).join(Station).join(Division).join(Zone)

    if zone_id is not None:
        q = q.filter(Division.zone_id == zone_id)
    if division_id is not None:
        q = q.filter(Station.division_id == division_id)
    if station_id is not None:
        q = q.filter(MaintenanceMode.station_id == station_id)
    if asset_type_hex:
        q = q.filter(MaintenanceMode.asset_type_hex == asset_type_hex)
    if asset_no:
        q = q.filter(MaintenanceMode.asset_no.ilike(f"%{asset_no}%"))
    if from_time:
        q = q.filter(MaintenanceMode.from_time >= from_time)
    if to_time:
        q = q.filter(MaintenanceMode.to_time <= to_time)

    return q.order_by(MaintenanceMode.created_at.desc(), MaintenanceMode.id.desc())


@router.get("", response_model=MaintenanceModeListResponse)
def list_maintenance_modes(
    zone_id: Optional[int] = Query(None),
    division_id: Optional[int] = Query(None),
    station_id: Optional[int] = Query(None),
    asset_type_hex: Optional[str] = Query(None),
    asset_no: Optional[str] = Query(None),
    from_time: Optional[datetime] = Query(None),
    to_time: Optional[datetime] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """List maintenance mode entries with pagination and filters."""
    q = _base_query(db, zone_id, division_id, station_id, asset_type_hex, asset_no, from_time, to_time)
    total = q.count()
    offset = (page - 1) * page_size
    rows = q.offset(offset).limit(page_size).all()

    return MaintenanceModeListResponse(
        total=total,
        page=page,
        page_size=page_size,
        rows=[_build_response_row(r, idx + offset + 1) for idx, r in enumerate(rows)]
    )


@router.post("", response_model=MaintenanceModeResponse, status_code=status.HTTP_201_CREATED)
def activate_maintenance_mode(payload: MaintenanceModeRequest, db: Session = Depends(get_db)):
    """Activate maintenance mode for a specific asset."""
    station = db.query(Station).filter(Station.id == payload.station_id).first()
    if not station:
        raise HTTPException(status_code=404, detail=f"Station with ID {payload.station_id} not found")

    # Find asset by station_id and asset_no
    asset = db.query(Asset).filter(
        Asset.station_id == payload.station_id,
        (Asset.asset_number_code == payload.asset_no) | (Asset.smms_asset_code == payload.asset_no)
    ).first()
    if not asset:
        raise HTTPException(
            status_code=404,
            detail=f"Asset '{payload.asset_no}' not found at station {payload.station_id}"
        )

    # Resolve start and end times
    from_dt = payload.from_date or payload.from_time
    to_dt = payload.to_date or payload.to_time
    if not from_dt or not to_dt:
        raise HTTPException(
            status_code=400,
            detail="Either (from_time, to_time) or (from_date, to_date) must be provided"
        )

    record = MaintenanceMode(
        station_id=payload.station_id,
        asset_type_hex=asset.asset_type_hex,
        asset_no=payload.asset_no,
        from_time=from_dt,
        to_time=to_dt,
        asset_id=asset.id,
        created_at=datetime.utcnow()
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return _build_response_row(record, 1)


@router.get("/download")
@router.get("/export")
def download_maintenance_modes(
    zone_id: Optional[int] = Query(None),
    division_id: Optional[int] = Query(None),
    station_id: Optional[int] = Query(None),
    asset_type_hex: Optional[str] = Query(None),
    asset_no: Optional[str] = Query(None),
    from_time: Optional[datetime] = Query(None),
    to_time: Optional[datetime] = Query(None),
    db: Session = Depends(get_db),
):
    """Export filtered maintenance mode records to a CSV file."""
    rows = _base_query(db, zone_id, division_id, station_id, asset_type_hex, asset_no, from_time, to_time).all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "SR", "ZONE", "DIVISION", "STATION", "ASSET TYPE", "ASSET NO.", "ACTIVATE DATE & TIME"
    ])

    for idx, r in enumerate(rows, start=1):
        res = _build_response_row(r, idx)
        # Format date time nicely: 09 Jun 2026, 09:19:30
        date_str = res.created_at.strftime("%d %b %Y, %H:%M:%S")
        writer.writerow([
            idx,
            res.zone_code,
            res.division_code,
            res.station_code,
            res.asset_type_name,
            res.asset_no,
            date_str
        ])

    output.seek(0)
    filename = f"maintenance_modes_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )
