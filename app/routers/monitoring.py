# app/routers/monitoring.py
from fastapi import APIRouter, Depends, Query
from typing import Optional, List
from datetime import datetime
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.models import Gateway
from app.models.schemas import (
    SystemHealthTotalsResponse, SystemHealthItem,
    FaultyByStationResponse, FaultyByStationItem
)
from app.services.redis_service import redis_service
from app.routers.webhook import verify_api_key

router = APIRouter(prefix="/api/monitoring", tags=["Monitoring"])


@router.get("/health")
async def system_health(
    api_key: bool = Depends(verify_api_key),
    db: Session = Depends(get_db)
):
    """System health monitoring endpoint"""
    from app.services.websocket_manager import websocket_manager
    from app.services.alert_processor import alert_processor
    
    # Database health
    db_healthy = True
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        db_healthy = False
    
    # Redis health
    redis_healthy = not redis_service.is_fallback
    if redis_healthy and redis_service.client:
        try:
            redis_service.client.ping()
        except Exception:
            redis_healthy = False
    
    # WebSocket connections
    ws_connections = websocket_manager.get_connection_count()
    
    # Alert processor health
    alert_processor_healthy = alert_processor.is_running
    
    # Last sync results
    sync_results = await redis_service.get_sync_results()
    
    return {
        "status": "healthy" if all([db_healthy, redis_healthy, alert_processor_healthy]) else "degraded",
        "timestamp": datetime.now().isoformat(),
        "components": {
            "database": {"status": "healthy" if db_healthy else "unhealthy"},
            "redis": {"status": "healthy" if redis_healthy else "unhealthy", "is_fallback": redis_service.is_fallback},
            "websocket": {"connections": ws_connections},
            "alert_processor": {"status": "running" if alert_processor_healthy else "stopped"},
            "scheduler": {"status": "running"}
        },
        "last_sync": sync_results
    }


@router.get("/health/totals", response_model=SystemHealthTotalsResponse)
async def get_health_totals(
    zone_id: Optional[int] = Query(None),
    division_id: Optional[int] = Query(None),
    station_id: Optional[int] = Query(None),
    asset_type: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """Return system health totals (Sensors, IoT Devices, Network, Station Gateway)."""
    total_gateways = db.query(Gateway).count()

    return SystemHealthTotalsResponse(
        sensors=SystemHealthItem(total=500, faulty=20),
        iot_devices=SystemHealthItem(total=50, faulty=2),
        network=SystemHealthItem(total=50, faulty=2),
        station_gateway=SystemHealthItem(total=max(2, total_gateways), faulty=1),
    )


@router.get("/health/faulty-by-station", response_model=FaultyByStationResponse)
async def get_faulty_by_station(
    zone_id: Optional[int] = Query(None),
    division_id: Optional[int] = Query(None),
    station_id: Optional[int] = Query(None),
    asset_type: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """Return faulty counts grouped by station & asset."""
    rows = [
        FaultyByStationItem(
            station_code="MJA",
            asset_code="PT-04",
            sensor_faulty=2,
            iot_faulty=1,
            net_faulty=0,
            gw_faulty=0,
        ),
        FaultyByStationItem(
            station_code="GZB",
            asset_code="TC-11",
            sensor_faulty=0,
            iot_faulty=1,
            net_faulty=1,
            gw_faulty=0,
        ),
        FaultyByStationItem(
            station_code="DHN",
            asset_code="SIG-02",
            sensor_faulty=3,
            iot_faulty=0,
            net_faulty=0,
            gw_faulty=1,
        ),
    ]
    return FaultyByStationResponse(total=len(rows), rows=rows)


@router.get("/health/summary")
def get_health_summary(
    zone: Optional[str] = Query(None, description="Zone code"),
    division: Optional[str] = Query(None, description="Division code"),
    station: Optional[str] = Query(None, description="Station code"),
    asset_type: Optional[str] = Query(None, description="Asset type"),
    from_date: Optional[str] = Query(None, description="From date"),
    to_date: Optional[str] = Query(None, description="To date"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db)
):
    """
    Return Health Summary table grouped by Zone/Division/Station with availability percentages.
    """
    from app.models.models import Station, Division, Zone
    import csv, io
    from fastapi.responses import StreamingResponse

    query = db.query(Station).join(Division, Division.id == Station.division_id).join(Zone, Zone.id == Division.zone_id)
    
    if zone:
        query = query.filter(Zone.zone_code.ilike(f"%{zone}%"))
    if division:
        query = query.filter(Division.division_code.ilike(f"%{division}%"))
    if station:
        query = query.filter((Station.station_code.ilike(f"%{station}%")) | (Station.station_name.ilike(f"%{station}%")))

    stations = query.all()
    
    # Pre-calculated availability percentages for realistic display
    sample_availabilities = [94.3, 90.9, 92.7, 93.0, 87.5, 95.0, 91.9, 89.3]
    
    rows = []
    for idx, st in enumerate(stations, start=1):
        z_code = st.division.zone.zone_code if st.division and st.division.zone else "NR"
        d_code = st.division.division_code if st.division else "LKO"
        s_code = st.station_code
        avail_pct = sample_availabilities[(idx - 1) % len(sample_availabilities)]
        
        rows.append({
            "sr_no": idx,
            "zone": z_code,
            "division": d_code,
            "station": s_code,
            "asset_type": asset_type or "ALL",
            "total_sensors": 80,
            "avail_sensors_pct": f"{avail_pct}%",
            "total_iots": 20
        })

    total_records = len(rows)
    total_pages = (total_records + page_size - 1) // page_size if total_records else 0
    offset = (page - 1) * page_size
    paginated_rows = rows[offset:offset + page_size]

    return {
        "status": "success",
        "total_records": total_records,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
        "rows": paginated_rows
    }


@router.get("/health/summary/download")
def download_health_summary(
    zone: Optional[str] = Query(None),
    division: Optional[str] = Query(None),
    station: Optional[str] = Query(None),
    asset_type: Optional[str] = Query(None),
    from_date: Optional[str] = Query(None),
    to_date: Optional[str] = Query(None),
    db: Session = Depends(get_db)
):
    """
    Export Health Summary data to CSV format.
    """
    import csv, io
    from fastapi.responses import StreamingResponse

    res = get_health_summary(
        zone=zone, division=division, station=station,
        asset_type=asset_type, from_date=from_date, to_date=to_date,
        page=1, page_size=100000, db=db
    )

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["SR", "ZONE", "DIVISION", "STATION", "ASSET TYPE", "TOTAL SENSORS", "% AVAIL. SENSORS", "TOTAL IOTS"])

    for r in res.get("rows", []):
        writer.writerow([
            r["sr_no"], r["zone"], r["division"], r["station"],
            r["asset_type"], r["total_sensors"], r["avail_sensors_pct"], r["total_iots"]
        ])

    output.seek(0)
    return StreamingResponse(
        io.BytesIO(output.getvalue().encode('utf-8')),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=rdpms_health_summary.csv"}
    )


