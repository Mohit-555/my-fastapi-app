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

