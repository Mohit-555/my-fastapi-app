import logging
from fastapi import APIRouter, Depends, HTTPException
from typing import List, Optional, Any

from app.auth_utils import get_current_user
from app.services.parameter_config_service import param_config_service
from app.models.database_models import ParameterConfig
from app.models.schemas import StandardResponse

logger = logging.getLogger("config_router")
router = APIRouter(prefix="/api/config", tags=["Configuration"])

@router.get("/parameters", response_model=StandardResponse[Any])
async def get_parameter_configs(
    asset_type_id: Optional[str] = None,
    current_user: dict = Depends(get_current_user)
):
    """Get parameter configurations"""
    if asset_type_id:
        configs = param_config_service.get_parameters_by_asset_type(asset_type_id)
    else:
        configs = list(param_config_service.config_cache.values())
    
    return {
        "status": True,
        "message": "Success",
        "data": {
            "count": len(configs),
            "configurations": [config.dict() for config in configs]
        }
    }

@router.get("/parameters/{para_id}", response_model=StandardResponse[Any])
async def get_parameter_config(
    para_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Get parameter configuration by ID"""
    config = param_config_service.get_parameter_config(para_id)
    if not config:
        raise HTTPException(status_code=404, detail="Parameter not found")
    return {
        "status": True,
        "message": "Success",
        "data": config.dict()
    }

@router.post("/parameters", response_model=StandardResponse[Any])
async def create_parameter_config(
    config: ParameterConfig,
    current_user: dict = Depends(get_current_user)
):
    """Create or update a parameter configuration"""
    try:
        param_config_service.register_parameter(config.dict())
        return {
            "status": True,
            "message": "Success",
            "data": None
        }
    except Exception as e:
        logger.error(f"Error saving parameter config: {e}")
        raise HTTPException(status_code=500, detail=str(e))

