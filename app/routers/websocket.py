# app/routers/websocket.py
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from typing import Optional, Dict
import json
import asyncio
from datetime import datetime
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.services.websocket_manager import websocket_manager
from app.services.redis_service import redis_service
from app.models.models import Station, Gateway, AlertEvent
import logging
logger = logging.getLogger("websocket")

router = APIRouter(tags=["WebSocket"])

@router.websocket("/ws/telemetry/{station_code}")
async def websocket_telemetry(
    websocket: WebSocket,
    station_code: str,
    asset_type: Optional[str] = Query(None),
    asset_no: Optional[str] = Query(None)
):
    """
    WebSocket endpoint for live telemetry streaming.
    
    Clients receive real-time parameter updates for the specified station.
    Optional filters: asset_type, asset_no
    """
    connection_id = await websocket_manager.connect(
        websocket=websocket,
        station_code=station_code,
        client_info={
            "asset_type": asset_type,
            "asset_no": asset_no
        }
    )
    
    try:
        # Send initial state
        await send_initial_telemetry(websocket, station_code, asset_type, asset_no)
        
        # Keep connection alive and handle client messages
        while True:
            # Receive client messages (for subscriptions/control)
            data = await websocket.receive_text()
            try:
                message = json.loads(data)
                await handle_client_message(websocket, message, station_code)
            except json.JSONDecodeError:
                await websocket.send_text(json.dumps({
                    "type": "error",
                    "message": "Invalid JSON format"
                }))
                
    except WebSocketDisconnect:
        websocket_manager.disconnect(websocket)
        logger.info(f"WebSocket disconnected: {connection_id}")


@router.websocket("/ws/alerts/{station_code}")
async def websocket_alerts(
    websocket: WebSocket,
    station_code: str,
    alert_type: Optional[str] = Query(None)  # "failure", "predictive", or "all"
):
    """
    WebSocket endpoint for live alert streaming.
    
    Clients receive real-time alert notifications for the specified station.
    """
    connection_id = await websocket_manager.connect(
        websocket=websocket,
        station_code=station_code,
        client_info={"alert_type": alert_type or "all"}
    )
    
    try:
        # Send pending alerts initially
        await send_pending_alerts(websocket, station_code, alert_type)
        
        while True:
            # Keep connection alive
            data = await websocket.receive_text()
            try:
                message = json.loads(data)
                if message.get("action") == "acknowledge":
                    await handle_acknowledgement(websocket, message, station_code)
                elif message.get("action") == "subscribe":
                    await handle_alert_subscription(websocket, message, station_code)
            except json.JSONDecodeError:
                await websocket.send_text(json.dumps({
                    "type": "error",
                    "message": "Invalid JSON format"
                }))
                
    except WebSocketDisconnect:
        websocket_manager.disconnect(websocket)
        logger.info(f"Alert WebSocket disconnected: {connection_id}")


@router.websocket("/ws/health/{station_code}")
async def websocket_health(
    websocket: WebSocket,
    station_code: str
):
    """
    WebSocket endpoint for live health status streaming.
    
    Clients receive real-time health updates for sensors, IoT, gateway, and network.
    """
    connection_id = await websocket_manager.connect(
        websocket=websocket,
        station_code=station_code,
        client_info={"type": "health"}
    )
    
    try:
        # Send initial health status
        await send_initial_health(websocket, station_code)
        
        while True:
            # Keep connection alive
            await websocket.receive_text()
                
    except WebSocketDisconnect:
        websocket_manager.disconnect(websocket)
        logger.info(f"Health WebSocket disconnected: {connection_id}")


# ============ Helper Functions ============

async def send_initial_telemetry(
    websocket: WebSocket,
    station_code: str,
    asset_type: Optional[str],
    asset_no: Optional[str]
):
    """Send initial telemetry data when client connects"""
    try:
        with SessionLocal() as db:
            # Get station
            station = db.query(Station).filter(Station.station_code == station_code).first()
            if not station:
                await websocket.send_text(json.dumps({
                    "type": "error",
                    "message": f"Station {station_code} not found"
                }))
                return
            
            # Get gateway
            gateway = db.query(Gateway).filter(Gateway.station_id == station.id).first()
            if not gateway:
                await websocket.send_text(json.dumps({
                    "type": "error",
                    "message": f"Gateway for station {station_code} not found"
                }))
                return
            
            # Get latest values from Redis
            latest_values = await redis_service.get_all_latest_parameters(gateway.stngw_id)
            
            await websocket.send_text(json.dumps({
                "type": "initial_state",
                "data": {
                    "station_code": station_code,
                    "timestamp": datetime.now().isoformat(),
                    "parameters": latest_values
                }
            }))
        
    except Exception as e:
        logger.error(f"Error sending initial telemetry: {e}")
        try:
            await websocket.send_text(json.dumps({
                "type": "error",
                "message": f"Error loading initial data: {str(e)}"
            }))
        except Exception:
            pass


async def send_pending_alerts(
    websocket: WebSocket,
    station_code: str,
    alert_type: Optional[str]
):
    """Send pending alerts when client connects"""
    try:
        with SessionLocal() as db:
            station = db.query(Station).filter(Station.station_code == station_code).first()
            if not station:
                return
            
            query = db.query(AlertEvent).filter(
                AlertEvent.station_id == station.id,
                AlertEvent.alert_status == "Active"
            )
            
            if alert_type and alert_type.lower() != "all":
                query = query.filter(
                    AlertEvent.alert_type.ilike(alert_type)
                )
            
            alerts = query.order_by(AlertEvent.alert_time.desc()).limit(100).all()
            
            await websocket.send_text(json.dumps({
                "type": "pending_alerts",
                "data": [
                    {
                        "id": alert.id,
                        "alert_type": alert.alert_type,
                        "asset_no": alert.asset_no,
                        "cause": alert.cause,
                        "cause_detail": alert.remark or "",
                        "time": alert.alert_time.isoformat() if alert.alert_time else datetime.utcnow().isoformat(),
                        "acknowledged": alert.acknowledged
                    }
                    for alert in alerts
                ]
            }))
        
    except Exception as e:
        logger.error(f"Error sending pending alerts: {e}")


async def send_initial_health(
    websocket: WebSocket,
    station_code: str
):
    """Send initial health status when client connects"""
    try:
        with SessionLocal() as db:
            station = db.query(Station).filter(Station.station_code == station_code).first()
            if not station:
                return
            
            gateway = db.query(Gateway).filter(Gateway.station_id == station.id).first()
            if not gateway:
                return
            
            # Get health from Redis
            health_data = {
                "station_code": station_code,
                "timestamp": datetime.now().isoformat(),
                "gateway": await redis_service.get_gateway_info(gateway.stngw_id),
                "sensors": await redis_service.get_sensor_health_summary(gateway.stngw_id),
                "iot": await redis_service.get_iot_health_summary(gateway.stngw_id)
            }
            
            await websocket.send_text(json.dumps({
                "type": "initial_health",
                "data": health_data
            }))
        
    except Exception as e:
        logger.error(f"Error sending initial health: {e}")


async def handle_client_message(websocket: WebSocket, message: Dict, station_code: str):
    """Handle client messages (subscriptions, control)"""
    action = message.get("action")
    
    if action == "subscribe":
        asset_type = message.get("asset_type")
        asset_no = message.get("asset_no")
        logger.info(f"Client subscribed to {station_code} - {asset_type} - {asset_no}")
        await websocket.send_text(json.dumps({
            "type": "subscription_confirmed",
            "data": {"asset_type": asset_type, "asset_no": asset_no}
        }))


async def handle_acknowledgement(websocket: WebSocket, message: Dict, station_code: str):
    """Handle alert acknowledgement from client"""
    alert_id = message.get("alert_id")
    if not alert_id:
        await websocket.send_text(json.dumps({
            "type": "error",
            "message": "alert_id required"
        }))
        return
    
    with SessionLocal() as db:
        alert = db.query(AlertEvent).filter(AlertEvent.id == alert_id).first()
        if alert:
            alert.acknowledged = True
            db.commit()
    
    await websocket.send_text(json.dumps({
        "type": "acknowledged",
        "data": {"alert_id": alert_id}
    }))


async def handle_alert_subscription(websocket: WebSocket, message: Dict, station_code: str):
    """Handle alert type subscription"""
    alert_type = message.get("alert_type", "all")
    logger.info(f"Client subscribed to alerts: {station_code} - {alert_type}")
    await websocket.send_text(json.dumps({
        "type": "subscription_confirmed",
        "data": {"alert_type": alert_type}
    }))
