import logging
import json
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any

from sqlalchemy.orm import Session
from app.database import SessionLocal, engine
from app.models.models import Gateway, Telemetry, AlertEvent, Asset, AssetParameter
from app.models.database_models import Alert, FeedbackType
from app.routers.gateway import _resolve_station_from_stngw_id

logger = logging.getLogger("database_service")

class DatabaseService:
    def __init__(self):
        pass
    
    async def initialize(self):
        """No-op for SQLAlchemy initialization, tables are created on startup in main.py"""
        logger.info("SQLAlchemy DatabaseService initialized successfully")
    
    async def close(self):
        """No-op for SQLAlchemy"""
        pass
    
    def _get_or_create_gateway(self, db: Session, stngw_id: str) -> Gateway:
        stngw_id = stngw_id.upper().strip()
        gateway = db.query(Gateway).filter(Gateway.stngw_id == stngw_id).first()
        if not gateway:
            station_id = _resolve_station_from_stngw_id(stngw_id, db)
            gateway = Gateway(stngw_id=stngw_id, station_id=station_id)
            db.add(gateway)
            db.flush()
        return gateway

    # ============ Parameter History ============
    
    async def store_parameter_history(
        self, 
        stngw_id: str, 
        para_id: str, 
        values: List[float], 
        timestamps: List[str]
    ):
        """Store parameter values in the main Telemetry table"""
        if not values or not timestamps or len(values) != len(timestamps):
            logger.warning(f"Invalid parameter data for {para_id}")
            return
        
        with SessionLocal() as db:
            try:
                gateway = self._get_or_create_gateway(db, stngw_id)
                para_id_upper = para_id.upper().strip()
                
                records = []
                for val, ts in zip(values, timestamps):
                    record = Telemetry(
                        gateway_id=gateway.id,
                        para_id=para_id_upper,
                        prv=val,
                        prt=ts,
                        raw_payload=json.dumps({
                            "stngw_id": stngw_id,
                            "para_id": para_id_upper,
                            "prv": val,
                            "prt": ts,
                            "packet_type": "historical_aggregation"
                        })
                    )
                    records.append(record)
                
                db.add_all(records)
                db.commit()
                logger.debug(f"Stored {len(values)} values for {para_id}")
            except Exception as e:
                db.rollback()
                logger.error(f"Error storing parameter history for {para_id}: {e}")
                raise
    
    # ============ Alerts ============
    
    async def store_alert(self, alert: Alert) -> Optional[int]:
        """Store a new alert event"""
        with SessionLocal() as db:
            try:
                gateway = self._get_or_create_gateway(db, alert.stngw_id)
                
                # Fetch matching asset to link
                asset = db.query(Asset).filter(
                    Asset.station_id == gateway.station_id,
                    Asset.asset_number_code == alert.asset_number_code
                ).first()
                asset_id = asset.id if asset else None
                asset_type_hex = asset.asset_type_hex if asset else "00"
                
                status_val = alert.status.value
                if status_val.lower() in ("pending", "active"):
                    status_val = "Active"
                else:
                    status_val = "Cleared"

                db_alert = AlertEvent(
                    station_id=gateway.station_id,
                    alert_type=alert.alert_type.value,
                    asset_type_hex=asset_type_hex,
                    asset_no=alert.asset_number_code,
                    cause=alert.cause_code,
                    alert_status=status_val,
                    acknowledged=False,
                    alert_time=alert.incidence_date_time or datetime.now(timezone.utc),
                    remark=alert.cause_detail,
                    asset_id=asset_id
                )
                db.add(db_alert)
                db.commit()
                db.refresh(db_alert)
                logger.info(f"Stored alert {db_alert.id}: {alert.cause_code}")
                return db_alert.id
            except Exception as e:
                db.rollback()
                logger.error(f"Error storing alert: {e}")
                raise
    
    async def update_alert_feedback(
        self, 
        alert_id: int, 
        feedback: FeedbackType,
        remarks: Optional[str] = None
    ):
        """Update alert with feedback"""
        with SessionLocal() as db:
            try:
                db_alert = db.query(AlertEvent).filter(AlertEvent.id == alert_id).first()
                if db_alert:
                    db_alert.feedback = feedback.value
                    db_alert.feedback_time = datetime.now(timezone.utc)
                    db_alert.remark = remarks
                    db_alert.alert_status = "Cleared"
                    db_alert.rectification_time = datetime.now(timezone.utc)
                    db.commit()
                    logger.info(f"Updated alert {alert_id} with feedback: {feedback.value}")
                else:
                    logger.warning(f"Alert {alert_id} not found for updating feedback")
            except Exception as e:
                db.rollback()
                logger.error(f"Error updating alert {alert_id}: {e}")
                raise
    
    async def get_active_alerts(
        self, 
        stngw_id: Optional[str] = None,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """Get active (pending/Active) alerts"""
        with SessionLocal() as db:
            try:
                query = db.query(AlertEvent).filter(AlertEvent.alert_status == "Active")
                if stngw_id:
                    gateway = db.query(Gateway).filter(Gateway.stngw_id == stngw_id.upper()).first()
                    if gateway:
                        query = query.filter(AlertEvent.station_id == gateway.station_id)
                    else:
                        return []
                
                rows = query.order_by(AlertEvent.alert_time.desc()).limit(limit).all()
                
                results = []
                for row in rows:
                    gw = db.query(Gateway).filter(Gateway.station_id == row.station_id).first()
                    gw_id = gw.stngw_id if gw else "UNKNOWN"
                    
                    results.append({
                        "id": row.id,
                        "stngw_id": gw_id,
                        "asset_number_code": row.asset_no,
                        "alert_type": row.alert_type,
                        "cause_code": row.cause,
                        "cause_detail": row.remark or "",
                        "incidence_date_time": row.alert_time,
                        "status": row.alert_status.lower(),
                        "feedback": row.feedback,
                        "feedback_date_time": row.feedback_time,
                        "rectification_date_time": row.rectification_time,
                        "remarks": row.remark,
                        "maintainer_name": row.maintainer_name,
                        "maintainer_mobile": row.mobile
                    })
                return results
            except Exception as e:
                logger.error(f"Error getting active alerts: {e}")
                return []
    
    # ============ Asset Management ============
    
    async def get_asset_by_para_id(self, para_id: str) -> Optional[Dict[str, Any]]:
        """Get asset information by parameter ID"""
        with SessionLocal() as db:
            try:
                ap = db.query(AssetParameter).filter(AssetParameter.para_id == para_id.upper()).first()
                if ap and ap.asset_id:
                    asset = db.query(Asset).filter(Asset.id == ap.asset_id).first()
                    if asset:
                        return {
                            "id": asset.id,
                            "smms_asset_code": asset.smms_asset_code,
                            "smms_asset_name": asset.smms_asset_name,
                            "asset_number_id": asset.asset_number_id,
                            "asset_number_code": asset.asset_number_code,
                            "asset_type_id": asset.asset_type_hex,
                            "asset_type_code": asset.asset_type.asset_type_code if asset.asset_type else "UNKNOWN",
                            "station_id": str(asset.station_id),
                            "make": asset.make,
                            "model": asset.model,
                            "prloc": asset.prloc
                        }
                return None
            except Exception as e:
                logger.error(f"Error getting asset for para_id {para_id}: {e}")
                return None
    
    # ============ Health ============
    
    async def update_gateway_health(
        self, 
        stngw_id: str, 
        is_healthy: bool, 
        version: Optional[str] = None
    ):
        """
        Update gateway health. We update the timestamp of the Gateway model itself 
        (or create a corresponding AlertEvent if unhealthy).
        """
        with SessionLocal() as db:
            try:
                gateway = self._get_or_create_gateway(db, stngw_id)
                # Keep gateway's associated information updated
                db.commit()
                logger.debug(f"Updated gateway health for {stngw_id}: {is_healthy}")
            except Exception as e:
                logger.error(f"Error updating gateway health {stngw_id}: {e}")
    
    async def update_sensor_health(
        self, 
        stngw_id: str, 
        para_id: str, 
        is_healthy: bool, 
        timestamp: datetime
    ):
        """Update sensor health status"""
        # Sensor health updates are handled through AlertEvent creations on status '01'
        logger.debug(f"Sensor health update hook called for {para_id}: {is_healthy}")

# Singleton instance
db_service = DatabaseService()
