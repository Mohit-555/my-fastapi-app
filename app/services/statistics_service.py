import logging
from datetime import datetime, timedelta, date
from typing import List, Dict, Any, Optional
from sqlalchemy import and_

from app.database import SessionLocal
from app.models.models import AlertEvent, Gateway, Asset

logger = logging.getLogger("statistics_service")

class StatisticsService:
    """Service for calculating statistics and performance metrics"""
    
    async def calculate_alert_statistics(
        self,
        stngw_id: Optional[str] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> Dict[str, Any]:
        """Calculate alert statistics for a period"""
        def make_naive(dt: Optional[datetime]) -> Optional[datetime]:
            if dt is None:
                return None
            return dt.replace(tzinfo=None) if dt.tzinfo is not None else dt

        start_date_naive = make_naive(start_date)
        end_date_naive = make_naive(end_date)

        with SessionLocal() as db:
            try:
                query = db.query(AlertEvent)
                
                if stngw_id:
                    gateway = db.query(Gateway).filter(Gateway.stngw_id == stngw_id.upper()).first()
                    if not gateway:
                        return {}
                    query = query.filter(AlertEvent.station_id == gateway.station_id)
                
                if start_date_naive:
                    query = query.filter(AlertEvent.alert_time >= start_date_naive)
                if end_date_naive:
                    query = query.filter(AlertEvent.alert_time <= end_date_naive)
                
                rows = query.all()
                
                stats = {
                    "total_alerts": 0,
                    "by_type": {
                        "failure": {"total": 0, "pending": 0, "cleared": 0},
                        "predictive": {"total": 0, "pending": 0, "cleared": 0}
                    },
                    "by_feedback": {
                        "T": 0,   # True
                        "PT": 0,  # Partially True
                        "F": 0,   # False
                        "M": 0    # Maintenance
                    }
                }
                
                for row in rows:
                    alert_type = row.alert_type.lower()
                    stats["total_alerts"] += 1
                    
                    if alert_type in stats["by_type"]:
                        stats["by_type"][alert_type]["total"] += 1
                        if row.alert_status.lower() == 'active' or row.alert_status.lower() == 'pending':
                            stats["by_type"][alert_type]["pending"] += 1
                        else:
                            stats["by_type"][alert_type]["cleared"] += 1
                    
                    fb = row.feedback
                    if fb and fb in stats["by_feedback"]:
                        stats["by_feedback"][fb] += 1
                
                # Calculate success rates
                failure_total = stats["by_type"]["failure"]["total"]
                predictive_total = stats["by_type"]["predictive"]["total"]
                
                true_pt = stats["by_feedback"]["T"] + stats["by_feedback"]["PT"]
                
                stats["failure_success_rate"] = (
                    true_pt / failure_total * 100 if failure_total > 0 else 0.0
                )
                stats["predictive_success_rate"] = (
                    true_pt / predictive_total * 100 if predictive_total > 0 else 0.0
                )
                stats["overall_success_rate"] = (
                    true_pt / stats["total_alerts"] * 100 if stats["total_alerts"] > 0 else 0.0
                )
                
                return stats
                
            except Exception as e:
                logger.error(f"Error calculating alert statistics: {e}")
                return {}
    
    async def calculate_asset_availability(
        self,
        stngw_id: str,
        asset_number_code: str,
        start_date: datetime,
        end_date: datetime
    ) -> float:
        """Calculate availability percentage for an asset"""
        def make_naive(dt: Optional[datetime]) -> Optional[datetime]:
            if dt is None:
                return None
            return dt.replace(tzinfo=None) if dt.tzinfo is not None else dt

        start_date_naive = make_naive(start_date)
        end_date_naive = make_naive(end_date)

        with SessionLocal() as db:
            try:
                gateway = db.query(Gateway).filter(Gateway.stngw_id == stngw_id.upper()).first()
                if not gateway:
                    return 0.0
                
                total_seconds = (end_date_naive - start_date_naive).total_seconds()
                if total_seconds <= 0:
                    return 100.0
                
                alerts = db.query(AlertEvent).filter(
                    AlertEvent.station_id == gateway.station_id,
                    AlertEvent.asset_no == asset_number_code,
                    AlertEvent.alert_type == 'Failure',
                    AlertEvent.alert_time >= start_date_naive,
                    AlertEvent.alert_time <= end_date_naive
                ).all()
                
                downtime_seconds = 0.0
                now_naive = make_naive(datetime.now())
                
                for alert in alerts:
                    start_dt = make_naive(alert.alert_time)
                    end_dt = make_naive(alert.rectification_time) or now_naive
                    
                    # Bound to the requested start/end range
                    start_dt = max(start_dt, start_date_naive)
                    end_dt = min(end_dt, end_date_naive)
                    
                    duration = (end_dt - start_dt).total_seconds()
                    if duration > 0:
                        downtime_seconds += duration
                
                availability = ((total_seconds - downtime_seconds) / total_seconds) * 100
                return max(0.0, min(100.0, availability))
                
            except Exception as e:
                logger.error(f"Error calculating asset availability: {e}")
                return 0.0
    
    async def calculate_mtbf(
        self,
        stngw_id: str,
        asset_number_code: str,
        start_date: datetime,
        end_date: datetime
    ) -> float:
        """Calculate Mean Time Between Failures in hours"""
        def make_naive(dt: Optional[datetime]) -> Optional[datetime]:
            if dt is None:
                return None
            return dt.replace(tzinfo=None) if dt.tzinfo is not None else dt

        start_date_naive = make_naive(start_date)
        end_date_naive = make_naive(end_date)

        with SessionLocal() as db:
            try:
                gateway = db.query(Gateway).filter(Gateway.stngw_id == stngw_id.upper()).first()
                if not gateway:
                    return 0.0
                
                rows = db.query(AlertEvent.alert_time).filter(
                    AlertEvent.station_id == gateway.station_id,
                    AlertEvent.asset_no == asset_number_code,
                    AlertEvent.alert_type == 'Failure',
                    AlertEvent.alert_time >= start_date_naive,
                    AlertEvent.alert_time <= end_date_naive
                ).order_by(AlertEvent.alert_time.asc()).all()
                
                if len(rows) < 2:
                    return 0.0
                
                total_time = 0.0
                for i in range(1, len(rows)):
                    diff = make_naive(rows[i].alert_time) - make_naive(rows[i-1].alert_time)
                    total_time += diff.total_seconds()
                
                mtbf = total_time / (len(rows) - 1)
                return mtbf / 3600  # Convert to hours
                
            except Exception as e:
                logger.error(f"Error calculating MTBF: {e}")
                return 0.0
    
    async def calculate_performance_metrics(
        self,
        stngw_id: str,
        start_date: datetime,
        end_date: datetime
    ) -> Dict[str, float]:
        """Calculate all performance metrics for a station"""
        try:
            stats = await self.calculate_alert_statistics(
                stngw_id=stngw_id,
                start_date=start_date,
                end_date=end_date
            )
            
            with SessionLocal() as db:
                gateway = db.query(Gateway).filter(Gateway.stngw_id == stngw_id.upper()).first()
                if not gateway:
                    assets = []
                else:
                    assets = db.query(Asset).filter(Asset.station_id == gateway.station_id).all()
            
            total_availability = 0.0
            for asset in assets:
                availability = await self.calculate_asset_availability(
                    stngw_id=stngw_id,
                    asset_number_code=asset.asset_number_code,
                    start_date=start_date,
                    end_date=end_date
                )
                total_availability += availability
            
            avg_availability = (
                total_availability / len(assets) if assets else 0.0
            )
            
            return {
                "fail_alert_per": stats.get("failure_success_rate", 0.0),
                "pred_alert_per": stats.get("predictive_success_rate", 0.0),
                "actual_fail_alert_per": avg_availability,
                "mtbf_hours": 0.0,  # Can be detailed per asset if needed
                "availability": avg_availability
            }
            
        except Exception as e:
            logger.error(f"Error calculating performance metrics: {e}")
            return {
                "fail_alert_per": 0.0,
                "pred_alert_per": 0.0,
                "actual_fail_alert_per": 0.0,
                "mtbf_hours": 0.0,
                "availability": 0.0
            }

# Singleton instance
statistics_service = StatisticsService()
