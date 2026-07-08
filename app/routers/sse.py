# app/routers/sse.py
from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from typing import Optional, AsyncGenerator
import asyncio
import json
from datetime import datetime
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.services.redis_service import redis_service
from app.models.models import Station, Gateway, AlertEvent
from app.routers.webhook import verify_api_key
import logging
logger = logging.getLogger("sse")

router = APIRouter(prefix="/sse", tags=["SSE"])

@router.get("/telemetry/{station_code}")
async def sse_telemetry(
    station_code: str,
    asset_type: Optional[str] = Query(None),
    asset_no: Optional[str] = Query(None),
    api_key: bool = Depends(verify_api_key)
):
    """
    Server-Sent Events endpoint for live telemetry streaming.
    
    Clients receive a continuous stream of parameter updates.
    """
    async def event_generator() -> AsyncGenerator[str, None]:
        with SessionLocal() as db:
            # Get station and gateway
            station = db.query(Station).filter(Station.station_code == station_code).first()
            if not station:
                yield f"event: error\ndata: {json.dumps({'message': 'Station not found'})}\n\n"
                return
            
            gateway = db.query(Gateway).filter(Gateway.station_id == station.id).first()
            if not gateway:
                yield f"event: error\ndata: {json.dumps({'message': 'Gateway not found'})}\n\n"
                return
            
            stngw_id = gateway.stngw_id
            
        # Send initial state
        latest_values = await redis_service.get_all_latest_parameters(stngw_id)
        yield f"event: initial\ndata: {json.dumps({'station_code': station_code, 'parameters': latest_values})}\n\n"
        
        # Stream updates every 5 seconds
        last_update = {}
        while True:
            try:
                # Get latest values from Redis
                current_values = await redis_service.get_all_latest_parameters(stngw_id)
                
                # Only send updates if values changed
                if current_values != last_update:
                    # Find changed parameters
                    changed = {}
                    for para_id, value in current_values.items():
                        if para_id not in last_update or last_update[para_id] != value:
                            changed[para_id] = value
                    
                    if changed:
                        yield f"event: update\ndata: {json.dumps({'station_code': station_code, 'changed': changed, 'timestamp': datetime.now().isoformat()})}\n\n"
                    
                    last_update = current_values
                
                # Keep connection alive with heartbeat
                yield f"event: heartbeat\ndata: {json.dumps({'timestamp': datetime.now().isoformat()})}\n\n"
                
                await asyncio.sleep(5)  # Update interval
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"SSE telemetry error: {e}")
                yield f"event: error\ndata: {json.dumps({'message': str(e)})}\n\n"
                await asyncio.sleep(1)
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"  # Disable nginx buffering
        }
    )


@router.get("/alerts/{station_code}")
async def sse_alerts(
    station_code: str,
    alert_type: Optional[str] = Query("all"),
    api_key: bool = Depends(verify_api_key)
):
    """
    Server-Sent Events endpoint for live alert streaming.
    
    Clients receive alerts as they are generated.
    """
    async def event_generator() -> AsyncGenerator[str, None]:
        with SessionLocal() as db:
            station = db.query(Station).filter(Station.station_code == station_code).first()
            if not station:
                yield f"event: error\ndata: {json.dumps({'message': 'Station not found'})}\n\n"
                return
            
            station_id = station.id

        # Send pending alerts
        with SessionLocal() as db:
            query = db.query(AlertEvent).filter(
                AlertEvent.station_id == station_id,
                AlertEvent.alert_status == "Active"
            )
            if alert_type.lower() != "all":
                query = query.filter(AlertEvent.alert_type.ilike(alert_type))
            
            pending = query.order_by(AlertEvent.alert_time.desc()).limit(50).all()
            if pending:
                yield f"event: pending\ndata: {json.dumps({'alerts': [{'id': a.id, 'asset_no': a.asset_no, 'cause': a.cause, 'time': a.alert_time.isoformat() if a.alert_time else datetime.utcnow().isoformat()} for a in pending]})}\n\n"
            
            # Track seen alert IDs
            seen_ids = {a.id for a in pending}
        
        # Stream new alerts
        while True:
            try:
                with SessionLocal() as db:
                    # Check for new alerts
                    new_alerts = db.query(AlertEvent).filter(
                        AlertEvent.station_id == station_id,
                        AlertEvent.alert_status == "Active",
                        AlertEvent.id.notin_(seen_ids)
                    ).order_by(AlertEvent.alert_time.desc()).limit(10).all()
                    
                    for alert in new_alerts:
                        yield f"event: alert\ndata: {json.dumps({'id': alert.id, 'alert_type': alert.alert_type, 'asset_no': alert.asset_no, 'cause': alert.cause, 'cause_detail': alert.remark or '', 'time': alert.alert_time.isoformat() if alert.alert_time else datetime.utcnow().isoformat()})}\n\n"
                        seen_ids.add(alert.id)
                
                # Heartbeat
                yield f"event: heartbeat\ndata: {json.dumps({'timestamp': datetime.now().isoformat()})}\n\n"
                
                await asyncio.sleep(2)  # Check every 2 seconds
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"SSE alerts error: {e}")
                yield f"event: error\ndata: {json.dumps({'message': str(e)})}\n\n"
                await asyncio.sleep(1)
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


@router.get("/health/{station_code}")
async def sse_health(
    station_code: str,
    api_key: bool = Depends(verify_api_key)
):
    """
    Server-Sent Events endpoint for live health status streaming.
    """
    async def event_generator() -> AsyncGenerator[str, None]:
        with SessionLocal() as db:
            station = db.query(Station).filter(Station.station_code == station_code).first()
            if not station:
                yield f"event: error\ndata: {json.dumps({'message': 'Station not found'})}\n\n"
                return
            
            gateway = db.query(Gateway).filter(Gateway.station_id == station.id).first()
            if not gateway:
                yield f"event: error\ndata: {json.dumps({'message': 'Gateway not found'})}\n\n"
                return
            
            stngw_id = gateway.stngw_id
            
        last_health = {}
        
        while True:
            try:
                # Get current health from Redis
                current_health = {
                    "gateway": await redis_service.get_gateway_info(stngw_id),
                    "sensors": await redis_service.get_sensor_health_summary(stngw_id),
                    "timestamp": datetime.now().isoformat()
                }
                
                if current_health != last_health:
                    yield f"event: update\ndata: {json.dumps(current_health)}\n\n"
                    last_health = current_health
                
                yield f"event: heartbeat\ndata: {json.dumps({'timestamp': datetime.now().isoformat()})}\n\n"
                
                await asyncio.sleep(30)  # Update every 30 seconds
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"SSE health error: {e}")
                yield f"event: error\ndata: {json.dumps({'message': str(e)})}\n\n"
                await asyncio.sleep(1)
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )
