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
        self.batch_size = 100
        self.processing_interval = 5  # seconds
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
            except Exception as e:
                logger.error(f"Error in alert processor: {e}")
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
            
            for telemetry in unprocessed:
                try:
                    # Get gateway
                    gateway = db.query(Gateway).filter(
                        Gateway.id == telemetry.gateway_id
                    ).first()
                    
                    if not gateway:
                        telemetry.is_processed = True
                        continue
                    
                    # Get asset parameter mapping
                    asset_param = db.query(AssetParameter).filter(
                        AssetParameter.para_id == telemetry.para_id
                    ).first()
                    
                    if not asset_param or not asset_param.asset_id:
                        # Mark as processed anyway (no asset mapping)
                        telemetry.is_processed = True
                        continue
                    
                    # Get asset
                    asset = db.query(Asset).filter(
                        Asset.id == asset_param.asset_id
                    ).first()
                    
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
                            # Push to any dashboard subscribed via
                            # ws://.../ws/alerts/{station_code}. Previously
                            # only manual actions (acknowledge/feedback/
                            # clear) broadcast; newly-generated alerts from
                            # this background loop never reached connected
                            # clients until they reconnected or polled.
                            try:
                                from app.routers.alerts import _broadcast_alert_update
                                _broadcast_alert_update(alert)
                            except Exception as e:
                                logger.error(f"Error broadcasting alert {alert.id}: {e}")
                    
                    # Mark as processed
                    telemetry.is_processed = True
                    processed_count += 1
                    
                except Exception as e:
                    logger.error(f"Error processing telemetry {telemetry.id}: {e}")
                    # Mark as processed to prevent infinite loops on malformed rows
                    telemetry.is_processed = True
            
            db.commit()
            
            if processed_count > 0:
                logger.info(f"Processed {processed_count} telemetry records, generated {alert_count} alerts")
            
        except Exception as e:
            logger.error(f"Error in alert processor batch: {e}")
            db.rollback()
        finally:
            db.close()

# Singleton instance
alert_processor = AlertProcessor()
