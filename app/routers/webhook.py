import re
import json
import math
import logging
from datetime import datetime, timezone
from typing import List, Optional, Union
from fastapi import APIRouter, Depends, HTTPException, Security
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session
from prometheus_client import Counter, Histogram

from app.database import get_db, settings
from app.models.models import Gateway, Telemetry, AssetParameter, Asset, AlertEvent
from app.routers.gateway import _resolve_station_from_stngw_id, _offset_event_timestamp

router = APIRouter(prefix="/webhook", tags=["Webhook Ingestion"])
logger = logging.getLogger("webhook")

# ============ Metrics Collection ============

webhook_requests = Counter(
    'webhook_requests_total',
    'Total webhook requests',
    ['endpoint', 'status']
)

webhook_latency = Histogram(
    'webhook_latency_seconds',
    'Webhook processing latency',
    ['endpoint']
)

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

# ============ Helper Functions ============

def normalize_timestamp(timestamp: str) -> str:
    """
    Ensure timestamp has exactly 3 decimal places for milliseconds: DD-MM-YYYY HH:mm:ss.SSS
    """
    timestamp = timestamp.strip()
    if '.' in timestamp:
        main, ms = timestamp.rsplit('.', 1)
        # Pad or truncate milliseconds to 3 digits
        ms = ms[:3].ljust(3, '0')
        return f"{main}.{ms}"
    else:
        return f"{timestamp}.000"

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

BATCH_SIZE = 1000

def _batch_insert(records: List[Telemetry], db: Session):
    """
    Batch insert telemetry records to avoid memory issues with large payloads.
    """
    for i in range(0, len(records), BATCH_SIZE):
        batch = records[i:i+BATCH_SIZE]
        db.add_all(batch)
        db.flush()

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

    @field_validator('prv')
    @classmethod
    def validate_values(cls, v: List[float]) -> List[float]:
        for val in v:
            if math.isnan(val) or math.isinf(val):
                raise ValueError(f'Invalid value: {val} (NaN or Infinity)')
        return v
    
    @field_validator('prt')
    @classmethod
    def validate_timestamps(cls, v: List[str], info) -> List[str]:
        if not v:
            raise ValueError('prt cannot be empty')
        # Access sibling fields from validation context (if present)
        prv = info.data.get('prv')
        if prv is not None and len(v) != len(prv):
            raise ValueError('Length of prt must match length of prv')
        
        normalized = []
        for timestamp in v:
            norm_ts = normalize_timestamp(timestamp)
            try:
                datetime.strptime(norm_ts, '%d-%m-%Y %H:%M:%S.%f')
            except ValueError:
                raise ValueError(f'Invalid timestamp format: {timestamp}. Expected DD-MM-YYYY HH:mm:ss.SSS')
            normalized.append(norm_ts)
        return normalized

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

    @field_validator('prv')
    @classmethod
    def validate_values(cls, v: List[float]) -> List[float]:
        for val in v:
            if math.isnan(val) or math.isinf(val):
                raise ValueError(f'Invalid value: {val} (NaN or Infinity)')
        return v
    
    @field_validator('prt')
    @classmethod
    def validate_timestamp(cls, v: str) -> str:
        norm_ts = normalize_timestamp(v)
        try:
            datetime.strptime(norm_ts, '%d-%m-%Y %H:%M:%S.%f')
        except ValueError:
            raise ValueError(f'Invalid timestamp format: {v}. Expected DD-MM-YYYY HH:mm:ss.SSS')
        return norm_ts

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
        norm_ts = normalize_timestamp(v)
        try:
            datetime.strptime(norm_ts, '%d-%m-%Y %H:%M:%S.%f')
        except ValueError:
            raise ValueError(f'Invalid timestamp format: {v}. Expected DD-MM-YYYY HH:mm:ss.SSS')
        return norm_ts

class ConfigData(BaseModel):
    config_id: str = Field(..., description="Configuration ID (one byte hex)")
    config_val: float = Field(..., description="Configuration value")

class ConfigWebhookPayload(BaseWebhookPayload):
    cmd: str = Field("CONFIG", description="Command type")
    config: List[ConfigData]

# ============ Endpoints ============

@router.post("/parameters/fixed", status_code=200)
def receive_fixed_parameters(
    payload: FixedParameterWebhookPayload,
    db: Session = Depends(get_db),
    api_key: bool = Depends(verify_api_key)
):
    """
    Receive fixed-interval parameter data (every 5 sec). Supports batch processing and partial success responses.
    """
    logger.info(f"RQI: {payload.rqi} | GW: {payload.stngw_id} | Fixed parameters ingestion start.")
    with webhook_latency.labels('fixed').time():
        try:
            stngw_id = payload.stngw_id.upper().strip()
            gateway = _get_or_create_gateway_with_station(stngw_id, db)

            # Pre-resolve existing keys & known parameters
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
            errors = []
            records_to_insert = []

            for param in payload.parameters:
                para_id_upper = param.para_id.upper()
                try:
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
                        records_to_insert.append(record)
                        saved_count += 1
                except Exception as e:
                    errors.append({
                        "para_id": param.para_id,
                        "error": str(e)
                    })

            if records_to_insert:
                _batch_insert(records_to_insert, db)
            db.commit()
            
            status_msg = "success"
            if errors:
                status_msg = "partial_success" if saved_count > 0 else "failed"

            response_data = {
                "status": status_msg,
                "rqi": payload.rqi,
                "message": f"Processed parameters: saved={saved_count}, skipped={duplicate_count}, errors={len(errors)}",
                "records_saved": saved_count,
                "duplicates_skipped": duplicate_count,
                "errors": errors
            }
            logger.info(f"RQI: {payload.rqi} | GW: {payload.stngw_id} | Fixed parameters ingestion complete: {response_data['message']}")
            webhook_requests.labels('fixed', status_msg).inc()
            return response_data
        except HTTPException as e:
            webhook_requests.labels('fixed', 'error').inc()
            raise
        except Exception as e:
            db.rollback()
            logger.error(f"RQI: {payload.rqi} | GW: {payload.stngw_id} | Fixed parameters ingestion failed: {str(e)}")
            webhook_requests.labels('fixed', 'error').inc()
            raise HTTPException(status_code=500, detail=str(e))

@router.post("/parameters/event", status_code=200)
def receive_event_parameters(
    payload: EventParameterWebhookPayload,
    db: Session = Depends(get_db),
    api_key: bool = Depends(verify_api_key)
):
    """
    Receive event-based parameter data (Point machine/ELB current sampled every 20ms). Supports batching and partial success.
    """
    logger.info(f"RQI: {payload.rqi} | GW: {payload.stngw_id} | Event parameters ingestion start.")
    with webhook_latency.labels('event').time():
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
            errors = []
            records_to_insert = []

            for param in payload.parameters:
                para_id_upper = param.para_id.upper()
                try:
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
                        records_to_insert.append(record)
                        saved_count += 1
                except Exception as e:
                    errors.append({
                        "para_id": param.para_id,
                        "error": str(e)
                    })

            if records_to_insert:
                _batch_insert(records_to_insert, db)
            db.commit()
            
            status_msg = "success"
            if errors:
                status_msg = "partial_success" if saved_count > 0 else "failed"

            response_data = {
                "status": status_msg,
                "rqi": payload.rqi,
                "message": f"Processed event parameters: saved={saved_count}, skipped={duplicate_count}, errors={len(errors)}",
                "records_saved": saved_count,
                "duplicates_skipped": duplicate_count,
                "errors": errors
            }
            logger.info(f"RQI: {payload.rqi} | GW: {payload.stngw_id} | Event parameters ingestion complete: {response_data['message']}")
            webhook_requests.labels('event', status_msg).inc()
            return response_data
        except HTTPException as e:
            webhook_requests.labels('event', 'error').inc()
            raise
        except Exception as e:
            db.rollback()
            logger.error(f"RQI: {payload.rqi} | GW: {payload.stngw_id} | Event parameters ingestion failed: {str(e)}")
            webhook_requests.labels('event', 'error').inc()
            raise HTTPException(status_code=500, detail=str(e))

@router.post("/health", status_code=200)
def receive_health_data(
    payload: HealthWebhookPayload,
    db: Session = Depends(get_db),
    api_key: bool = Depends(verify_api_key)
):
    """
    Receive health status of sensors and gateway. Raises alerts if faulty, resolves alerts when healthy.
    """
    logger.info(f"RQI: {payload.rqi} | GW: {payload.stngw_id} | Health diagnostic ingestion start.")
    with webhook_latency.labels('health').time():
        try:
            stngw_id = payload.stngw_id.upper().strip()
            gateway = _get_or_create_gateway_with_station(stngw_id, db)

            alerts_created = 0
            alerts_resolved = 0

            # Gateway health check
            if payload.stngw_health:
                is_healthy = (payload.stngw_health.stngwh_id == "00")
                if is_healthy:
                    # Clear active GATEWAY_FAULTY alert for this station
                    existing_alerts = db.query(AlertEvent).filter(
                        AlertEvent.station_id == gateway.station_id,
                        AlertEvent.alert_type == "Failure",
                        AlertEvent.asset_no == "GATEWAY",
                        AlertEvent.cause == "GATEWAY_FAULTY",
                        AlertEvent.alert_status == "Active"
                    ).all()
                    for alert in existing_alerts:
                        alert.alert_status = "Cleared"
                        alert.rectification_time = datetime.now(timezone.utc)
                        alert.remark = "Resolved automatically: Gateway reported healthy status code 00."
                        alerts_resolved += 1
                else:
                    try:
                        norm_t = normalize_timestamp(payload.stngw_health.stngwh_t)
                        alert_time = datetime.strptime(norm_t, '%d-%m-%Y %H:%M:%S.%f')
                    except ValueError:
                        alert_time = datetime.now(timezone.utc)

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
                    
                    ap = db.query(AssetParameter).filter(AssetParameter.para_id == sensor.para_id.upper()).first()
                    asset_id = ap.asset_id if ap else None
                    asset = db.query(Asset).filter(Asset.id == asset_id).first() if asset_id else None
                    asset_no = asset.asset_number_code if asset else "UNKNOWN"
                    asset_type_hex = asset.asset_type_hex if asset else "00"

                    if is_healthy:
                        # Clear active SENSOR_FAULTY alert for this station/asset/parameter
                        existing_alerts = db.query(AlertEvent).filter(
                            AlertEvent.station_id == gateway.station_id,
                            AlertEvent.alert_type == "Failure",
                            AlertEvent.asset_no == asset_no,
                            AlertEvent.cause == f"SENSOR_FAULTY_{sensor.para_id.upper()}",
                            AlertEvent.alert_status == "Active"
                        ).all()
                        for alert in existing_alerts:
                            alert.alert_status = "Cleared"
                            alert.rectification_time = datetime.now(timezone.utc)
                            alert.remark = f"Resolved automatically: Sensor parameter {sensor.para_id} reported healthy status code 00."
                            alerts_resolved += 1
                    else:
                        try:
                            norm_t = normalize_timestamp(sensor.sh_t)
                            alert_time = datetime.strptime(norm_t, '%d-%m-%Y %H:%M:%S.%f')
                        except ValueError:
                            alert_time = datetime.now(timezone.utc)

                        existing_alert = db.query(AlertEvent).filter(
                            AlertEvent.station_id == gateway.station_id,
                            AlertEvent.alert_type == "Failure",
                            AlertEvent.asset_no == asset_no,
                            AlertEvent.cause == f"SENSOR_FAULTY_{sensor.para_id.upper()}",
                            AlertEvent.alert_status == "Active"
                        ).first()

                        if not existing_alert:
                            alert = AlertEvent(
                                station_id=gateway.station_id,
                                alert_type="Failure",
                                asset_type_hex=asset_type_hex,
                                asset_no=asset_no,
                                cause=f"SENSOR_FAULTY_{sensor.para_id.upper()}",
                                alert_status="Active",
                                acknowledged=False,
                                alert_time=alert_time,
                                remark=f"Sensor parameter {sensor.para_id} reported unhealthy status code 01.",
                                asset_id=asset_id
                            )
                            db.add(alert)
                            alerts_created += 1

            db.commit()
            response_data = {
                "status": "success",
                "rqi": payload.rqi,
                "message": f"Health data processed: alerts_created={alerts_created}, alerts_resolved={alerts_resolved}",
                "alerts_created": alerts_created,
                "alerts_resolved": alerts_resolved
            }
            logger.info(f"RQI: {payload.rqi} | GW: {payload.stngw_id} | Health diagnostic complete: {response_data['message']}")
            webhook_requests.labels('health', 'success').inc()
            return response_data
        except HTTPException as e:
            webhook_requests.labels('health', 'error').inc()
            raise
        except Exception as e:
            db.rollback()
            logger.error(f"RQI: {payload.rqi} | GW: {payload.stngw_id} | Health diagnostic failed: {str(e)}")
            webhook_requests.labels('health', 'error').inc()
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
    logger.info(f"RQI: {payload.rqi} | GW: {payload.stngw_id} | Gateway discovery start.")
    with webhook_latency.labels('discovery').time():
        try:
            stngw_id = payload.stngw_id.upper().strip()
            gateway = _get_or_create_gateway_with_station(stngw_id, db)

            db.commit()
            response_data = {
                "status": "success",
                "rqi": payload.rqi,
                "message": "Gateway registered successfully",
                "action": {
                    "time_sync": "pending",
                    "info_request": "pending",
                    "image_request": "pending"
                }
            }
            logger.info(f"RQI: {payload.rqi} | GW: {payload.stngw_id} | Gateway discovery complete.")
            webhook_requests.labels('discovery', 'success').inc()
            return response_data
        except HTTPException as e:
            webhook_requests.labels('discovery', 'error').inc()
            raise
        except Exception as e:
            db.rollback()
            logger.error(f"RQI: {payload.rqi} | GW: {payload.stngw_id} | Gateway discovery failed: {str(e)}")
            webhook_requests.labels('discovery', 'error').inc()
            raise HTTPException(status_code=500, detail=str(e))

@router.post("/time_sync_confirm", status_code=200)
def receive_time_sync_confirm(
    payload: TimeSyncWebhookPayload,
    api_key: bool = Depends(verify_api_key)
):
    """
    Receive time sync confirmation.
    """
    logger.info(f"RQI: {payload.rqi} | GW: {payload.stngw_id} | Time sync confirmation received.")
    with webhook_latency.labels('time_sync_confirm').time():
        webhook_requests.labels('time_sync_confirm', 'success').inc()
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
    logger.info(f"RQI: {payload.rqi} | GW: {payload.stngw_id} | Config confirmation received. Items count={len(payload.config)}")
    with webhook_latency.labels('config_confirm').time():
        webhook_requests.labels('config_confirm', 'success').inc()
        return {
            "status": "success",
            "rqi": payload.rqi,
            "message": "Configuration confirmed",
            "config_items": len(payload.config)
        }
