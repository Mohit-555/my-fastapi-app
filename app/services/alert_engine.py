from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from enum import Enum
import logging
from sqlalchemy.orm import Session

logger = logging.getLogger("alert_engine")
from app.models.models import Telemetry, Asset, AlertEvent, Gateway, AssetParameter
from app.models.schemas import AlertEventCreate
from fastapi import HTTPException
from app.services.parameter_config_service import param_config_service

class AlertType(str, Enum):
    FAILURE = "Failure"
    PREDICTIVE = "Predictive"

class AlertPriority(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


def build_alert_key(station_id, asset_number_code: str, cause_code: str, alert_type_value) -> str:
    """Dedup/tracking key for an alert.

    Station-scoped: identical asset numbers exist at different stations, so
    keys without the station would cross-suppress alerts between stations.
    Used consistently by alert_engine and routers/alerts.py.
    """
    return f"{station_id}:{asset_number_code}:{cause_code}:{alert_type_value}"

class AlertEngine:
    def __init__(self):
        self.active_alerts = {}  # Track active alerts per asset
        self.alert_history = {}  # Track historical alerts
        self.maintenance_mode = {}  # Track maintenance mode
        
    def evaluate_telemetry(
        self,
        gateway_id: int,
        stngw_id: str,
        para_id: str,
        value: float,
        timestamp: str,
        db: Session
    ) -> List[Dict]:
        """
        Evaluate telemetry against all relevant logics
        Returns list of alerts to generate
        """
        alerts = []
        
        # Get parameter configuration from config service instead of database
        param_config = param_config_service.get_parameter_config(para_id)
        
        if not param_config:
            return alerts
        
        # Get asset for this parameter
        asset_param = db.query(AssetParameter).filter(
            AssetParameter.para_id == para_id
        ).first()
        
        if not asset_param or not asset_param.asset_id:
            return alerts
        
        asset = db.query(Asset).filter(Asset.id == asset_param.asset_id).first()
        
        if not asset:
            return alerts
        
        # Check if in maintenance mode
        if self._is_in_maintenance_mode(asset.asset_number_code, stngw_id):
            logger.debug(f"Asset {asset.asset_number_code} in maintenance mode, skipping alerts")
            return alerts
        
        # Route to appropriate logic handler based on asset type
        asset_type = asset.asset_type_hex
        
        if asset_type == "00":  # Point Machine
            alerts = self._evaluate_point_machine_logics(
                gateway_id, stngw_id, para_id, value, timestamp, asset, db
            )
        elif asset_type == "20":  # DC Track Circuit
            alerts = self._evaluate_track_circuit_logics(
                gateway_id, stngw_id, para_id, value, timestamp, asset, db
            )
        elif asset_type in ["10", "11", "12", "13"]:  # Signals
            alerts = self._evaluate_signal_logics(
                gateway_id, stngw_id, para_id, value, timestamp, asset, db
            )
        elif asset_type == "50":  # IPS
            alerts = self._evaluate_ips_logics(
                gateway_id, stngw_id, para_id, value, timestamp, asset, db
            )
        
        return alerts
    
    def _is_in_maintenance_mode(self, asset_number_code: str, stngw_id: str) -> bool:
        """Check if asset is in maintenance mode"""
        key = f"{stngw_id}:{asset_number_code}"
        if key in self.maintenance_mode:
            end_time = self.maintenance_mode[key]
            if datetime.now() < end_time:
                return True
            else:
                # Clean up expired maintenance mode
                del self.maintenance_mode[key]
        return False
    
    def activate_maintenance_mode(
        self,
        stngw_id: str,
        asset_number_code: str,
        from_time: datetime,
        to_time: datetime
    ):
        """Activate maintenance mode for an asset"""
        key = f"{stngw_id}:{asset_number_code}"
        self.maintenance_mode[key] = to_time
        logger.info(f"Maintenance mode activated for {asset_number_code} until {to_time}")
    
    def clear_maintenance_mode(self, stngw_id: str, asset_number_code: str):
        """Clear maintenance mode for an asset"""
        key = f"{stngw_id}:{asset_number_code}"
        if key in self.maintenance_mode:
            del self.maintenance_mode[key]
            logger.info(f"Maintenance mode cleared for {asset_number_code}")
    
    def _should_generate_alert(
        self,
        station_id: int,
        asset_number_code: str,
        cause_code: str,
        alert_type: AlertType,
        db: Session
    ) -> bool:
        """Check if an alert should be generated (deduplication logic)"""
        key = build_alert_key(station_id, asset_number_code, cause_code, alert_type.value)

        # If alert already active in memory, don't generate another
        if key in self.active_alerts:
            return False

        # 1. Sync from DB if active alert exists but is not in memory cache (e.g. after a restart)
        existing_db = db.query(AlertEvent).filter(
            AlertEvent.station_id == station_id,
            AlertEvent.asset_no == asset_number_code,
            AlertEvent.cause == cause_code,
            AlertEvent.alert_status == "Active"
        ).first()
        if existing_db:
            self.active_alerts[key] = {
                "alert_id": existing_db.id,
                "timestamp": existing_db.alert_time
            }
            return False
        
        # If this is a FAILURE alert, check if there's an active PREDICTIVE alert
        # for the same asset and matching cause. If so, resolve it.
        if alert_type == AlertType.FAILURE:
            FAILURE_TO_PREDICTIVE_MAP = {
                # IPS
                "IPS_110_DC_VOLT_FAIL": "IPS_110_DC_VOLT_LOW",
                "IPS_110_AC_SIG_VOLT_FAIL": "IPS_110_AC_SIG_VOLT_LOW",
                "IPS_110_AC_TR_VOLT_FAIL": "IPS_110_AC_TR_VOLT_LOW",
                "IPS_IIP_VOLT_FAIL": "IPS_IIP_VOLT_LOW",
                "IPS_SMR_1_VOLT_FAIL": "IPS_SMR_1_VOLT_LOW",
                "IPS_SMR_2_VOLT_FAIL": "IPS_SMR_2_VOLT_LOW",
                "IPS_SMR_3_VOLT_FAIL": "IPS_SMR_3_VOLT_LOW",
                "IPS_SMR_4_VOLT_FAIL": "IPS_SMR_4_VOLT_LOW",
                "IPS_SMR_5_VOLT_FAIL": "IPS_SMR_5_VOLT_LOW",
                "IPS_110_AC_SIG_2_VOLT_FAIL": "IPS_110_AC_SIG_2_VOLT_LOW",
                "IPS_110_AC_SIG_3_VOLT_FAIL": "IPS_110_AC_SIG_3_VOLT_LOW",
                "IPS_110_AC_SIG_4_VOLT_FAIL": "IPS_110_AC_SIG_4_VOLT_LOW",
                "IPS_110_AC_TR_2_VOLT_FAIL": "IPS_110_AC_TR_2_VOLT_LOW",
                "IPS_110_AC_TR_3_VOLT_FAIL": "IPS_110_AC_TR_3_VOLT_LOW",
                "IPS_110_AC_TR_4_VOLT_FAIL": "IPS_110_AC_TR_4_VOLT_LOW",
                "IPS_DC_R_INT_VOLT_FAIL": "IPS_DC_R_INT_VOLT_LOW",
                "IPS_DC_R_EXT_VOLT_FAIL": "IPS_DC_R_EXT_VOLT_LOW",
                "IPS_DC_AXLE_C_VOLT_FAIL": "IPS_DC_AXLE_C_VOLT_LOW",
                "IPS_DC_PAN_IND_VOLT_FAIL": "IPS_DC_PAN_IND_VOLT_LOW",
                "IPS_DC_BLOCK_LOCAL_VOLT_FAIL": "IPS_DC_BLOCK_LOCAL_VOLT_LOW",
                "IPS_DC_HKT_MAG_VOLT_FAIL": "IPS_DC_HKT_MAG_VOLT_LOW",
                "IPS_DC_BLOCK_LINE_UP_VOLT_FAIL": "IPS_DC_BLOCK_LINE_UP_VOLT_LOW",
                "IPS_DC_BLOCK_LINE_DN_VOLT_FAIL": "IPS_DC_BLOCK_LINE_DN_VOLT_LOW",
                "IPS_DC_BLOCK_TEL_UP_VOLT_FAIL": "IPS_DC_BLOCK_TEL_UP_VOLT_LOW",
                "IPS_DC_BLOCK_TEL_DN_VOLT_FAIL": "IPS_DC_BLOCK_TEL_DN_VOLT_LOW",
                "IPS_DC_DATALOG_VOLT_FAIL": "IPS_DC_DATALOG_VOLT_LOW",
                "IPS_DC_EI_VOLT_FAIL": "IPS_DC_EI_VOLT_LOW",
                "IPS_BATT_CHAR_CURR_FAIL": "IPS_BATT_CHAR_CURR_LOW",
                "IPS_BATT_CHAR_CURR_OVER": "IPS_BATT_CHAR_CURR_LOW",
                
                # Signal
                "SIG_DG_VOLT_CURR_FAIL": "SIG_DG_VOLT_CURR_LOW",
                "SIG_HG_VOLT_CURR_FAIL": "SIG_HG_VOLT_CURR_LOW",
                "SIG_HHG_VOLT_CURR_FAIL": "SIG_HHG_VOLT_CURR_LOW",
                "SIG_RG_VOLT_CURR_FAIL": "SIG_RG_VOLT_CURR_LOW",
                "SIG_UNKNOWN_VOLT_CURR_FAIL": "SIG_UNKNOWN_VOLT_CURR_LOW",
                "SIG_DPR_VOLT_FAIL": "SIG_DPR_VOLT_CURR_LOW",
                "SIG_HPR_VOLT_FAIL": "SIG_HPR_VOLT_CURR_LOW",
                "SIG_HHPR_VOLT_FAIL": "SIG_HHPR_VOLT_CURR_LOW",
                "COSIG_ASPECT_VOLT_CURR_FAIL": "COSIG_ASPECT_VOLT_CURR_LOW",
                "ROSIG_ASPECT_VOLT_CURR_FAIL": "ROSIG_ASPECT_VOLT_CURR_LOW",
                
                # Track Circuit
                "TC_TFC_OP_VOLT_FAIL": "TC_TFC_OP_VOLT_LOW",
                "TC_SHORT": "TC_TR_VOLT_LOW",
                
                # Point Machine
                "PT_N_VOLT_CURR_FAIL": "PT_N_VOLT_CURR_LOW",
                "PT_R_VOLT_CURR_FAIL": "PT_R_VOLT_CURR_LOW",
                "PT_N_OBS": "PT_N_TIME_HIGH",
                "PT_R_OBS": "PT_R_TIME_HIGH",
            }
            
            pred_cause = FAILURE_TO_PREDICTIVE_MAP.get(cause_code)
            if not pred_cause:
                if cause_code.endswith("_FAIL"):
                    pred_cause = cause_code[:-5] + "_LOW"
                elif cause_code.endswith("_OVER"):
                    pred_cause = cause_code[:-5] + "_LOW"
                else:
                    pred_cause = cause_code
            
            pred_key = build_alert_key(station_id, asset_number_code, pred_cause, AlertType.PREDICTIVE.value)

            if pred_key in self.active_alerts:
                self._resolve_alert(pred_key, f"Escalated to Failure ({cause_code})", db)
            else:
                # Also look up in DB to resolve it if it exists active in DB
                existing_pred = db.query(AlertEvent).filter(
                    AlertEvent.station_id == station_id,
                    AlertEvent.asset_no == asset_number_code,
                    AlertEvent.cause == pred_cause,
                    AlertEvent.alert_status == "Active"
                ).first()
                if existing_pred:
                    # Sync to memory first
                    self.active_alerts[pred_key] = {
                        "alert_id": existing_pred.id,
                        "timestamp": existing_pred.alert_time
                    }
                    self._resolve_alert(pred_key, f"Escalated to Failure ({cause_code})", db)
        
        # Check if same cause was recently cleared
        if key in self.alert_history:
            cleared_time = self.alert_history[key]
            # If cleared within last hour, don't regenerate
            if (datetime.now() - cleared_time).total_seconds() < 3600:
                return False
        
        return True

    def _resolve_alert(self, key: str, reason: str, db: Session):
        """Resolve an active alert and move it to history."""
        if key in self.active_alerts:
            alert_data = self.active_alerts.pop(key)
            alert_id = alert_data.get("alert_id")
            
            # Track in history
            self.alert_history[key] = datetime.now()
            
            if alert_id:
                try:
                    record = db.query(AlertEvent).filter(AlertEvent.id == alert_id).first()
                    if record:
                        record.alert_status = "Cleared"
                        record.rectification_time = datetime.utcnow()
                        record.remark = f"Auto-resolved: {reason}"
                        db.commit()
                        db.refresh(record)
                        try:
                            from app.routers.alerts import _broadcast_alert_update
                            _broadcast_alert_update(record)
                        except Exception as ex:
                            logger.error(f"Failed to broadcast alert resolution: {ex}")
                        logger.info(f"Alert {alert_id} resolved in DB: {reason}")
                except Exception as e:
                    logger.error(f"Error updating resolved alert in DB: {e}")
    
    def _generate_alert(
        self,
        station_id: int,
        asset_id: int,
        asset_number_code: str,
        asset_type_hex: str,
        cause_code: str,
        cause_detail: str,
        alert_type: AlertType,
        timestamp: datetime,
        db: Session
    ) -> Optional[AlertEvent]:
        """Generate and store an alert using existing router"""
        
        if not self._should_generate_alert(station_id, asset_number_code, cause_code, alert_type, db):
            return None
        
        # Import here to avoid circular imports
        from app.routers.alerts import create_alert_event
        
        payload = AlertEventCreate(
            station_id=station_id,
            alert_type=alert_type.value,
            asset_type_hex=asset_type_hex,
            asset_no=asset_number_code,
            cause=cause_code,
            alert_status="Active",
            alert_time=timestamp,
            remark=cause_detail
        )
        
        try:
            # Call the existing create function
            alert = create_alert_event(payload, db)
            
            # Track active alert
            key = build_alert_key(station_id, asset_number_code, cause_code, alert_type.value)
            self.active_alerts[key] = {
                "alert_id": alert.id,
                "timestamp": timestamp
            }
            logger.info(f"Generated {alert_type.value} alert for {asset_number_code}: {cause_code}")
            return alert
        except HTTPException as e:
            if "suppressed" in str(e.detail):
                logger.info(f"Alert suppressed: {asset_number_code} - {cause_code}")
            else:
                logger.error(f"Error creating alert: {e.detail}")
            return None
        except Exception as e:
            logger.error(f"Error creating alert: {e}")
            return None

    def _evaluate_point_machine_logics(
        self, gateway_id: int, stngw_id: str, para_id: str, value: float, timestamp: str, asset: Asset, db: Session
    ) -> List[Dict]:
        from app.services.logics.point_machine import PointMachineLogics
        predictive = PointMachineLogics.check_predictive_alerts(gateway_id, stngw_id, para_id, value, timestamp, asset, db)
        failure = PointMachineLogics.check_failure_alerts(gateway_id, stngw_id, para_id, value, timestamp, asset, db)
        return predictive + failure

    def _evaluate_track_circuit_logics(
        self, gateway_id: int, stngw_id: str, para_id: str, value: float, timestamp: str, asset: Asset, db: Session
    ) -> List[Dict]:
        from app.services.logics.track_circuit import TrackCircuitLogics
        predictive = TrackCircuitLogics.check_predictive_alerts(gateway_id, stngw_id, para_id, value, timestamp, asset, db)
        failure = TrackCircuitLogics.check_failure_alerts(gateway_id, stngw_id, para_id, value, timestamp, asset, db)
        return predictive + failure

    def _evaluate_signal_logics(
        self, gateway_id: int, stngw_id: str, para_id: str, value: float, timestamp: str, asset: Asset, db: Session
    ) -> List[Dict]:
        from app.services.logics.signal import SignalLogics
        predictive = SignalLogics.check_predictive_alerts(gateway_id, stngw_id, para_id, value, timestamp, asset, db)
        failure = SignalLogics.check_failure_alerts(gateway_id, stngw_id, para_id, value, timestamp, asset, db)
        return predictive + failure

    def _evaluate_ips_logics(
        self, gateway_id: int, stngw_id: str, para_id: str, value: float, timestamp: str, asset: Asset, db: Session
    ) -> List[Dict]:
        from app.services.logics.ips import IPSLogics
        predictive = IPSLogics.check_predictive_alerts(gateway_id, stngw_id, para_id, value, timestamp, asset, db)
        failure = IPSLogics.check_failure_alerts(gateway_id, stngw_id, para_id, value, timestamp, asset, db)
        return predictive + failure

# Singleton instance
alert_engine = AlertEngine()
