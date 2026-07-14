import re
import json
import math
import logging
import asyncio
from datetime import datetime, timezone
from typing import List, Optional, Union
from fastapi import APIRouter, Depends, HTTPException, Security, Request
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session
from prometheus_client import Counter, Histogram

from app.database import get_db, settings
from app.constants import ASSET_TYPE_MAP
from app.models.models import Gateway, Telemetry, AssetParameter, Asset, AlertEvent
from app.routers.gateway import _resolve_station_from_stngw_id, _offset_event_timestamp
from app.services.parameter_config_service import param_config_service
from app.services.redis_service import redis_service
from app.services.websocket_manager import websocket_manager

router = APIRouter(prefix="/webhook", tags=["Webhook Ingestion"])
logger = logging.getLogger("webhook")


def safe_create_task(coro):
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(coro)
    except RuntimeError:
        try:
            import anyio
            anyio.from_thread.run(lambda: coro)
        except Exception:
            coro.close()

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

def verify_client_cert(request: Request) -> Optional[str]:
    """
    Verify the reverse proxy performed mTLS client-certificate verification
    (Annexure B §6) before forwarding this request. TLS itself is terminated
    upstream (nginx/Traefik/etc) — this only checks that the proxy set the
    headers it's configured to set after a successful client-cert handshake.
    See deployment/nginx-mtls.conf.example for the proxy config that
    populates these headers.

    No-op (returns None) when settings.REQUIRE_MTLS is False, so this
    doesn't break dev/staging deployments without mTLS configured yet.
    Returns the certificate's Common Name on success, for optional
    per-gateway identity binding via _check_gateway_cert_binding().
    """
    if not settings.REQUIRE_MTLS:
        return None

    verify_status = request.headers.get(settings.MTLS_VERIFY_HEADER)
    if verify_status != "SUCCESS":
        raise HTTPException(
            status_code=401,
            detail="Client certificate verification failed or missing. mTLS is required for this endpoint."
        )

    cn = request.headers.get(settings.MTLS_CN_HEADER)
    if not cn:
        raise HTTPException(
            status_code=401,
            detail="Client certificate Common Name missing from proxy headers."
        )
    return cn

def _check_gateway_cert_binding(cn: Optional[str], gateway: Gateway):
    """
    If this gateway has a registered mtls_cn (bound via admin action once
    its certificate was issued), the presented certificate's CN must match
    it — this is what stops a leaked shared API key from letting someone
    impersonate a DIFFERENT gateway than the one their certificate was
    issued for. If the gateway has no mtls_cn registered yet, this passes
    through permissively (so newly-provisioned gateways aren't blocked
    before an admin has bound their cert) but logs a warning.
    """
    if not settings.REQUIRE_MTLS:
        return
    if gateway.mtls_cn is None:
        logger.warning(f"Gateway {gateway.stngw_id} has no mtls_cn bound yet — allowing request but not identity-verified.")
        return
    if cn != gateway.mtls_cn:
        raise HTTPException(
            status_code=401,
            detail=f"Certificate CN does not match the registered certificate for gateway {gateway.stngw_id}."
        )

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

class AssetInfoData(BaseModel):
    """One asset's metadata + parameter/location mapping — Annexure B §5.6"""
    asset_number_code: str = Field(..., description="Readable asset name, e.g. PT-01")
    asset_number_id: str = Field(..., description="1 Byte hexadecimal")
    asset_type_code: str = Field(..., description="Asset type string code, e.g. EOP")
    smms_asset_code: str = Field(..., description="Asset code as known to SMMS")
    additional_info: Optional[dict] = Field(
        default=None,
        description="Free-form vendor attributes, e.g. {\"make\":..,\"model\":..,\"attr1\":..,\"attr2\":..}"
    )
    para_id: List[str] = Field(default_factory=list, description="4 Byte hex para_ids belonging to this asset")
    prloc: List[str] = Field(default_factory=list, description="Monitoring location per para_id, same length/order as para_id")

    @field_validator('asset_number_id')
    @classmethod
    def validate_asset_number_id(cls, v: str) -> str:
        if not re.match(r'^[0-9A-Fa-f]{2}$', v):
            raise ValueError('asset_number_id must be a 2 character hexadecimal string')
        return v.upper()

    @field_validator('para_id')
    @classmethod
    def validate_para_ids(cls, v: List[str]) -> List[str]:
        for p in v:
            if not re.match(r'^[0-9A-Fa-f]{8}$', p):
                raise ValueError(f'para_id {p!r} must be an 8 character hexadecimal string')
        return [p.upper() for p in v]

class InformationWebhookPayload(BaseModel):
    resi: str = Field(..., description="Unique response ID")
    stngw_id: str = Field(..., description="4 Byte hexadecimal station gateway ID")
    vcc: Optional[str] = None
    vgc: Optional[str] = None
    stngw_ver: Optional[str] = None
    sc: Optional[str] = Field(None, description="Station code")
    station_name: Optional[str] = None
    cmd: str = Field("INFO", description="Command type")
    info: List[AssetInfoData]

    @field_validator('stngw_id')
    @classmethod
    def validate_stngw_id(cls, v: str) -> str:
        if not re.match(r'^[0-9A-Fa-f]{8}$', v):
            raise ValueError('stngw_id must be 8 character hexadecimal string')
        return v.upper()

class ImageData(BaseModel):
    """One parameter's last-known snapshot value — Annexure B §5.8"""
    para_id: str = Field(..., description="4 Byte hexadecimal parameter ID")
    prv: List[float] = Field(..., description="Last value measured for this para_id")
    prt: List[str] = Field(..., description="Last timestamp for this para_id")

    @field_validator('para_id')
    @classmethod
    def validate_para_id(cls, v: str) -> str:
        if not re.match(r'^[0-9A-Fa-f]{8}$', v):
            raise ValueError('para_id must be 8 character hexadecimal string')
        return v.upper()

    @field_validator('prt')
    @classmethod
    def validate_timestamps(cls, v: List[str]) -> List[str]:
        normalized = []
        for timestamp in v:
            norm_ts = normalize_timestamp(timestamp)
            try:
                datetime.strptime(norm_ts, '%d-%m-%Y %H:%M:%S.%f')
            except ValueError:
                raise ValueError(f'Invalid timestamp format: {timestamp}. Expected DD-MM-YYYY HH:mm:ss.SSS')
            normalized.append(norm_ts)
        return normalized

class ImageWebhookPayload(BaseModel):
    resi: str = Field(..., description="Unique response ID")
    stngw_id: str = Field(..., description="4 Byte hexadecimal station gateway ID")
    cmd: str = Field("IMAGE", description="Command type")
    image: List[ImageData]

    @field_validator('stngw_id')
    @classmethod
    def validate_stngw_id(cls, v: str) -> str:
        if not re.match(r'^[0-9A-Fa-f]{8}$', v):
            raise ValueError('stngw_id must be 8 character hexadecimal string')
        return v.upper()

# ============ Endpoints ============

@router.post("/parameters/fixed", status_code=200)
def receive_fixed_parameters(
    payload: FixedParameterWebhookPayload,
    db: Session = Depends(get_db),
    api_key: bool = Depends(verify_api_key),
    mtls_cn: Optional[str] = Depends(verify_client_cert)
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
            
            # Query parameter ID to asset number code mapping
            asset_mappings = {}
            if candidate_para_ids:
                rows = (
                    db.query(AssetParameter.para_id, Asset.asset_number_code)
                    .join(Asset, Asset.id == AssetParameter.asset_id)
                    .filter(AssetParameter.para_id.in_(candidate_para_ids))
                    .all()
                )
                asset_mappings = {r.para_id.upper(): r.asset_number_code for r in rows}

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
                    
                    if param.prv:
                        latest_value = param.prv[-1]
                        health = param_config_service.check_parameter_health(
                            para_id=para_id_upper,
                            value=latest_value
                        )
                        if health["status"] == "warning":
                            logger.warning(f"Parameter {param.para_id} is in warning state: {health['message']}")
                except Exception as e:
                    errors.append({
                        "para_id": param.para_id,
                        "error": str(e)
                    })

            if records_to_insert:
                _batch_insert(records_to_insert, db)
            db.commit()

            # Broadcast to WebSocket
            station_code = gateway.station.station_code if (gateway and gateway.station) else None
            if station_code and records_to_insert:
                for param in payload.parameters:
                    if param.prv:
                        para_id_upper = param.para_id.upper()
                        asset_number_code = asset_mappings.get(para_id_upper)
                        safe_create_task(
                            websocket_manager.broadcast_parameter_update(
                                stngw_id=stngw_id,
                                station_code=station_code,
                                para_id=para_id_upper,
                                value=param.prv[-1],
                                timestamp=param.prt[-1],
                                asset_number_code=asset_number_code
                            )
                        )
            
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
    api_key: bool = Depends(verify_api_key),
    mtls_cn: Optional[str] = Depends(verify_client_cert)
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

            # Query parameter ID to asset number code mapping
            asset_mappings = {}
            if candidate_para_ids:
                rows = (
                    db.query(AssetParameter.para_id, Asset.asset_number_code)
                    .join(Asset, Asset.id == AssetParameter.asset_id)
                    .filter(AssetParameter.para_id.in_(candidate_para_ids))
                    .all()
                )
                asset_mappings = {r.para_id.upper(): r.asset_number_code for r in rows}

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

            # Broadcast to WebSocket
            station_code = gateway.station.station_code if (gateway and gateway.station) else None
            if station_code and records_to_insert:
                for param in payload.parameters:
                    if param.prv:
                        para_id_upper = param.para_id.upper()
                        asset_number_code = asset_mappings.get(para_id_upper)
                        safe_create_task(
                            websocket_manager.broadcast_parameter_update(
                                stngw_id=stngw_id,
                                station_code=station_code,
                                para_id=para_id_upper,
                                value=param.prv[-1],
                                timestamp=param.prt,
                                asset_number_code=asset_number_code
                            )
                        )
            
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
    api_key: bool = Depends(verify_api_key),
    mtls_cn: Optional[str] = Depends(verify_client_cert)
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
                
                # Update health in cache
                safe_create_task(redis_service.store_gateway_health(stngw_id, is_healthy, payload.stngw_health.stngwh_t))
                
                # Broadcast gateway health update
                station_code = gateway.station.station_code if (gateway and gateway.station) else None
                if station_code:
                    safe_create_task(
                        websocket_manager.broadcast_health_update(
                            station_code=station_code,
                            device_type="gateway",
                            device_id=stngw_id,
                            status="healthy" if is_healthy else "faulty",
                            timestamp=payload.stngw_health.stngwh_t
                        )
                    )

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
                    
                    # Store health in cache
                    safe_create_task(redis_service.store_sensor_health(stngw_id, sensor.para_id, is_healthy, sensor.sh_t))
                    
                    # Broadcast sensor health update
                    station_code = gateway.station.station_code if (gateway and gateway.station) else None
                    if station_code:
                        safe_create_task(
                            websocket_manager.broadcast_health_update(
                                station_code=station_code,
                                device_type="sensor",
                                device_id=sensor.para_id.upper(),
                                status="healthy" if is_healthy else "faulty",
                                timestamp=sensor.sh_t
                            )
                        )
                    
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
    api_key: bool = Depends(verify_api_key),
    mtls_cn: Optional[str] = Depends(verify_client_cert)
):
    """
    Receive gateway discovery on startup/reboot.
    """
    logger.info(f"RQI: {payload.rqi} | GW: {payload.stngw_id} | Gateway discovery start.")
    with webhook_latency.labels('discovery').time():
        try:
            stngw_id = payload.stngw_id.upper().strip()
            gateway = _get_or_create_gateway_with_station(stngw_id, db)
            _check_gateway_cert_binding(mtls_cn, gateway)

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
    api_key: bool = Depends(verify_api_key),
    mtls_cn: Optional[str] = Depends(verify_client_cert)
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
    api_key: bool = Depends(verify_api_key),
    mtls_cn: Optional[str] = Depends(verify_client_cert)
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

# Reverse lookup: asset_type_code (e.g. "EOP") -> asset_type_hex (e.g. "00").
# Built once at import time. Note "IPS" is ambiguous (asset "50" = Integrated
# Power Supply unit, room "F1" = IPS Room) — dict iteration order means the
# first-inserted match ("50") wins here; para_id-derived asset_type_hex
# (unambiguous, see below) is always preferred over this when available.
_CODE_TO_ASSET_TYPE_HEX = {}
for _hex, (_code, _name) in ASSET_TYPE_MAP.items():
    _CODE_TO_ASSET_TYPE_HEX.setdefault(_code, _hex)

@router.post("/information", status_code=200)
def receive_information(
    payload: InformationWebhookPayload,
    db: Session = Depends(get_db),
    api_key: bool = Depends(verify_api_key),
    mtls_cn: Optional[str] = Depends(verify_client_cert)
):
    """
    Receive asset Information data (Annexure B §5.6). Upserts Asset rows and
    maps each para_id to its asset + monitoring location (prloc), the same
    data the "Configure Slave" admin flow would otherwise set by hand.
    """
    logger.info(f"RESI: {payload.resi} | GW: {payload.stngw_id} | Information ingestion start, assets={len(payload.info)}")
    with webhook_latency.labels('information').time():
        try:
            stngw_id = payload.stngw_id.upper().strip()
            gateway = _get_or_create_gateway_with_station(stngw_id, db)
            _check_gateway_cert_binding(mtls_cn, gateway)

            assets_created = 0
            assets_updated = 0
            params_mapped = 0
            errors = []

            for entry in payload.info:
                try:
                    # Prefer deriving asset_type_hex from the first para_id
                    # (unambiguous, byte 1 of para_id) over asset_type_code
                    # (can be ambiguous, e.g. "IPS" means two different things).
                    asset_type_hex = None
                    if entry.para_id:
                        asset_type_hex = entry.para_id[0][0:2].upper()
                    elif entry.asset_type_code in _CODE_TO_ASSET_TYPE_HEX:
                        asset_type_hex = _CODE_TO_ASSET_TYPE_HEX[entry.asset_type_code]
                    else:
                        errors.append(f"{entry.smms_asset_code}: could not resolve asset_type_hex (no para_id, unknown asset_type_code {entry.asset_type_code!r})")
                        continue

                    additional = entry.additional_info or {}

                    asset = db.query(Asset).filter(
                        Asset.station_gateway_id == stngw_id,
                        Asset.asset_type_hex == asset_type_hex,
                        Asset.asset_number_id == entry.asset_number_id,
                    ).first()

                    if asset is None:
                        asset = Asset(
                            smms_asset_code=entry.smms_asset_code,
                            smms_asset_name=entry.asset_number_code,
                            asset_number_code=entry.asset_number_code,
                            asset_number_id=entry.asset_number_id,
                            asset_type_hex=asset_type_hex,
                            station_gateway_id=stngw_id,
                            station_id=gateway.station_id,
                            make=additional.get("make"),
                            model=additional.get("model"),
                            attr1=additional.get("attr1"),
                            attr2=additional.get("attr2"),
                            last_sync=datetime.utcnow(),
                        )
                        db.add(asset)
                        db.flush()
                        assets_created += 1
                    else:
                        asset.smms_asset_code = entry.smms_asset_code
                        asset.asset_number_code = entry.asset_number_code
                        if "make" in additional:
                            asset.make = additional.get("make")
                        if "model" in additional:
                            asset.model = additional.get("model")
                        if "attr1" in additional:
                            asset.attr1 = additional.get("attr1")
                        if "attr2" in additional:
                            asset.attr2 = additional.get("attr2")
                        asset.last_sync = datetime.utcnow()
                        assets_updated += 1

                    # Map each para_id to this asset + its monitoring location
                    for i, para_id in enumerate(entry.para_id):
                        prloc = entry.prloc[i] if i < len(entry.prloc) else None
                        asset_param = db.query(AssetParameter).filter(
                            AssetParameter.para_id == para_id
                        ).first()
                        if asset_param is None:
                            asset_param = AssetParameter(para_id=para_id)
                            db.add(asset_param)
                        asset_param.asset_id = asset.id
                        if prloc is not None:
                            asset_param.prloc = prloc
                        asset_param.is_assigned = True
                        params_mapped += 1

                except Exception as e:
                    errors.append(f"{entry.smms_asset_code}: {str(e)}")

            db.commit()
            logger.info(f"RESI: {payload.resi} | GW: {payload.stngw_id} | Information ingestion complete. created={assets_created} updated={assets_updated} params_mapped={params_mapped}")
            webhook_requests.labels('information', 'success').inc()
            return {
                "status": "success",
                "resi": payload.resi,
                "assets_created": assets_created,
                "assets_updated": assets_updated,
                "params_mapped": params_mapped,
                "errors": errors,
            }
        except HTTPException:
            webhook_requests.labels('information', 'error').inc()
            raise
        except Exception as e:
            db.rollback()
            logger.error(f"RESI: {payload.resi} | GW: {payload.stngw_id} | Information ingestion failed: {str(e)}")
            webhook_requests.labels('information', 'error').inc()
            raise HTTPException(status_code=500, detail=str(e))

@router.post("/image", status_code=200)
def receive_image(
    payload: ImageWebhookPayload,
    db: Session = Depends(get_db),
    api_key: bool = Depends(verify_api_key),
    mtls_cn: Optional[str] = Depends(verify_client_cert)
):
    """
    Receive Image data (Annexure B §5.8) — a full snapshot of every
    parameter's last known value at one instant. Stored the same way as a
    fixed-interval reading (dedup + auto-register unmapped para_id), since
    that's exactly what it structurally is: one more (para_id, value,
    timestamp) triple per parameter.
    """
    logger.info(f"RESI: {payload.resi} | GW: {payload.stngw_id} | Image ingestion start, parameters={len(payload.image)}")
    with webhook_latency.labels('image').time():
        try:
            stngw_id = payload.stngw_id.upper().strip()
            gateway = _get_or_create_gateway_with_station(stngw_id, db)
            _check_gateway_cert_binding(mtls_cn, gateway)

            saved = 0
            skipped = 0
            errors = []
            new_records = []

            for item in payload.image:
                try:
                    asset_param = db.query(AssetParameter).filter(
                        AssetParameter.para_id == item.para_id
                    ).first()
                    if asset_param is None:
                        asset_param = AssetParameter(para_id=item.para_id)
                        db.add(asset_param)
                        db.flush()

                    for value, ts in zip(item.prv, item.prt):
                        exists = db.query(Telemetry).filter(
                            Telemetry.para_id == item.para_id,
                            Telemetry.prt == ts,
                            Telemetry.prv == value,
                        ).first()
                        if exists:
                            skipped += 1
                            continue
                        new_records.append(Telemetry(
                            gateway_id=gateway.id,
                            para_id=item.para_id,
                            prv=value,
                            prt=ts,
                            is_processed=False,
                        ))
                        saved += 1
                except Exception as e:
                    errors.append(f"{item.para_id}: {str(e)}")

            if new_records:
                _batch_insert(new_records, db)
            db.commit()

            logger.info(f"RESI: {payload.resi} | GW: {payload.stngw_id} | Image ingestion complete. saved={saved} skipped={skipped}")
            webhook_requests.labels('image', 'success').inc()
            return {
                "status": "success",
                "resi": payload.resi,
                "saved": saved,
                "skipped": skipped,
                "errors": errors,
            }
        except HTTPException:
            webhook_requests.labels('image', 'error').inc()
            raise
        except Exception as e:
            db.rollback()
            logger.error(f"RESI: {payload.resi} | GW: {payload.stngw_id} | Image ingestion failed: {str(e)}")
            webhook_requests.labels('image', 'error').inc()
            raise HTTPException(status_code=500, detail=str(e))
