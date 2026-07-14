from typing import Dict, List, Optional, Tuple
from sqlalchemy.orm import Session
from app.models.models import Asset
from app.services.alert_engine import AlertType
from app.services.parameter_config_service import param_config_service

class SignalLogics:
    """
    Implementation of Signal logics from Annexure C §2.4 (Main Signal),
    §2.5 (Calling ON Signal), §2.6 (Route Signal), §2.7 (Shunt Signal).

    All four signal asset types (asset_type_hex "10"/"11"/"12"/"13") route
    here from alert_engine._evaluate_signal_logics(). Each code family below
    is checked against param_config.min_safe/max_safe/min_fail exactly the
    same way — only the code prefix and the aspect label differ.
    """

    LD = 80  # Lower deviation for predictive
    HD = 120  # Higher deviation

    # (code prefix as it appears in parameter_representation_code, signal-type
    #  label used in cause codes, aspect label used in cause codes)
    # Main Signal keeps its original cause codes ("SIG_DG_...") unchanged so
    # existing alert history / dashboards keep working.
    _MAIN_ASPECTS = ["HHG", "DG", "HG", "RG"]  # HHG checked before HG (HG is a substring of HHG)
    _SHUNT_ASPECTS = ["ON", "OFF", "PILOT"]

    @staticmethod
    def _identify(code: str) -> Optional[Tuple[str, str]]:
        """
        Returns (signal_type, aspect) for a given parameter_representation_code,
        or None if it doesn't belong to any known signal family.
        signal_type is one of: MAIN, CALLING_ON, ROUTE, SHUNT
        """
        if "VSIG" in code or "ISIG" in code:
            for aspect in SignalLogics._MAIN_ASPECTS:
                if aspect in code:
                    return ("MAIN", aspect)
            return None

        if "COSIG" in code:
            return ("CALLING_ON", "ASPECT")

        if "ROSIG" in code:
            return ("ROUTE", "ASPECT")

        if "SHSIG" in code:
            for aspect in SignalLogics._SHUNT_ASPECTS:
                if aspect in code:
                    return ("SHUNT", aspect)
            return None

        return None

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
        """Check all predictive logics for signals (Main/Calling ON/Route/Shunt)"""
        alerts = []

        param_config = param_config_service.get_parameter_config(para_id)
        if not param_config:
            return alerts

        identified = SignalLogics._identify(param_config.parameter_representation_code)
        if not identified:
            return alerts
        signal_type, aspect = identified

        # cause_code prefix stays "SIG" for Main Signal (unchanged, backward
        # compatible); the other three signal types get their own prefix.
        prefix = {
            "MAIN": "SIG",
            "CALLING_ON": "COSIG",
            "ROUTE": "ROSIG",
            "SHUNT": "SHSIG",
        }[signal_type]

        label = f"{aspect}_" if aspect != "ASPECT" else ""

        if param_config.min_safe is not None and value < param_config.min_safe:
            alerts.append({
                "cause_code": f"{prefix}_{label}VOLT_CURR_LOW",
                "cause_detail": f"{signal_type.replace('_', ' ').title()} Signal predictive Alert: Voltage or Current of {aspect if aspect != 'ASPECT' else 'signal'} Aspect Low.",
                "alert_type": AlertType.PREDICTIVE
            })

        if param_config.max_safe is not None and value > param_config.max_safe:
            alerts.append({
                "cause_code": f"{prefix}_{label}CURR_HIGH",
                "cause_detail": f"{signal_type.replace('_', ' ').title()} Signal predictive Alert: Current of {aspect if aspect != 'ASPECT' else 'signal'} Aspect high.",
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
        """Check all failure logics for signals (Main/Calling ON/Route/Shunt)"""
        alerts = []

        param_config = param_config_service.get_parameter_config(para_id)
        if not param_config:
            return alerts

        if param_config.min_fail is None or value >= param_config.min_fail:
            return alerts

        identified = SignalLogics._identify(param_config.parameter_representation_code)
        if not identified:
            return alerts
        signal_type, aspect = identified

        # Main Signal keeps its exact original cause codes/messages.
        if signal_type == "MAIN":
            if aspect == "DG":
                alerts.append({"cause_code": "SIG_DG_VOLT_CURR_FAIL",
                                "cause_detail": "Sig No. DG Aspect failed. Voltage or Current of DG Aspect failed.",
                                "alert_type": AlertType.FAILURE})
            elif aspect == "HG":
                alerts.append({"cause_code": "SIG_HG_VOLT_CURR_FAIL",
                                "cause_detail": "Sig No. HG Aspect failed. Voltage or Current of HG Aspect failed.",
                                "alert_type": AlertType.FAILURE})
            elif aspect == "HHG":
                alerts.append({"cause_code": "SIG_HHG_VOLT_CURR_FAIL",
                                "cause_detail": "Sig No. HHG Aspect failed. Voltage or Current of HHG Aspect failed.",
                                "alert_type": AlertType.FAILURE})
            elif aspect == "RG":
                alerts.append({"cause_code": "SIG_RG_VOLT_CURR_FAIL",
                                "cause_detail": "Sig No. RG Aspect failed. HR DN. Signal blank in ON position.",
                                "alert_type": AlertType.FAILURE})
            return alerts

        if signal_type == "CALLING_ON":
            alerts.append({"cause_code": "COSIG_VOLT_CURR_FAIL",
                            "cause_detail": "Calling ON Signal failed. Voltage or Current of Aspect failed.",
                            "alert_type": AlertType.FAILURE})
            return alerts

        if signal_type == "ROUTE":
            alerts.append({"cause_code": "ROSIG_VOLT_CURR_FAIL",
                            "cause_detail": "Route Signal failed. Voltage or Current of Aspect failed.",
                            "alert_type": AlertType.FAILURE})
            return alerts

        if signal_type == "SHUNT":
            alerts.append({"cause_code": f"SHSIG_{aspect}_VOLT_CURR_FAIL",
                            "cause_detail": f"Shunt Signal {aspect} Aspect failed. Voltage or Current failed.",
                            "alert_type": AlertType.FAILURE})
            return alerts

        return alerts
