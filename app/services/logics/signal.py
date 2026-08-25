from typing import Dict, List, Optional, Tuple
import logging
from sqlalchemy.orm import Session
from app.models.models import Asset
from app.services.alert_engine import AlertType
from app.services.parameter_config_service import param_config_service

logger = logging.getLogger("signal_logics")

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
    _MAIN_PR_VOLTS = ["HHPR", "DPR", "HPR"]    # HHPR checked before HPR (HPR is a substring of HHPR)
    _SHUNT_ASPECTS = ["ON", "OFF", "PILOT"]

    _CURRENT_TYPE_IDS = {"00", "01", "10", "11"}   # DC-A, DC-mA, AC-A, AC-mA

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
            for pr_volt in SignalLogics._MAIN_PR_VOLTS:
                if pr_volt in code:
                    return ("MAIN", pr_volt)
            logger.warning(f"Unknown aspect for MAIN signal parameter: {code}")
            return ("MAIN", "UNKNOWN")

        if "COSIG" in code:
            return ("CALLING_ON", "ASPECT")

        if "ROSIG" in code:
            return ("ROUTE", "ASPECT")

        if "SHSIG" in code:
            for aspect in SignalLogics._SHUNT_ASPECTS:
                if aspect in code:
                    return ("SHUNT", aspect)
            logger.warning(f"Unknown aspect for SHUNT signal parameter: {code}")
            return ("SHUNT", "UNKNOWN")

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

        param_config = param_config_service.get_effective_config(db, para_id, asset.station_id)
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

        label = f"{aspect}_"
        # Annexure C defines a high-side predictive (CURR HIGH) only for
        # current parameters. Voltage-high is emitted as a clearly-named
        # vendor extension (VOLT_HIGH) so over-voltage is never mislabeled
        # as a current alert.
        is_current_param = param_config.parameter_type_id in SignalLogics._CURRENT_TYPE_IDS

        if param_config.min_safe is not None and value < param_config.min_safe:
            alerts.append({
                "cause_code": f"{prefix}_{label}VOLT_CURR_LOW",
                "cause_detail": f"{signal_type.replace('_', ' ').title()} Signal predictive Alert: Voltage or Current of {aspect if aspect != 'ASPECT' else 'signal'} Aspect Low.",
                "alert_type": AlertType.PREDICTIVE
            })

        if param_config.max_safe is not None and value > param_config.max_safe:
            high_code = f"{prefix}_{label}CURR_HIGH" if is_current_param else f"{prefix}_{label}VOLT_HIGH"
            alerts.append({
                "cause_code": high_code,
                "cause_detail": f"{signal_type.replace('_', ' ').title()} Signal predictive Alert: {'Current' if is_current_param else 'Voltage'} of {aspect if aspect != 'ASPECT' else 'signal'} Aspect high.",
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

        param_config = param_config_service.get_effective_config(db, para_id, asset.station_id)
        if not param_config:
            return alerts

        # Bimodal (relay-gated) parameters — e.g. Shunt ON aspect carries
        # Min-fail ABOVE its lit band (spec Max safe=58 / Min fail=90), so a
        # plain `value < min_fail` check would fire on every normal sample.
        # Correct evaluation needs the SH-HR relay state (Annexure C §2.7);
        # until that is implemented, skip failure generation for them.
        if (param_config.min_fail is not None
                and param_config.max_safe is not None
                and param_config.min_fail > param_config.max_safe):
            logger.debug(
                "Skipping failure check for %s: min_fail (%s) sits above "
                "max_safe (%s); requires relay-gated evaluation.",
                param_config.parameter_representation_code,
                param_config.min_fail, param_config.max_safe
            )
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
                                "cause_detail": "Sig No. RG Aspect failed. Voltage or Current of RG Aspect failed.",
                                "alert_type": AlertType.FAILURE})
            elif aspect in SignalLogics._MAIN_PR_VOLTS:
                alerts.append({"cause_code": f"SIG_{aspect}_VOLT_FAIL",
                                "cause_detail": f"Sig No. {aspect} Voltage failed.",
                                "alert_type": AlertType.FAILURE})
            else:
                alerts.append({"cause_code": "SIG_UNKNOWN_VOLT_CURR_FAIL",
                                "cause_detail": f"Sig No. Unknown Aspect failed. Aspect: {aspect}.",
                                "alert_type": AlertType.FAILURE})
            return alerts

        if signal_type == "CALLING_ON":
            alerts.append({"cause_code": "COSIG_ASPECT_VOLT_CURR_FAIL",
                            "cause_detail": "Calling ON Signal failed. Voltage or Current of Aspect failed.",
                            "alert_type": AlertType.FAILURE})
            return alerts

        if signal_type == "ROUTE":
            alerts.append({"cause_code": "ROSIG_ASPECT_VOLT_CURR_FAIL",
                            "cause_detail": "Route Signal failed. Voltage or Current of Aspect failed.",
                            "alert_type": AlertType.FAILURE})
            return alerts

        if signal_type == "SHUNT":
            alerts.append({"cause_code": f"SHSIG_{aspect}_VOLT_CURR_FAIL",
                            "cause_detail": f"Shunt Signal {aspect} Aspect failed. Voltage or Current failed.",
                            "alert_type": AlertType.FAILURE})
            return alerts

        return alerts
