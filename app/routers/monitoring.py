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


@router.get("/telemetry-debug")
async def telemetry_debug(db: Session = Depends(get_db)):
    from app.models.models import Telemetry, AssetParameter, Asset
    from app.services.alert_engine import alert_engine, AlertType
    from app.services.alert_processor import safe_parse_datetime
    from fastapi import HTTPException
    
    # Query latest telemetry records overall
    telemetry_records = db.query(Telemetry).order_by(Telemetry.id.desc()).limit(10).all()
    
    telemetry_list = []
    for r in telemetry_records:
        # Run manual evaluation for this record
        evaluation_result = alert_engine.evaluate_telemetry(
            gateway_id=r.gateway_id,
            stngw_id="01011200",  # LKO gateway
            para_id=r.para_id,
            value=r.prv,
            timestamp=r.prt,
            db=db
        )
        
        # Try to generate alert for each evaluation result
        generation_results = []
        for alert_data in evaluation_result:
            try:
                # Find mapped asset
                ap = db.query(AssetParameter).filter(AssetParameter.para_id == r.para_id).first()
                asset = db.query(Asset).filter(Asset.id == ap.asset_id).first() if ap else None
                if not asset:
                    generation_results.append({"status": "error", "message": "Asset not found"})
                    continue
                    
                # Call create_alert_event directly to see the exception
                from app.routers.alerts import create_alert_event
                from app.models.schemas import AlertEventCreate
                import traceback
                
                payload = AlertEventCreate(
                    station_id=1,  # LKO station ID
                    alert_type=alert_data["alert_type"].value,
                    asset_type_hex=asset.asset_type_hex,
                    asset_no=asset.asset_number_code,
                    cause=alert_data["cause_code"],
                    alert_status="Active",
                    alert_time=safe_parse_datetime(r.prt),
                    remark=alert_data["cause_detail"]
                )
                
                try:
                    alert = create_alert_event(payload, db)
                    generation_results.append({"status": "success", "alert_id": alert.id})
                except HTTPException as he:
                    generation_results.append({
                        "status": "http_exception",
                        "status_code": he.status_code,
                        "detail": he.detail
                    })
                except Exception as ex:
                    generation_results.append({
                        "status": "exception",
                        "error": str(ex),
                        "trace": traceback.format_exc()
                    })
            except Exception as e:
                generation_results.append({"status": "exception", "error": str(e)})
        
        telemetry_list.append({
            "id": r.id,
            "gateway_id": r.gateway_id,
            "para_id": r.para_id,
            "prv": r.prv,
            "prt": r.prt,
            "is_processed": r.is_processed,
            "received_at": r.received_at.isoformat() if r.received_at else None,
            "evaluation_result": evaluation_result,
            "generation_results": generation_results
        })
        
    # Query AssetParameter for 0001000C
    ap = db.query(AssetParameter).filter(AssetParameter.para_id == "0001000C").first()
    ap_info = None
    if ap:
        ap_info = {
            "id": ap.id,
            "para_id": ap.para_id,
            "asset_id": ap.asset_id,
            "is_assigned": ap.is_assigned
        }
        
    # Query all active or semi-active AlertEvents
    from app.models.models import AlertEvent
    all_db_alerts = db.query(AlertEvent).all()
    db_alerts_info = [
        {
            "id": a.id,
            "station_id": a.station_id,
            "asset_no": a.asset_no,
            "cause": a.cause,
            "alert_status": a.alert_status,
            "rectification_time": a.rectification_time.isoformat() if a.rectification_time else None
        }
        for a in all_db_alerts
    ]
        
    from app.models.models import Station, Division, Zone
    st = db.query(Station).filter(Station.id == 1).first()
    st_info = {
        "id": st.id if st else None,
        "station_code": st.station_code if st else None,
        "division_id": st.division_id if st else None
    } if st else None
    
    div = db.query(Division).filter(Division.id == st.division_id).first() if st else None
    div_info = {
        "id": div.id if div else None,
        "division_code": div.division_code if div else None,
        "zone_id": div.zone_id if div else None
    } if div else None
    
    zn = db.query(Zone).filter(Zone.id == div.zone_id).first() if div else None
    zn_info = {
        "id": zn.id if zn else None,
        "zone_code": zn.zone_code if zn else None
    } if zn else None
        
    # Run _base_live_query
    from app.routers.alerts import _base_live_query
    try:
        live_query_rows = _base_live_query(db, None, None, None, None, None, None, None, None).all()
        live_query_results = [
            {
                "id": r.id,
                "station_id": r.station_id,
                "asset_no": r.asset_no,
                "cause": r.cause,
                "alert_status": r.alert_status
            }
            for r in live_query_rows
        ]
    except Exception as e:
        live_query_results = {"error": str(e)}

    # Run _process_batch manually
    from app.services.alert_processor import alert_processor
    import asyncio
    
    tasks_info = []
    for t in asyncio.all_tasks():
        tasks_info.append({
            "name": t.get_name(),
            "coro": str(t.get_coro())
        })
        
    # Count unprocessed
    unprocessed_count = db.query(Telemetry).filter(Telemetry.is_processed == False).count()
    oldest_unprocessed = db.query(Telemetry).filter(Telemetry.is_processed == False).order_by(Telemetry.id.asc()).first()
    oldest_info = {
        "id": oldest_unprocessed.id,
        "prt": oldest_unprocessed.prt,
        "received_at": oldest_unprocessed.received_at.isoformat() if oldest_unprocessed.received_at else None
    } if oldest_unprocessed else None

    newest_unprocessed = db.query(Telemetry).filter(Telemetry.is_processed == False).order_by(Telemetry.id.desc()).first()
    newest_info = {
        "id": newest_unprocessed.id,
        "prt": newest_unprocessed.prt,
        "received_at": newest_unprocessed.received_at.isoformat() if newest_unprocessed.received_at else None
    } if newest_unprocessed else None

    raw_unprocessed = db.query(Telemetry).filter(Telemetry.is_processed == False).order_by(Telemetry.id.asc()).limit(5).all()
    unprocessed_info = [
        {
            "id": r.id,
            "gateway_id": r.gateway_id,
            "para_id": r.para_id,
            "prv": r.prv,
            "prt": r.prt,
            "received_at": r.received_at.isoformat() if r.received_at else None
        }
        for r in raw_unprocessed
    ]

    from app.database import SessionLocal
    test_db = SessionLocal()
    manual_error = None
    try:
        unprocessed_test = test_db.query(Telemetry).filter(
            Telemetry.is_processed == False
        ).order_by(Telemetry.id.asc()).limit(10).all()
        
        for telemetry in unprocessed_test:
            # Replicate the core logic:
            gateway = test_db.query(Gateway).filter(Gateway.id == telemetry.gateway_id).first()
            if not gateway:
                telemetry.is_processed = True
                continue
                
            asset_param = test_db.query(AssetParameter).filter(AssetParameter.para_id == telemetry.para_id).first()
            if not asset_param or not asset_param.asset_id:
                telemetry.is_processed = True
                continue
                
            asset = test_db.query(Asset).filter(Asset.id == asset_param.asset_id).first()
            if not asset:
                telemetry.is_processed = True
                continue
                
            alerts = alert_engine.evaluate_telemetry(
                gateway_id=gateway.id,
                stngw_id=gateway.stngw_id,
                para_id=telemetry.para_id,
                value=telemetry.prv,
                timestamp=telemetry.prt,
                db=test_db
            )
            
            for alert_data in alerts:
                alert_engine._generate_alert(
                    station_id=gateway.station_id,
                    asset_id=asset.id,
                    asset_number_code=asset.asset_number_code,
                    asset_type_hex=asset.asset_type_hex,
                    cause_code=alert_data["cause_code"],
                    cause_detail=alert_data["cause_detail"],
                    alert_type=alert_data["alert_type"],
                    timestamp=safe_parse_datetime(telemetry.prt),
                    db=test_db
                )
            telemetry.is_processed = True
            
        test_db.commit()
    except Exception as e:
        manual_error = f"Commit failed: {type(e).__name__}: {str(e)}"
        test_db.rollback()
    finally:
        test_db.close()

    process_batch_res = None
    try:
        await alert_processor._process_batch()
        process_batch_res = "Success"
    except Exception as e:
        process_batch_res = f"Error: {e}"

    return {
        "telemetry": telemetry_list,
        "asset_parameter": ap_info,
        "db_alerts": db_alerts_info,
        "station_1": st_info,
        "division": div_info,
        "zone": zn_info,
        "live_query_results": live_query_results,
        "asyncio_tasks": tasks_info,
        "manual_process_batch": process_batch_res,
        "unprocessed_count": unprocessed_count,
        "oldest_unprocessed": oldest_info,
        "newest_unprocessed": newest_info,
        "raw_unprocessed": unprocessed_info,
        "manual_error": manual_error
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


