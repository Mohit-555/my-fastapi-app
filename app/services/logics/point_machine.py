from typing import Dict, List, Optional
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from app.models.models import Telemetry, Asset
from app.services.alert_engine import AlertType
from app.services.parameter_config_service import param_config_service

class PointMachineLogics:
    """Implementation of Point Machine logics from Annexure C §2.2"""
    
    # Threshold percentages (from Annexure C)
    LD1 = 80  # Lower deviation for predictive
    LD2 = 90  # Lower deviation for cable check
    HD = 150  # Higher deviation
    
    @staticmethod
    def check_predictive_alerts(
        gateway_id: int,
        stngw_id: str,
        para_id: str,
        value: float,
        timestamp: str,
        asset: Asset,
        db: Session
    ) -> List[Dict]:
        """Check all predictive logics for point machine (Section 2.2(a))"""
        alerts = []
        
        # Get recent data for average calculation
        recent_data = db.query(Telemetry).filter(
            Telemetry.gateway_id == gateway_id,
            Telemetry.para_id == para_id,
            Telemetry.prt >= (datetime.utcnow() - timedelta(days=15)).isoformat()
        ).order_by(Telemetry.prt.desc()).limit(100).all()
        
        if not recent_data:
            return alerts
        
        # Calculate average (excluding failures)
        values = [t.prv for t in recent_data if t.prv is not None]
        if not values:
            return alerts
        avg_value = sum(values) / len(values)
        
        # Get parameter config
        param_config = param_config_service.get_parameter_config(para_id)
        if not param_config:
            return alerts
        
        # Logic 1: Predictive Alert - Normal Voltage/Current Low at Loc
        if para_id.startswith("0001") or param_config.parameter_representation_code in ["VPT 110 DC LOC N", "IPT N"]:
            # Check for normal operation voltage/current low
            if param_config.parameter_representation_code in ["VPT 110 DC LOC N", "IPT N"]:
                threshold = min(avg_value * (PointMachineLogics.LD1 / 100), param_config.min_safe or float('inf'))
                
                if value < threshold:
                    alerts.append({
                        "cause_code": "PT_N_VOLT_CURR_LOW",
                        "cause_detail": "Predictive Alert: Voltage or Current for Normal operation Low at Loc",
                        "alert_type": AlertType.PREDICTIVE
                    })
            
            # Logic 2: Predictive Alert - Reverse Voltage/Current Low at Loc
            elif param_config.parameter_representation_code in ["VPT 110 DC LOC R", "IPT R"]:
                threshold = min(avg_value * (PointMachineLogics.LD1 / 100), param_config.min_safe or float('inf'))
                
                if value < threshold:
                    alerts.append({
                        "cause_code": "PT_R_VOLT_CURR_LOW",
                        "cause_detail": "Predictive Alert: Voltage or Current for Reverse operation Low at Loc",
                        "alert_type": AlertType.PREDICTIVE
                    })
        
        return alerts
    
    @staticmethod
    def check_failure_alerts(
        gateway_id: int,
        stngw_id: str,
        para_id: str,
        value: float,
        timestamp: str,
        asset: Asset,
        db: Session
    ) -> List[Dict]:
        """Check all failure logics for point machine (Section 2.2(b))"""
        alerts = []
        
        # Get parameter config
        param_config = param_config_service.get_parameter_config(para_id)
        
        if not param_config:
            return alerts
        
        # Check failure conditions
        if param_config.min_fail is not None and value < param_config.min_fail:
            # Determine which failure logic applies
            if "VPT 110 DC LOC N" in param_config.parameter_representation_code:
                alerts.append({
                    "cause_code": "PT_N_IND_VOLT_FAIL_AT_LOC",
                    "cause_detail": "Point failed in Normal. Normal Indication Voltage at Loc is low/failed/detection break.",
                    "alert_type": AlertType.FAILURE
                })
            elif "VPT 110 DC LOC R" in param_config.parameter_representation_code:
                alerts.append({
                    "cause_code": "PT_R_IND_VOLT_FAIL_AT_LOC",
                    "cause_detail": "Point failed in Reverse. Reverse Indication Voltage at Loc is low/failed/detection break.",
                    "alert_type": AlertType.FAILURE
                })
            elif "IPT N" in param_config.parameter_representation_code:
                alerts.append({
                    "cause_code": "PT_N_VOLT_CURR_FAIL",
                    "cause_detail": "Point failed in Normal. Voltage or Current for normal operation in Loc failed.",
                    "alert_type": AlertType.FAILURE
                })
            elif "IPT R" in param_config.parameter_representation_code:
                alerts.append({
                    "cause_code": "PT_R_VOLT_CURR_FAIL",
                    "cause_detail": "Point failed in Reverse. Voltage or Current for reverse operation in Loc failed.",
                    "alert_type": AlertType.FAILURE
                })
        
        # Check obstruction logic
        if param_config.parameter_representation_code in ["TPT N", "TPT R"]:
            if param_config.max_safe is not None and value > param_config.max_safe:
                alerts.append({
                    "cause_code": "PT_N_OBS" if "N" in param_config.parameter_representation_code else "PT_R_OBS",
                    "cause_detail": "Point failed. Normal/Reverse operation time high. Point in Obstruction.",
                    "alert_type": AlertType.FAILURE
                })
        
        return alerts
