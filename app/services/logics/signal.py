from typing import Dict, List
from sqlalchemy.orm import Session
from app.models.models import Asset
from app.services.alert_engine import AlertType
from app.services.parameter_config_service import param_config_service

class SignalLogics:
    """Implementation of Signal logics from Annexure C §2.4-2.7"""
    
    LD = 80  # Lower deviation for predictive
    HD = 120  # Higher deviation
    
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
        """Check all predictive logics for signals"""
        alerts = []
        
        param_config = param_config_service.get_parameter_config(para_id)
        
        if not param_config:
            return alerts
        
        # Check for voltage/current low conditions
        if "VSIG" in param_config.parameter_representation_code or "ISIG" in param_config.parameter_representation_code:
            # Determine which aspect
            if "DG" in param_config.parameter_representation_code:
                aspect = "DG"
            elif "HG" in param_config.parameter_representation_code:
                aspect = "HG"
            elif "HHG" in param_config.parameter_representation_code:
                aspect = "HHG"
            elif "RG" in param_config.parameter_representation_code:
                aspect = "RG"
            else:
                return alerts
            
            # Predictive alert for low voltage/current
            if param_config.min_safe is not None and value < param_config.min_safe:
                alerts.append({
                    "cause_code": f"SIG_{aspect}_VOLT_CURR_LOW",
                    "cause_detail": f"Sig predictive Alert: Voltage or Current of {aspect} Aspect Low.",
                    "alert_type": AlertType.PREDICTIVE
                })
            
            # Predictive alert for high current
            if param_config.max_safe is not None and value > param_config.max_safe:
                alerts.append({
                    "cause_code": f"SIG_{aspect}_CURR_HIGH",
                    "cause_detail": f"Sig predictive Alert: Current of {aspect} Aspect high.",
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
        """Check all failure logics for signals"""
        alerts = []
        
        param_config = param_config_service.get_parameter_config(para_id)
        
        if not param_config:
            return alerts
        
        if param_config.min_fail is not None and value < param_config.min_fail:
            if "DG" in param_config.parameter_representation_code:
                alerts.append({
                    "cause_code": "SIG_DG_VOLT_CURR_FAIL",
                    "cause_detail": "Sig No. DG Aspect failed. Voltage or Current of DG Aspect failed.",
                    "alert_type": AlertType.FAILURE
                })
            elif "HG" in param_config.parameter_representation_code:
                alerts.append({
                    "cause_code": "SIG_HG_VOLT_CURR_FAIL",
                    "cause_detail": "Sig No. HG Aspect failed. Voltage or Current of HG Aspect failed.",
                    "alert_type": AlertType.FAILURE
                })
            elif "HHG" in param_config.parameter_representation_code:
                alerts.append({
                    "cause_code": "SIG_HHG_VOLT_CURR_FAIL",
                    "cause_detail": "Sig No. HHG Aspect failed. Voltage or Current of HHG Aspect failed.",
                    "alert_type": AlertType.FAILURE
                })
            elif "RG" in param_config.parameter_representation_code:
                alerts.append({
                    "cause_code": "SIG_RG_VOLT_CURR_FAIL",
                    "cause_detail": "Sig No. RG Aspect failed. HR DN. Signal blank in ON position.",
                    "alert_type": AlertType.FAILURE
                })
        
        return alerts
