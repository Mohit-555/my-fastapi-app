import logging
from fastapi import APIRouter, Depends, Query
from datetime import datetime, timedelta
from typing import Optional

from app.auth_utils import get_current_user
from app.services.statistics_service import statistics_service

logger = logging.getLogger("statistics_router")
router = APIRouter(prefix="/api/statistics", tags=["Statistics"])

@router.get("/alerts")
async def get_alert_statistics(
    stngw_id: Optional[str] = None,
    days: int = Query(30, ge=1, le=365, description="Number of days to analyze"),
    current_user: dict = Depends(get_current_user)
):
    """Get alert statistics for the last N days"""
    end_date = datetime.now()
    start_date = end_date - timedelta(days=days)
    
    stats = await statistics_service.calculate_alert_statistics(
        stngw_id=stngw_id,
        start_date=start_date,
        end_date=end_date
    )
    
    return {
        "period": {
            "start": start_date.isoformat(),
            "end": end_date.isoformat(),
            "days": days
        },
        "statistics": stats
    }

@router.get("/performance/{stngw_id}")
async def get_performance_metrics(
    stngw_id: str,
    days: int = Query(30, ge=1, le=365),
    current_user: dict = Depends(get_current_user)
):
    """Get performance metrics for a station"""
    end_date = datetime.now()
    start_date = end_date - timedelta(days=days)
    
    metrics = await statistics_service.calculate_performance_metrics(
        stngw_id=stngw_id,
        start_date=start_date,
        end_date=end_date
    )
    
    return {
        "stngw_id": stngw_id,
        "period": {
            "start": start_date.isoformat(),
            "end": end_date.isoformat(),
            "days": days
        },
        "metrics": metrics
    }

@router.get("/asset-availability")
async def get_asset_availability(
    stngw_id: str,
    asset_number_code: str,
    days: int = Query(30, ge=1, le=365),
    current_user: dict = Depends(get_current_user)
):
    """Get availability for a specific asset"""
    end_date = datetime.now()
    start_date = end_date - timedelta(days=days)
    
    availability = await statistics_service.calculate_asset_availability(
        stngw_id=stngw_id,
        asset_number_code=asset_number_code,
        start_date=start_date,
        end_date=end_date
    )
    
    return {
        "stngw_id": stngw_id,
        "asset_number_code": asset_number_code,
        "period": {
            "start": start_date.isoformat(),
            "end": end_date.isoformat(),
            "days": days
        },
        "availability": availability
    }
