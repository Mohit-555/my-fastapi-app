import re
import json
from datetime import datetime
from typing import List, Optional, Union
from fastapi import APIRouter, Depends, HTTPException, Security
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.database import get_db, settings
from app.models.models import Gateway, Telemetry, AssetParameter, Asset, AlertEvent
from app.routers.gateway import _resolve_station_from_stngw_id, _offset_event_timestamp

router = APIRouter(prefix="/webhook", tags=["Webhook Ingestion"])

# ============ Authentication ============

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

def verify_api_key(api_key: Optional[str] = Security(api_key_header)) -> bool:
    if not api_key:
        raise HTTPException(
            status_code=401,
            detail="API key missing. Please provide X-API-Key header."
        )
    if api_key != settings.API_KEY:
        raise HTTPException(
            status_code=401,
            detail="Invalid API key."
        )
    return True

# ============ Schemas ============

class BaseWebhookPayload(BaseModel):
    rqi: str = Field(..., description="Unique request ID")
    stngw_id: str = Field(..., description="4 Byte hexadecimal station gateway ID")
    
    @field_validator('stngw_id')
    @classmethod
    def validate_stngw_id(cls, v: str) -> str:
        if not re.match(r'^[0-9A-Fa-f]{8}$', v):
            raise ValueError('stngw_id must be 8 character hexadecimal string')
        return v.upper()

class ParameterData(BaseModel):
    para_id: str = Field(..., description="4 Byte hexadecimal parameter ID")
    prv: List[float] = Field(..., description="List of parameter values")
    prt: List[str] = Field(..., description="List of timestamps")
    
    @field_validator('para_id')
    @classmethod
    def validate_para_id(cls, v: str) -> str:
        if not re.match(r'^[0-9A-Fa-f]{8}$', v):
            raise ValueError('para_id must be 8 character hexadecimal string')
        return v.upper()
    
    @field_validator('prt')
    @classmethod
    def validate_timestamps(cls, v: List[str], info) -> List[str]:
        if not v:
            raise ValueError('prt cannot be empty')
        # Access sibling fields from validation context (if present)
        prv = info.data.get('prv')
        if prv is not None and len(v) != len(prv):
            raise ValueError('Length of prt must match length of prv')
        for timestamp in v:
            try:
                datetime.strptime(timestamp.strip(), '%d-%m-%Y %H:%M:%S.%f')
            except ValueError:
                raise ValueError(f'Invalid timestamp format: {timestamp}. Expected DD-MM-YYYY HH:mm:ss.SSS')
        return v

class FixedParameterWebhookPayload(BaseWebhookPayload):
    parameters: List[ParameterData]

class EventParameterData(BaseModel):
    para_id: str = Field(..., description="4 Byte hexadecimal parameter ID")
    prv: List[float] = Field(..., description="List of event parameter values")
    prt: str = Field(..., description="Base timestamp for event")
    
    @field_validator('para_id')
    @classmethod
    def validate_para_id(cls, v: str) -> str:
        if not re.match(r'^[0-9A-Fa-f]{8}$', v):
            raise ValueError('para_id must be 8 character hexadecimal string')
        return v.upper()
    
    @field_validator('prt')
    @classmethod
    def validate_timestamp(cls, v: str) -> str:
        try:
            datetime.strptime(v.strip(), '%d-%m-%Y %H:%M:%S.%f')
        except ValueError:
            raise ValueError(f'Invalid timestamp format: {v}. Expected DD-MM-YYYY HH:mm:ss.SSS')
        return v

class EventParameterWebhookPayload(BaseWebhookPayload):
    parameters: List[EventParameterData]

class SensorHealthData(BaseModel):
    para_id: str
    sh_id: str = Field(..., description="00=Healthy, 01=Faulty")
    sh_t: str = Field(..., description="Timestamp")
    
    @field_validator('sh_id')
    @classmethod
    def validate_health_id(cls, v: str) -> str:
        if v not in ['00', '01']:
            raise ValueError('sh_id must be 00 (Healthy) or 01 (Faulty)')
        return v

class IoTHealthData(BaseModel):
    imei: str = Field(..., description="IMEI number")
    ioth_id: str = Field(..., description="00=Healthy, 01=Faulty")
    ioth_t: str = Field(..., description="Timestamp")
    
    @field_validator('ioth_id')
    @classmethod
    def validate_health_id(cls, v: str) -> str:
        if v not in ['00', '01']:
            raise ValueError('ioth_id must be 00 (Healthy) or 01 (Faulty)')
        return v

class GatewayHealthData(BaseModel):
    stngwh_id: str = Field(..., description="00=Healthy, 01=Faulty")
    stngwh_t: str = Field(..., description="Timestamp")
    
    @field_validator('stngwh_id')
    @classmethod
    def validate_health_id(cls, v: str) -> str:
        if v not in ['00', '01']:
            raise ValueError('stngwh_id must be 00 (Healthy) or 01 (Faulty)')
        return v

class NetworkHealthData(BaseModel):
    neth_id: str = Field(..., description="00=Healthy, 01=Faulty")
    net_des: str = Field(..., description="Network description")
    neth_t: str = Field(..., description="Timestamp")
    
    @field_validator('neth_id')
    @classmethod
    def validate_health_id(cls, v: str) -> str:
        if v not in ['00', '01']:
            raise ValueError('neth_id must be 00 (Healthy) or 01 (Faulty)')
        return v

class HealthWebhookPayload(BaseWebhookPayload):
    sensor_health: Optional[List[SensorHealthData]] = None
    iot_health: Optional[List[IoTHealthData]] = None
    stngw_health: Optional[GatewayHealthData] = None
    network_health: Optional[List[NetworkHealthData]] = None

class DiscoveryWebhookPayload(BaseWebhookPayload):
    vcc: str = Field(..., description="Vendor code of RDPMS Application")
    vgc: str = Field(..., description="Vendor code of station field devices")
    stngw_ver: str = Field(..., description="Version of station gateway software")

class TimeSyncWebhookPayload(BaseWebhookPayload):
    cmd: str = Field("TIME_SYNC", description="Command type")
    clt: str = Field(..., description="Timestamp from RDPMS Application")
    
    @field_validator('clt')
    @classmethod
    def validate_timestamp(cls, v: str) -> str:
        try:
            datetime.strptime(v.strip(), '%d-%m-%Y %H:%M:%S.%f')
        except ValueError:
            raise ValueError(f'Invalid timestamp format: {v}. Expected DD-MM-YYYY HH:mm:ss.SSS')
        return v

class ConfigData(BaseModel):
    config_id: str = Field(..., description="Configuration ID (one byte hex)")
    config_val: float = Field(..., description="Configuration value")

class ConfigWebhookPayload(BaseWebhookPayload):
    cmd: str = Field("CONFIG", description="Command type")
    config: List[ConfigData]

# ============ Helper ============

def _get_or_create_gateway_with_station(stngw_id: str, db: Session) -> Gateway:
    stngw_id = stngw_id.upper().strip()
    gateway = db.query(Gateway).filter(Gateway.stngw_id == stngw_id).first()
    if not gateway:
        station_id = _resolve_station_from_stngw_id(stngw_id, db)
        gateway = Gateway(stngw_id=stngw_id, station_id=station_id)
        db.add(gateway)
        db.flush()
    else:
        if gateway.station_id is None:
            gateway.station_id = _resolve_station_from_stngw_id(stngw_id, db)
            db.flush()
    
    if gateway.station_id is None:
        raise HTTPException(
            status_code=400,
            detail=f"Station gateway ID '{stngw_id}' is not mapped to any registered station. Please register the station with zone/division/station hex codes matching this gateway ID."
        )
    return gateway

# ============ Endpoints ============

@router.post("/parameters/fixed", status_code=200)
def receive_fixed_parameters(
    payload: FixedParameterWebhookPayload,
    db: Session = Depends(get_db),
    api_key: bool = Depends(verify_api_key)
):
    """
    Receive fixed-interval parameter data (every 5 sec).
    """
    try:
        stngw_id = payload.stngw_id.upper().strip()
        gateway = _get_or_create_gateway_with_station(stngw_id, db)

        candidate_para_ids = {p.para_id.upper() for p in payload.parameters if p.para_id}
        existing_keys = set()
        if candidate_para_ids:
            existing_rows = (
                db.query(Telemetry.para_id, Telemetry.prt, Telemetry.prv)
                .filter(
                    Telemetry.gateway_id == gateway.id,
                    Telemetry.para_id.in_(candidate_para_ids),
                )
                .all()
            )
            existing_keys = {(r.para_id, r.prt, r.prv) for r in existing_rows}

            known_para_ids = {
                r.para_id for r in
                db.query(AssetParameter.para_id)
                .filter(AssetParameter.para_id.in_(candidate_para_ids))
                .all()
            }
            for pid in candidate_para_ids - known_para_ids:
                db.add(AssetParameter(para_id=pid, asset_id=None, prloc=None, is_assigned=False))
            if candidate_para_ids - known_para_ids:
                db.flush()

        saved_count = 0
        duplicate_count = 0

        for param in payload.parameters:
            para_id_upper = param.para_id.upper()
            for i, value in enumerate(param.prv):
                timestamp = param.prt[i]
                dedup_key = (para_id_upper, timestamp, value)
                if dedup_key in existing_keys:
                    duplicate_count += 1
                    continue
                existing_keys.add(dedup_key)

                record = Telemetry(
                    gateway_id=gateway.id,
                    para_id=para_id_upper,
                    prv=value,
                    prt=timestamp,
                    raw_payload=json.dumps({
                        "rqi": payload.rqi,
                        "stngw_id": stngw_id,
                        "para_id": param.para_id,
                        "prv": value,
                        "prt": timestamp,
                        "packet_type": "fixed_interval_5_9"
                    })
                )
                db.add(record)
                saved_count += 1
        
        db.commit()
        return {
            "status": "success",
            "rqi": payload.rqi,
            "message": f"Processed {len(payload.parameters)} parameters",
            "records_saved": saved_count,
            "duplicates_skipped": duplicate_count
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/parameters/event", status_code=200)
def receive_event_parameters(
    payload: EventParameterWebhookPayload,
    db: Session = Depends(get_db),
    api_key: bool = Depends(verify_api_key)
):
    """
    Receive event-based parameter data (Point machine/ELB current sampled every 20ms).
    """
    try:
        stngw_id = payload.stngw_id.upper().strip()
        gateway = _get_or_create_gateway_with_station(stngw_id, db)

        candidate_para_ids = {p.para_id.upper() for p in payload.parameters if p.para_id}
        existing_keys = set()
        if candidate_para_ids:
            existing_rows = (
                db.query(Telemetry.para_id, Telemetry.prt, Telemetry.prv)
                .filter(
                    Telemetry.gateway_id == gateway.id,
                    Telemetry.para_id.in_(candidate_para_ids),
                )
                .all()
            )
            existing_keys = {(r.para_id, r.prt, r.prv) for r in existing_rows}

            known_para_ids = {
                r.para_id for r in
                db.query(AssetParameter.para_id)
                .filter(AssetParameter.para_id.in_(candidate_para_ids))
                .all()
            }
            for pid in candidate_para_ids - known_para_ids:
                db.add(AssetParameter(para_id=pid, asset_id=None, prloc=None, is_assigned=False))
            if candidate_para_ids - known_para_ids:
                db.flush()

        saved_count = 0
        duplicate_count = 0

        for param in payload.parameters:
            para_id_upper = param.para_id.upper()
            for i, value in enumerate(param.prv):
                timestamp = _offset_event_timestamp(param.prt, i, 20)
                dedup_key = (para_id_upper, timestamp, value)
                if dedup_key in existing_keys:
                    duplicate_count += 1
                    continue
                existing_keys.add(dedup_key)

                record = Telemetry(
                    gateway_id=gateway.id,
                    para_id=para_id_upper,
                    prv=value,
                    prt=timestamp,
                    raw_payload=json.dumps({
                        "rqi": payload.rqi,
                        "stngw_id": stngw_id,
                        "para_id": param.para_id,
                        "prv": value,
                        "prt": timestamp,
                        "packet_type": "event_based_5_10"
                    })
                )
                db.add(record)
                saved_count += 1
        
        db.commit()
        return {
            "status": "success",
            "rqi": payload.rqi,
            "message": f"Processed {len(payload.parameters)} event parameters",
            "records_saved": saved_count,
            "duplicates_skipped": duplicate_count
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/health", status_code=200)
def receive_health_data(
    payload: HealthWebhookPayload,
    db: Session = Depends(get_db),
    api_key: bool = Depends(verify_api_key)
):
    """
    Receive health status of sensors and gateway, firing database alerts if faulty.
    """
    try:
        stngw_id = payload.stngw_id.upper().strip()
        gateway = _get_or_create_gateway_with_station(stngw_id, db)

        alerts_created = 0

        # Gateway health check
        if payload.stngw_health:
            is_healthy = (payload.stngw_health.stngwh_id == "00")
            if not is_healthy:
                try:
                    alert_time = datetime.strptime(payload.stngw_health.stngwh_t.strip(), '%d-%m-%Y %H:%M:%S.%f')
                except ValueError:
                    alert_time = datetime.utcnow()

                existing_alert = db.query(AlertEvent).filter(
                    AlertEvent.station_id == gateway.station_id,
                    AlertEvent.alert_type == "Failure",
                    AlertEvent.asset_no == "GATEWAY",
                    AlertEvent.cause == "GATEWAY_FAULTY",
                    AlertEvent.alert_status == "Active"
                ).first()

                if not existing_alert:
                    alert = AlertEvent(
                        station_id=gateway.station_id,
                        alert_type="Failure",
                        asset_type_hex="00",
                        asset_no="GATEWAY",
                        cause="GATEWAY_FAULTY",
                        alert_status="Active",
                        acknowledged=False,
                        alert_time=alert_time,
                        remark="Gateway reported unhealthy status code 01."
                    )
                    db.add(alert)
                    alerts_created += 1

        # Sensor health check
        if payload.sensor_health:
            for sensor in payload.sensor_health:
                is_healthy = (sensor.sh_id == "00")
                if not is_healthy:
                    try:
                        alert_time = datetime.strptime(sensor.sh_t.strip(), '%d-%m-%Y %H:%M:%S.%f')
                    except ValueError:
                        alert_time = datetime.utcnow()

                    ap = db.query(AssetParameter).filter(AssetParameter.para_id == sensor.para_id.upper()).first()
                    asset_id = ap.asset_id if ap else None
                    asset = db.query(Asset).filter(Asset.id == asset_id).first() if asset_id else None
                    asset_no = asset.asset_number_code if asset else "UNKNOWN"
                    asset_type_hex = asset.asset_type_hex if asset else "00"

                    existing_alert = db.query(AlertEvent).filter(
                        AlertEvent.station_id == gateway.station_id,
                        AlertEvent.alert_type == "Failure",
                        AlertEvent.asset_no == asset_no,
                        AlertEvent.cause == f"SENSOR_FAULTY_{sensor.para_id}",
                        AlertEvent.alert_status == "Active"
                    ).first()

                    if not existing_alert:
                        alert = AlertEvent(
                            station_id=gateway.station_id,
                            alert_type="Failure",
                            asset_type_hex=asset_type_hex,
                            asset_no=asset_no,
                            cause=f"SENSOR_FAULTY_{sensor.para_id}",
                            alert_status="Active",
                            acknowledged=False,
                            alert_time=alert_time,
                            remark=f"Sensor parameter {sensor.para_id} reported unhealthy status code 01.",
                            asset_id=asset_id
                        )
                        db.add(alert)
                        alerts_created += 1

        db.commit()
        return {
            "status": "success",
            "rqi": payload.rqi,
            "message": "Health data processed successfully",
            "alerts_created": alerts_created
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/discovery", status_code=200)
def receive_discovery(
    payload: DiscoveryWebhookPayload,
    db: Session = Depends(get_db),
    api_key: bool = Depends(verify_api_key)
):
    """
    Receive gateway discovery on startup/reboot.
    """
    try:
        stngw_id = payload.stngw_id.upper().strip()
        gateway = _get_or_create_gateway_with_station(stngw_id, db)

        db.commit()
        return {
            "status": "success",
            "rqi": payload.rqi,
            "message": "Gateway registered successfully",
            "action": {
                "time_sync": "pending",
                "info_request": "pending",
                "image_request": "pending"
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/time_sync_confirm", status_code=200)
def receive_time_sync_confirm(
    payload: TimeSyncWebhookPayload,
    api_key: bool = Depends(verify_api_key)
):
    """
    Receive time sync confirmation.
    """
    return {
        "status": "success",
        "rqi": payload.rqi,
        "message": "Time sync confirmed"
    }

@router.post("/config_confirm", status_code=200)
def receive_config_confirm(
    payload: ConfigWebhookPayload,
    api_key: bool = Depends(verify_api_key)
):
    """
    Receive configuration confirmation.
    """
    return {
        "status": "success",
        "rqi": payload.rqi,
        "message": "Configuration confirmed",
        "config_items": len(payload.config)
    }
