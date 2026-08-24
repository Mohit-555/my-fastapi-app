import asyncio
from datetime import datetime
import logging
from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.services.alert_engine import alert_engine
from app.models.models import Telemetry, Gateway, AssetParameter, Asset

logger = logging.getLogger("alert_processor")

def safe_parse_datetime(prt_str: str) -> datetime:
    if not prt_str:
        return datetime.utcnow()
    clean_str = prt_str.replace(" IST", "").strip()
    try:
        return datetime.fromisoformat(clean_str)
    except ValueError:
        try:
            return datetime.strptime(clean_str, "%Y-%m-%d %H:%M:%S.%f")
        except ValueError:
            try:
                return datetime.strptime(clean_str, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                return datetime.utcnow()

class AlertProcessor:
    """Background service to process telemetry for alerts"""
    
    def __init__(self):
        self.alert_engine = alert_engine
        self.is_running = False
        self.batch_size = 1000
        self.processing_interval = 1  # seconds
        self._task = None
    
    async def start(self):
        """Start the alert processor"""
        self.is_running = True
        logger.info("Alert processor started")
        
        while self.is_running:
            try:
                await self._process_batch()
                await asyncio.sleep(self.processing_interval)
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Error in alert processor daemon loop")
                await asyncio.sleep(30)  # Wait before retry
    
    async def stop(self):
        """Stop the alert processor"""
        self.is_running = False
        logger.info("Alert processor stopped")
    
    async def _process_batch(self):
        """Process a batch of unprocessed telemetry"""
        db = SessionLocal()
        try:
            # Get unprocessed telemetry
            unprocessed = db.query(Telemetry).filter(
                Telemetry.is_processed == False
            ).order_by(Telemetry.id.asc()).limit(self.batch_size).all()
            
            if not unprocessed:
                return
            
            processed_count = 0
            alert_count = 0
            
            # Batch query related records to resolve N+1 database roundtrips
            gateway_ids = {t.gateway_id for t in unprocessed if t.gateway_id}
            para_ids = {t.para_id for t in unprocessed if t.para_id}
            
            gateways = {}
            if gateway_ids:
                g_rows = db.query(Gateway).filter(Gateway.id.in_(gateway_ids)).all()
                gateways = {g.id: g for g in g_rows}
                
            asset_params = {}
            if para_ids:
                ap_rows = db.query(AssetParameter).filter(AssetParameter.para_id.in_(para_ids)).all()
                asset_params = {ap.para_id.upper(): ap for ap in ap_rows}
                
            asset_ids = {ap.asset_id for ap in asset_params.values() if ap.asset_id}
            assets = {}
            if asset_ids:
                a_rows = db.query(Asset).filter(Asset.id.in_(asset_ids)).all()
                assets = {a.id: a for a in a_rows}
            
            for telemetry in unprocessed:
                try:
                    # Get gateway from batch mapping
                    gateway = gateways.get(telemetry.gateway_id)
                    if not gateway:
                        telemetry.is_processed = True
                        continue
                    
                    # Get asset parameter mapping from batch mapping
                    para_id_key = telemetry.para_id.upper() if telemetry.para_id else None
                    asset_param = asset_params.get(para_id_key)
                    if not asset_param or not asset_param.asset_id:
                        # Mark as processed anyway (no asset mapping)
                        telemetry.is_processed = True
                        continue
                    
                    # Get asset from batch mapping
                    asset = assets.get(asset_param.asset_id)
                    if not asset:
                        telemetry.is_processed = True
                        continue
                    
                    # Evaluate alerts
                    alerts = self.alert_engine.evaluate_telemetry(
                        gateway_id=gateway.id,
                        stngw_id=gateway.stngw_id,
                        para_id=telemetry.para_id,
                        value=telemetry.prv,
                        timestamp=telemetry.prt,
                        db=db
                    )
                    
                    # Process generated alerts
                    for alert_data in alerts:
                        alert = self.alert_engine._generate_alert(
                            station_id=gateway.station_id,
                            asset_id=asset.id,
                            asset_number_code=asset.asset_number_code,
                            asset_type_hex=asset.asset_type_hex,
                            cause_code=alert_data["cause_code"],
                            cause_detail=alert_data["cause_detail"],
                            alert_type=alert_data["alert_type"],
                            timestamp=safe_parse_datetime(telemetry.prt),
                            db=db
                        )
                        if alert:
                            alert_count += 1
                            try:
                                from app.routers.alerts import _broadcast_alert_update
                                _broadcast_alert_update(alert)
                            except Exception:
                                logger.exception(f"Error broadcasting alert {alert.id}")
                    
                    # Mark as processed
                    telemetry.is_processed = True
                    processed_count += 1
                    
                except Exception:
                    logger.exception(f"Error processing telemetry {telemetry.id}")
                    # Mark as processed to prevent infinite loops on malformed rows
                    telemetry.is_processed = True
            
            db.commit()
            if alert_count > 0:
                from app.services.websocket_manager import websocket_manager
                await websocket_manager.broadcast_dashboard_update("alert_created")
            
            if processed_count > 0:
                logger.info(f"Processed {processed_count} telemetry records, generated {alert_count} alerts")
            
        except Exception:
            logger.exception("Error in alert processor batch execution")
            db.rollback()
        finally:
            db.close()

# Singleton instance
alert_processor = AlertProcessor()
