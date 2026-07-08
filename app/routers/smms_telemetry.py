# app/routers/smms_telemetry.py
from fastapi import APIRouter, Depends, HTTPException, Query, Header
from typing import Optional, List
from datetime import datetime
from sqlalchemy.orm import Session

from app.database import get_db, settings
from app.models.models import Station, Division, Zone, Asset, AssetParameter, Telemetry, Gateway
from app.services.redis_service import redis_service
from app.services.parameter_config_service import param_config_service
import logging
logger = logging.getLogger("smms_telemetry")

router = APIRouter(prefix="/api/smms", tags=["SMMS Telemetry"])


@router.get("/get_asset_telemetry/{zc}/{dc}/{sc}")
async def get_asset_telemetry(
    zc: str,
    dc: str,
    sc: str,
    smms_asset_code: Optional[str] = None,
    para_ids: Optional[str] = Query(None, description="Comma-separated parameter IDs"),
    x_api_key: str = Header(...),
    db: Session = Depends(get_db)
):
    """
    API for SMMS to fetch telemetry data from RDPMS.
    
    This implements the SMMS telemetry data format from Annexure B §5.14.
    
    If smms_asset_code is not provided, returns telemetry for all assets at the station.
    If para_ids is not provided, returns all parameters.
    """
    # Validate API key
    if x_api_key != settings.SMMS_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API Key")
    
    # Validate station
    station = db.query(Station).filter(Station.station_code == sc).first()
    if not station:
        raise HTTPException(status_code=404, detail=f"Station {sc} not found")
    
    # Get gateway for station
    gateway = db.query(Gateway).filter(Gateway.station_id == station.id).first()
    if not gateway:
        return {
            "resi": "error",
            "vcc": settings.VENDOR_CODE,
            "zc": zc,
            "dc": dc,
            "sc": sc,
            "telemetry_data": [],
            "message": "No gateway found for station"
        }
    
    # Parse para_ids
    para_id_list = None
    if para_ids:
        para_id_list = [p.strip().upper() for p in para_ids.split(",") if p.strip()]
    
    # Get assets
    query = db.query(Asset).filter(
        Asset.station_id == station.id,
        Asset.is_active == True
    )
    
    if smms_asset_code:
        query = query.filter(Asset.smms_asset_code == smms_asset_code)
    
    assets = query.all()
    
    if not assets:
        return {
            "resi": "no_assets",
            "vcc": settings.VENDOR_CODE,
            "zc": zc,
            "dc": dc,
            "sc": sc,
            "telemetry_data": []
        }
    
    # Build response
    telemetry_data = []
    
    for asset in assets:
        # Get parameter IDs for this asset
        asset_params = db.query(AssetParameter).filter(
            AssetParameter.asset_id == asset.id
        ).all()
        
        param_ids = [ap.para_id for ap in asset_params]
        
        # Filter by para_ids if provided
        if para_id_list:
            param_ids = [pid for pid in param_ids if pid in para_id_list]
        
        if not param_ids:
            continue
        
        # Get latest values from Redis/fallback
        parameters = []
        for para_id in param_ids:
            latest = await redis_service.get_latest_parameter(gateway.stngw_id, para_id)
            
            if latest:
                # Get parameter config for metadata from service
                param_config = param_config_service.get_parameter_config(para_id)
                
                parameters.append({
                    "para_id": para_id,
                    "prv": latest.get("value"),
                    "prt": latest.get("timestamp"),
                    "unit": param_config.unit if param_config else None
                })
            else:
                # No data available
                parameters.append({
                    "para_id": para_id,
                    "prv": None,
                    "prt": None
                })
        
        if parameters:
            telemetry_data.append({
                "smms_asset_code": asset.smms_asset_code,
                "asset_number_code": asset.asset_number_code,
                "asset_type_hex": asset.asset_type_hex,
                "parameters": parameters
            })
    
    return {
        "resi": "success",
        "vcc": settings.VENDOR_CODE,
        "zc": zc,
        "dc": dc,
        "sc": sc,
        "timestamp": datetime.utcnow().isoformat(),
        "telemetry_data": telemetry_data
    }
