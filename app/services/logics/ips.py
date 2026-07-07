from typing import Dict, List
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from app.models.models import Telemetry, Asset
from app.services.alert_engine import AlertType
from app.services.parameter_config_service import param_config_service

class IPSLogics:
    """Implementation of IPS logics from Annexure C §2.1"""
    
    LD = 90  # Lower deviation for IPS predictive
    
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
        """Check all predictive logics for IPS (Section 2.1(a))"""
        alerts = []
        
        param_config = param_config_service.get_parameter_config(para_id)
        
        if not param_config:
            return alerts
        
        # Get recent data for average calculation
        recent_data = db.query(Telemetry).filter(
            Telemetry.gateway_id == gateway_id,
            Telemetry.para_id == para_id,
            Telemetry.prt >= (datetime.utcnow() - timedelta(days=15)).isoformat()
        ).order_by(Telemetry.prt.desc()).limit(100).all()
        
        if not recent_data:
            return alerts
        
        values = [t.prv for t in recent_data if t.prv is not None]
        if not values:
            return alerts
        avg_value = sum(values) / len(values)
        
        # Check all IPS voltage outputs
        if "VIPS" in param_config.parameter_representation_code or "IIPS" in param_config.parameter_representation_code:
            threshold = min(avg_value * (IPSLogics.LD / 100), param_config.min_safe or float('inf'))
            if value < threshold:
                # Map to appropriate cause code
                cause_map = {
                    "VIPS IIP": "IPS_IIP_VOLT_LOW",
                    "VIPS 110 DC": "IPS_110_DC_VOLT_LOW",
                    "VIPS SIG-1 110 AC": "IPS_110_AC_SIG_VOLT_LOW",
                    "VIPS TR-1 110 AC": "IPS_110_AC_TR_VOLT_LOW",
                    "VIPS SMR-1 110 DC": "IPS_SMR_1_VOLT_LOW",
                    "VIPS DC R INT": "IPS_DC_R_INT_VOLT_LOW",
                    "VIPS DC R EXT": "IPS_DC_R_EXT_VOLT_LOW",
                    "VIPS DC AXLE C": "IPS_DC_AXLE_C_VOLT_LOW",
                    "VIPS DC PAN IND": "IPS_DC_PAN_IND_VOLT_LOW",
                    "VIPS DC BLOCK LOCAL": "IPS_DC_BLOCK_LOCAL_VOLT_LOW",
                    "VIPS DC HKT MAG": "IPS_DC_HKT_MAG_VOLT_LOW",
                    "VIPS DC BLOCK LINE UP": "IPS_DC_BLOCK_LINE_UP_VOLT_LOW",
                    "VIPS DC BLOCK LINE DN": "IPS_DC_BLOCK_LINE_DN_VOLT_LOW",
                    "VIPS DC BLOCK TEL UP": "IPS_DC_BLOCK_TEL_UP_VOLT_LOW",
                    "VIPS DC BLOCK TEL DN": "IPS_DC_BLOCK_TEL_DN_VOLT_LOW",
                    "VIPS DC DATALOG": "IPS_DC_DATALOG_VOLT_LOW",
                    "VIPS DC EI": "IPS_DC_EI_VOLT_LOW",
                    "IIPS BATT CHAR 110 DC": "IPS_BATT_CHAR_CURR_LOW"
                }
                
                for key, cause_code in cause_map.items():
                    if key in param_config.parameter_representation_code:
                        alerts.append({
                            "cause_code": cause_code,
                            "cause_detail": f"IPS predictive Alert: {key} low.",
                            "alert_type": AlertType.PREDICTIVE
                        })
                        break
        
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
        """Check all failure logics for IPS (Section 2.1(b))"""
        alerts = []
        
        param_config = param_config_service.get_parameter_config(para_id)
        
        if not param_config:
            return alerts
        
        if param_config.min_fail is not None and value < param_config.min_fail:
            # Map to appropriate failure cause
            cause_map = {
                "VIPS IIP": "IPS_IIP_VOLT_FAIL",
                "VIPS 110 DC": "IPS_110_DC_VOLT_FAIL",
                "VIPS SIG-1 110 AC": "IPS_110_AC_SIG_VOLT_FAIL",
                "VIPS TR-1 110 AC": "IPS_110_AC_TR_VOLT_FAIL",
                "VIPS SMR-1 110 DC": "IPS_SMR_1_VOLT_FAIL",
                "VIPS DC R INT": "IPS_DC_R_INT_VOLT_FAIL",
                "VIPS DC R EXT": "IPS_DC_R_EXT_VOLT_FAIL",
                "VIPS DC AXLE C": "IPS_DC_AXLE_C_VOLT_FAIL",
                "VIPS DC PAN IND": "IPS_DC_PAN_IND_VOLT_FAIL",
                "VIPS DC BLOCK LOCAL": "IPS_DC_BLOCK_LOCAL_VOLT_FAIL",
                "VIPS DC HKT MAG": "IPS_DC_HKT_MAG_VOLT_FAIL",
                "VIPS DC BLOCK LINE UP": "IPS_DC_BLOCK_LINE_UP_VOLT_FAIL",
                "VIPS DC BLOCK LINE DN": "IPS_DC_BLOCK_LINE_DN_VOLT_FAIL",
                "VIPS DC BLOCK TEL UP": "IPS_DC_BLOCK_TEL_UP_VOLT_FAIL",
                "VIPS DC BLOCK TEL DN": "IPS_DC_BLOCK_TEL_DN_VOLT_FAIL",
                "VIPS DC DATALOG": "IPS_DC_DATALOG_VOLT_FAIL",
                "VIPS DC EI": "IPS_DC_EI_VOLT_FAIL",
                "IIPS BATT CHAR 110 DC": "IPS_BATT_CHAR_CURR_FAIL"
            }
            
            for key, cause_code in cause_map.items():
                if key in param_config.parameter_representation_code:
                    alerts.append({
                        "cause_code": cause_code,
                        "cause_detail": f"IPS failed. {key} failed.",
                        "alert_type": AlertType.FAILURE
                    })
                    break
        
        return alerts
