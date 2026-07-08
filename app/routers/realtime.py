# app/routers/realtime.py
from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.database import get_db
from app.models.models import Station, Gateway, Telemetry, AlertEvent, Asset
from app.services.redis_service import redis_service
from app.services.statistics_service import statistics_service
from app.services.parameter_config_service import param_config_service
from app.routers.webhook import verify_api_key
import logging
logger = logging.getLogger("realtime")

router = APIRouter(prefix="/api/realtime", tags=["Real-Time"])


@router.get("/telemetry/{station_code}")
async def get_live_telemetry(
    station_code: str,
    asset_type: Optional[str] = Query(None),
    asset_no: Optional[str] = Query(None),
    api_key: bool = Depends(verify_api_key),
    db: Session = Depends(get_db)
):
    """
    Get latest telemetry values for a station.
    Returns all parameters with their current values.
    """
    station = db.query(Station).filter(Station.station_code == station_code).first()
    if not station:
        raise HTTPException(status_code=404, detail=f"Station {station_code} not found")
    
    gateway = db.query(Gateway).filter(Gateway.station_id == station.id).first()
    if not gateway:
        return {
            "station_code": station_code,
            "timestamp": datetime.now().isoformat(),
            "parameters": {},
            "message": "No gateway found for station"
        }
    
    # Get latest values from Redis
    latest_values = await redis_service.get_all_latest_parameters(gateway.stngw_id)
    
    # If asset_type or asset_no provided, filter parameters
    if asset_type or asset_no:
        # Get parameter IDs for the asset
        query = db.query(Asset).filter(Asset.station_id == station.id)
        if asset_no:
            query = query.filter(Asset.asset_number_code == asset_no)
        if asset_type:
            query = query.filter(Asset.asset_type_hex == asset_type)
        
        asset = query.first()
        if asset:
            # Get parameters for this asset
            param_ids = [p.para_id for p in asset.parameters]
            latest_values = {
                pid: val for pid, val in latest_values.items()
                if pid in param_ids
            }
    
    return {
        "station_code": station_code,
        "station_name": station.station_name,
        "timestamp": datetime.now().isoformat(),
        "parameter_count": len(latest_values),
        "parameters": latest_values
    }


@router.get("/telemetry/{station_code}/{para_id}/history")
async def get_telemetry_history(
    station_code: str,
    para_id: str,
    hours: int = Query(24, ge=1, le=168, description="Number of hours to look back"),
    api_key: bool = Depends(verify_api_key),
    db: Session = Depends(get_db)
):
    """
    Get historical telemetry data for a specific parameter.
    Returns time-series data for the last N hours.
    """
    station = db.query(Station).filter(Station.station_code == station_code).first()
    if not station:
        raise HTTPException(status_code=404, detail=f"Station {station_code} not found")
    
    gateway = db.query(Gateway).filter(Gateway.station_id == station.id).first()
    if not gateway:
        raise HTTPException(status_code=404, detail="Gateway not found")
    
    # Calculate time range using UTC naive datetime to match database defaults
    end_time = datetime.utcnow()
    start_time = end_time - timedelta(hours=hours)
    
    # Query history from database using received_at DateTime column
    history = db.query(Telemetry).filter(
        Telemetry.gateway_id == gateway.id,
        Telemetry.para_id == para_id,
        Telemetry.received_at >= start_time,
        Telemetry.received_at <= end_time
    ).order_by(Telemetry.received_at.asc()).limit(10000).all()
    
    # Get parameter config (for metadata) from service cache
    param_config = param_config_service.get_parameter_config(para_id)
    
    return {
        "para_id": para_id,
        "station_code": station_code,
        "period": {
            "start": start_time.isoformat(),
            "end": end_time.isoformat(),
            "hours": hours
        },
        "data_points": len(history),
        "parameter_info": {
            "name": param_config.parameter_representation_name if param_config else None,
            "unit": param_config.unit if param_config else None,
            "min_safe": param_config.min_safe if param_config else None,
            "max_safe": param_config.max_safe if param_config else None
        } if param_config else None,
        "values": [
            {
                "timestamp": h.prt,
                "value": h.prv
            }
            for h in history
        ]
    }


@router.get("/dashboard/{station_code}")
async def get_dashboard_data(
    station_code: str,
    api_key: bool = Depends(verify_api_key),
    db: Session = Depends(get_db)
):
    """
    Get comprehensive dashboard data for a station.
    Includes consolidated metrics, alerts summary, telemetry summary, and health status.
    """
    station = db.query(Station).filter(Station.station_code == station_code).first()
    if not station:
        raise HTTPException(status_code=404, detail=f"Station {station_code} not found")
    
    gateway = db.query(Gateway).filter(Gateway.station_id == station.id).first()
    
    # Get alerts summary (last 24 hours)
    end_time = datetime.utcnow()
    start_time = end_time - timedelta(hours=24)
    
    alerts = db.query(AlertEvent).filter(
        AlertEvent.station_id == station.id,
        AlertEvent.alert_time >= start_time
    ).all()
    
    alert_summary = {
        "total": len(alerts),
        "failure": len([a for a in alerts if a.alert_type == "Failure"]),
        "predictive": len([a for a in alerts if a.alert_type == "Predictive"]),
        "pending": len([a for a in alerts if a.alert_status == "Active"]),
        "by_cause": {}
    }
    
    for alert in alerts:
        cause = alert.cause
        if cause not in alert_summary["by_cause"]:
            alert_summary["by_cause"][cause] = 0
        alert_summary["by_cause"][cause] += 1
    
    # Consolidate real-time statistics for the dashboard cards
    total_assets = db.query(Asset).filter(Asset.station_id == station.id).count()
    active_failures = db.query(AlertEvent).filter(
        AlertEvent.station_id == station.id,
        AlertEvent.alert_status == "Active",
        AlertEvent.alert_type == "Failure"
    ).count()
    active_predictive = db.query(AlertEvent).filter(
        AlertEvent.station_id == station.id,
        AlertEvent.alert_status == "Active",
        AlertEvent.alert_type == "Predictive"
    ).count()
    
    system_health_val = 100.0 - (active_failures * 5.0) - (active_predictive * 2.0)
    system_health_val = max(50.0, min(100.0, system_health_val))
    
    gateway_health_val = 100.0
    if gateway:
        gateway_info = await redis_service.get_gateway_info(gateway.stngw_id)
        if gateway_info and gateway_info.get("status") == "faulty":
            gateway_health_val = 0.0
            
    # Calculate Prediction Accuracy
    prediction_accuracy_val = 91.0
    if gateway:
        stats = await statistics_service.calculate_alert_statistics(stngw_id=gateway.stngw_id)
        if stats and stats.get("predictive_success_rate", 0.0) > 0.0:
            prediction_accuracy_val = round(stats["predictive_success_rate"], 1)
            
    # Calculate MTTR (Mean Time to Repair) in hours for cleared alerts
    cleared_alerts = db.query(AlertEvent).filter(
        AlertEvent.station_id == station.id,
        AlertEvent.alert_status == "Cleared",
        AlertEvent.rectification_time.isnot(None),
        AlertEvent.alert_time.isnot(None)
    ).all()
    
    total_hours = 0.0
    cleared_count = 0
    for a in cleared_alerts:
        diff = (a.rectification_time - a.alert_time).total_seconds() / 3600.0
        if diff > 0:
            total_hours += diff
            cleared_count += 1
            
    mttr_val = round(total_hours / cleared_count, 1) if cleared_count > 0 else 4.2

    # Get health status
    health_status = {
        "gateway": "unknown",
        "sensors": {"total": 0, "healthy": 0, "faulty": 0},
        "iot": {"total": 0, "healthy": 0, "faulty": 0}
    }
    
    if gateway:
        # Get gateway health from Redis
        gateway_info = await redis_service.get_gateway_info(gateway.stngw_id)
        if gateway_info:
            health_status["gateway"] = "healthy" if gateway_info.get("status") == "healthy" else "faulty"
        
        # Get sensor health summary
        sensor_health = await redis_service.get_sensor_health_summary(gateway.stngw_id)
        health_status["sensors"] = sensor_health
        
        # Get IoT health summary
        iot_health = await redis_service.get_iot_health_summary(gateway.stngw_id)
        health_status["iot"] = iot_health
    
    # Get latest telemetry summary
    telemetry_summary = {
        "total_parameters": 0,
        "updated_in_last_hour": 0,
        "latest_timestamp": None
    }
    
    if gateway:
        latest_values = await redis_service.get_all_latest_parameters(gateway.stngw_id)
        telemetry_summary["total_parameters"] = len(latest_values)
        
        # Count parameters updated in last hour
        one_hour_ago = datetime.utcnow() - timedelta(hours=1)
        for pid, data in latest_values.items():
            if data.get("timestamp"):
                try:
                    ts = datetime.strptime(data["timestamp"], '%d-%m-%Y %H:%M:%S.%f')
                    if ts > one_hour_ago:
                        telemetry_summary["updated_in_last_hour"] += 1
                except:
                    pass
        
        # Get latest timestamp
        if latest_values:
            latest_ts = max(
                [data.get("timestamp") for data in latest_values.values() if data.get("timestamp")],
                default=None
            )
            telemetry_summary["latest_timestamp"] = latest_ts
    
    return {
        "station_code": station_code,
        "station_name": station.station_name,
        "timestamp": datetime.now().isoformat(),
        "metrics": {
            "total_assets": total_assets,
            "failures": active_failures,
            "system_health": system_health_val,
            "gateway_health": gateway_health_val,
            "prediction_accuracy": prediction_accuracy_val,
            "mttr_hours": mttr_val
        },
        "alerts": alert_summary,
        "health": health_status,
        "telemetry": telemetry_summary,
        "gateway_status": "online" if gateway else "offline"
    }


@router.get("/asset-status/{station_code}/{asset_no}")
async def get_asset_status(
    station_code: str,
    asset_no: str,
    api_key: bool = Depends(verify_api_key),
    db: Session = Depends(get_db)
):
    """
    Get comprehensive status for a specific asset.
    Includes live telemetry, active alerts, and health status.
    """
    station = db.query(Station).filter(Station.station_code == station_code).first()
    if not station:
        raise HTTPException(status_code=404, detail=f"Station {station_code} not found")
    
    gateway = db.query(Gateway).filter(Gateway.station_id == station.id).first()
    if not gateway:
        raise HTTPException(status_code=404, detail="Gateway not found")
    
    # Get asset
    asset = db.query(Asset).filter(
        Asset.station_id == station.id,
        Asset.asset_number_code == asset_no
    ).first()
    
    if not asset:
        raise HTTPException(status_code=404, detail=f"Asset {asset_no} not found")
    
    # Get active alerts for this asset
    active_alerts = db.query(AlertEvent).filter(
        AlertEvent.station_id == station.id,
        AlertEvent.asset_no == asset_no,
        AlertEvent.alert_status == "Active"
    ).all()
    
    # Get latest parameters for this asset
    asset_params = [p.para_id for p in asset.parameters] if asset.parameters else []
    latest_values = {}
    
    for para_id in asset_params:
        val = await redis_service.get_latest_parameter(gateway.stngw_id, para_id)
        if val:
            latest_values[para_id] = val
    
    # Get sensor health for this asset
    sensor_health = {}
    for para_id in asset_params:
        health = await redis_service.get_sensor_health(gateway.stngw_id, para_id)
        if health:
            sensor_health[para_id] = health
    
    return {
        "station_code": station_code,
        "asset_number_code": asset.asset_number_code,
        "asset_type_hex": asset.asset_type_hex,
        "asset_make": asset.make,
        "asset_model": asset.model,
        "timestamp": datetime.now().isoformat(),
        "parameters": latest_values,
        "active_alerts": [
            {
                "id": alert.id,
                "alert_type": alert.alert_type,
                "cause": alert.cause,
                "cause_detail": alert.remark or "",
                "time": alert.alert_time.isoformat() if alert.alert_time else datetime.utcnow().isoformat()
            }
            for alert in active_alerts
        ],
        "sensor_health": sensor_health,
        "status": "active" if not active_alerts else "alerting"
    }
