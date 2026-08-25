import logging
from typing import Dict, List, Optional
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from app.models.models import Telemetry, Asset
from app.services.alert_engine import AlertType
from app.services.parameter_config_service import param_config_service
from app.services.timestamp_utils import parse_prt

logger = logging.getLogger(__name__)

class PointMachineLogics:
    """Implementation of Point Machine logics from Annexure C §2.2"""

    # Threshold percentages (from Annexure C)
    LD1 = 80  # Lower deviation for predictive
    LD2 = 90  # Lower deviation for cable check
    HD = 150  # Higher deviation

    @staticmethod
    def _norm(code: Optional[str]) -> str:
        """Normalize a parameter code for matching.

        The spec itself is inconsistent about whitespace — Annexure A writes
        "VPT110 DC LOC R" while Annexure C writes "VPT 110 DC LOC R" — so all
        comparisons go through this (uppercase, space-free) form.
        """
        return (code or "").upper().replace(" ", "")

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
        limit = 100
        # prt is a string in Annexure-B "DD-MM-YYYY" format — lexicographic
        # SQL comparison/ordering is meaningless for it. Order by id
        # (insertion order) and filter by the parsed timestamp instead.
        rows = db.query(Telemetry).filter(
            Telemetry.gateway_id == gateway_id,
            Telemetry.para_id == para_id
        ).order_by(Telemetry.id.desc()).limit(400).all()

        cutoff = datetime.utcnow() - timedelta(days=15)
        recent_data = []
        for row in rows:
            ts = parse_prt(row.prt)
            if ts is None and row.received_at is not None:
                ts = row.received_at.replace(tzinfo=None) if row.received_at.tzinfo else row.received_at
            if ts is not None and ts >= cutoff:
                recent_data.append(row)
            if len(recent_data) >= limit:
                break

        if not recent_data:
            return alerts

        # Calculate average (excluding failures)
        values = [t.prv for t in recent_data if t.prv is not None]
        if not values:
            return alerts
        avg_value = sum(values) / len(values)

        # Get parameter config (with DB threshold overrides for this station)
        param_config = param_config_service.get_effective_config(db, para_id, asset.station_id)
        if not param_config:
            return alerts

        code = PointMachineLogics._norm(param_config.parameter_representation_code)

        # Logic 1: Predictive Alert - Normal Voltage/Current Low at Loc
        if code in ("VPT110DCLOCN", "IPTN"):
            if param_config.min_safe is None:
                logger.debug("Point Machine IPT/N: min_safe not configured, skipping alert")
                return alerts
            # Spec semantics: "< LD % of avg value OR Min safe" — either
            # condition alone must raise the alert.
            threshold = max(avg_value * (PointMachineLogics.LD1 / 100), param_config.min_safe)

            if value < threshold:
                alerts.append({
                    "cause_code": "PT_N_VOLT_CURR_LOW",
                    "cause_detail": "Predictive Alert: Voltage or Current for Normal operation Low at Loc",
                    "alert_type": AlertType.PREDICTIVE
                })

        # Logic 2: Predictive Alert - Reverse Voltage/Current Low at Loc
        elif code in ("VPT110DCLOCR", "IPTR"):
            if param_config.min_safe is None:
                logger.debug("Point Machine IPT/R: min_safe not configured, skipping alert")
                return alerts
            threshold = max(avg_value * (PointMachineLogics.LD1 / 100), param_config.min_safe)

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

        # Get parameter config (with DB threshold overrides for this station)
        param_config = param_config_service.get_effective_config(db, para_id, asset.station_id)

        if not param_config:
            return alerts

        code = PointMachineLogics._norm(param_config.parameter_representation_code)

        # Check failure conditions
        if param_config.min_fail is not None and value < param_config.min_fail:
            # Determine which failure logic applies
            if "VPT110DCLOCN" in code:
                alerts.append({
                    "cause_code": "PT_N_IND_VOLT_FAIL_AT_LOC",
                    "cause_detail": "Point failed in Normal. Normal Indication Voltage at Loc is low/failed/detection break.",
                    "alert_type": AlertType.FAILURE
                })
            elif "VPT110DCLOCR" in code:
                alerts.append({
                    "cause_code": "PT_R_IND_VOLT_FAIL_AT_LOC",
                    "cause_detail": "Point failed in Reverse. Reverse Indication Voltage at Loc is low/failed/detection break.",
                    "alert_type": AlertType.FAILURE
                })
            elif "IPTN" in code:
                alerts.append({
                    "cause_code": "PT_N_VOLT_CURR_FAIL",
                    "cause_detail": "Point failed in Normal. Voltage or Current for normal operation in Loc failed.",
                    "alert_type": AlertType.FAILURE
                })
            elif "IPTR" in code:
                alerts.append({
                    "cause_code": "PT_R_VOLT_CURR_FAIL",
                    "cause_detail": "Point failed in Reverse. Voltage or Current for reverse operation in Loc failed.",
                    "alert_type": AlertType.FAILURE
                })

        # Check obstruction logic (spec: obstruction declared when operation
        # time exceeds max safe, ≈ WJR timer − 1.5 s, default 8 s)
        if code in ("TPTN", "TPTR") and param_config.max_safe is not None:
            if value > param_config.max_safe:
                alerts.append({
                    "cause_code": "PT_N_OBS" if code == "TPTN" else "PT_R_OBS",
                    "cause_detail": "Point failed. Normal/Reverse operation time high. Point in Obstruction.",
                    "alert_type": AlertType.FAILURE
                })

        return alerts
