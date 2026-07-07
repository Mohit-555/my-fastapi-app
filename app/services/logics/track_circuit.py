from typing import Dict, List
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from app.models.models import Telemetry, Asset
from app.services.alert_engine import AlertType
from app.services.parameter_config_service import param_config_service

class TrackCircuitLogics:
    """Implementation of Track Circuit logics from Annexure C §2.3"""
    
    # Threshold percentages (from Annexure C)
    LD1 = 80
    LD2 = 50
    LD3 = 90
    HD1 = 120
    HD2 = 150
    
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
        """Check all predictive logics for track circuit (Section 2.3(a))"""
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
        
        param_config = param_config_service.get_parameter_config(para_id)
        
        if not param_config:
            return alerts
        
        # Logic 1: Track Circuit predictive Alert - TFC input voltage Low
        if param_config.parameter_representation_code == "VTC TFC IP":
            threshold = min(avg_value * (TrackCircuitLogics.LD1 / 100), param_config.min_safe or float('inf'))
            if value < threshold:
                alerts.append({
                    "cause_code": "TC_TFC_IP_VOLT_LOW",
                    "cause_detail": "Track Ckt predictive Alert: TFC input voltage Low/failed in Loc.",
                    "alert_type": AlertType.PREDICTIVE
                })
        
        # Logic 2: Track Circuit predictive Alert - TFC output voltage Low
        elif param_config.parameter_representation_code == "VTC TFC O/P":
            threshold = min(avg_value * (TrackCircuitLogics.LD1 / 100), param_config.min_safe or float('inf'))
            if value < threshold:
                alerts.append({
                    "cause_code": "TC_TFC_OP_VOLT_LOW",
                    "cause_detail": "Track Ckt predictive Alert: Battery charging but TFC output voltage Low.",
                    "alert_type": AlertType.PREDICTIVE
                })
        
        # Logic 3: Track Circuit predictive Alert - Battery charging current high/low
        elif param_config.parameter_representation_code == "ITC BATT CHARG":
            if param_config.max_safe is not None and value > param_config.max_safe:
                alerts.append({
                    "cause_code": "TC_BT_CHG_CURR_HIGH",
                    "cause_detail": "Track Ckt predictive Alert: Battery charging current high.",
                    "alert_type": AlertType.PREDICTIVE
                })
            elif param_config.min_safe is not None and value < param_config.min_safe:
                alerts.append({
                    "cause_code": "TC_BT_CHG_CURR_LOW",
                    "cause_detail": "Track Ckt predictive Alert: Battery not charging.",
                    "alert_type": AlertType.PREDICTIVE
                })
        
        # Logic 4: Track Circuit predictive Alert - Track Relay voltage low
        elif param_config.parameter_representation_code == "VTC TR":
            threshold = min(avg_value * (TrackCircuitLogics.LD1 / 100), param_config.min_safe or float('inf'))
            if value < threshold:
                alerts.append({
                    "cause_code": "TC_TR_VOLT_LOW",
                    "cause_detail": "Track Ckt predictive Alert: Track Relay Voltage Low/ Under energization.",
                    "alert_type": AlertType.PREDICTIVE
                })
        
        # Logic 5: Track Circuit predictive Alert - Track Relay voltage high
        elif param_config.parameter_representation_code == "VTC TR":
            threshold = max(avg_value * (TrackCircuitLogics.HD1 / 100), param_config.max_safe or 0)
            if value > threshold:
                alerts.append({
                    "cause_code": "TC_TR_OVER_ENERIZATION",
                    "cause_detail": "Track Ckt predictive Alert: Track Relay Voltage high/Over energization.",
                    "alert_type": AlertType.PREDICTIVE
                })
        
        # Logic 6: Track Circuit predictive Alert - Feed End Choke Resistance
        elif param_config.parameter_representation_code == "RTC CH FEED END":
            if value < (avg_value * 0.5):
                alerts.append({
                    "cause_code": "TC_CH_RES_LOW",
                    "cause_detail": "Track Ckt predictive Alert: Feed End Choke Resistance Low or short.",
                    "alert_type": AlertType.PREDICTIVE
                })
            elif value > (avg_value * 1.5):
                alerts.append({
                    "cause_code": "TC_CH_RES_HIGH",
                    "cause_detail": "Track Ckt predictive Alert: Feed End Choke Resistance High.",
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
        """Check all failure logics for track circuit (Section 2.3(b))"""
        alerts = []
        
        param_config = param_config_service.get_parameter_config(para_id)
        
        if not param_config:
            return alerts
        
        # Check failure conditions
        if param_config.min_fail is not None and value < param_config.min_fail:
            if param_config.parameter_representation_code == "ITC RELAY END":
                alerts.append({
                    "cause_code": "TC_SHORT",
                    "cause_detail": "Track Ckt failed. TR Down. Possible shorting in track.",
                    "alert_type": AlertType.FAILURE
                })
            elif param_config.parameter_representation_code == "VTC TFC O/P":
                alerts.append({
                    "cause_code": "TC_TFC_OP_VOLT_FAIL",
                    "cause_detail": "Track Ckt failed. TFC output voltage failed.",
                    "alert_type": AlertType.FAILURE
                })
        
        return alerts
