import logging
import re
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from app.models.models import Telemetry, Asset
from app.services.alert_engine import AlertType
from app.services.parameter_config_service import param_config_service
from app.services.timestamp_utils import parse_prt

logger = logging.getLogger(__name__)

# Matches the multi-unit IPS output families. Annexure C §2.1 note: the
# SIG/TR/SMR logics are "to be done for all similar modules", i.e. every
# unit number must raise alerts, not just unit 1.
_MULTI_UNIT_RE = re.compile(r"^(?:V|I)IPS\s+(SIG|TR|SMR)-(\d+)\b")


class IPSLogics:
    """Implementation of IPS logics from Annexure C §2.1"""

    LD = 90  # Lower deviation for IPS predictive

    # Exact-key fallbacks for single-instance parameters.
    _PREDICTIVE_MAP = {
        "VIPS IIP": "IPS_IIP_VOLT_LOW",
        "VIPS 110 DC": "IPS_110_DC_VOLT_LOW",
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
        "IIPS BATT CHAR 110 DC": "IPS_BATT_CHAR_CURR_LOW",
    }
    _FAILURE_MAP = {
        "VIPS IIP": "IPS_IIP_VOLT_FAIL",
        "VIPS 110 DC": "IPS_110_DC_VOLT_FAIL",
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
    }

    @staticmethod
    def _resolve_cause(code: str, failure: bool) -> Optional[Tuple[str, str]]:
        """Resolve an IPS parameter_representation_code to (cause_code, label).

        Multi-unit families (SIG/TR/SMR) generalise per spec "for all similar
        modules". Unit-1 SIG/TR keep their legacy un-numbered cause codes so
        existing alert history stays valid; SMR was always numbered.
        """
        m = _MULTI_UNIT_RE.match(code)
        if m:
            family, unit = m.group(1), m.group(2)
            suffix = "_FAIL" if failure else "_LOW"
            if family == "SMR":
                return f"IPS_SMR_{unit}_VOLT{suffix}", f"SMR-{unit} voltage"
            legacy = "" if unit == "1" else f"_{unit}"
            return (
                f"IPS_110_AC_{family}{legacy}_VOLT{suffix}",
                f"{family}-{unit} 110 AC O/P voltage",
            )

        exact_map = IPSLogics._FAILURE_MAP if failure else IPSLogics._PREDICTIVE_MAP
        for key, cause_code in exact_map.items():
            if key in code:
                return cause_code, key
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
        """Check all predictive logics for IPS (Section 2.1(a))"""
        alerts = []

        param_config = param_config_service.get_effective_config(db, para_id, asset.station_id)

        if not param_config:
            return alerts

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

        values = [t.prv for t in recent_data if t.prv is not None]
        if not values:
            return alerts
        avg_value = sum(values) / len(values)

        # Check all IPS voltage outputs
        if "VIPS" in param_config.parameter_representation_code or "IIPS" in param_config.parameter_representation_code:
            if param_config.min_safe is None:
                logger.debug("IPS: min_safe not configured, skipping alert")
                return alerts
            # Spec semantics: "< LD % of avg value OR Min safe" — either
            # condition alone must raise the alert.
            threshold = max(avg_value * (IPSLogics.LD / 100), param_config.min_safe)
            if value < threshold:
                resolved = IPSLogics._resolve_cause(
                    param_config.parameter_representation_code, failure=False
                )
                if resolved:
                    cause_code, label = resolved
                    alerts.append({
                        "cause_code": cause_code,
                        "cause_detail": f"IPS predictive Alert: {label} low.",
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
        """Check all failure logics for IPS (Section 2.1(b))"""
        alerts = []

        param_config = param_config_service.get_effective_config(db, para_id, asset.station_id)

        if not param_config:
            return alerts

        is_under = param_config.min_fail is not None and value < param_config.min_fail
        is_over = param_config.max_fail is not None and value > param_config.max_fail

        if is_under or is_over:
            # Check for battery charging current failure (both under and over)
            if "IIPS BATT CHAR" in param_config.parameter_representation_code:
                if is_under:
                    alerts.append({
                        "cause_code": "IPS_BATT_CHAR_CURR_FAIL",
                        "cause_detail": "IPS failed. Battery Charging current low.",
                        "alert_type": AlertType.FAILURE
                    })
                elif is_over:
                    alerts.append({
                        "cause_code": "IPS_BATT_CHAR_CURR_OVER",
                        "cause_detail": "IPS failed. Battery Charging current excessively high.",
                        "alert_type": AlertType.FAILURE
                    })
            else:
                resolved = IPSLogics._resolve_cause(
                    param_config.parameter_representation_code, failure=True
                )
                if resolved:
                    cause_code, label = resolved
                    cond_str = "low" if is_under else "high"
                    alerts.append({
                        "cause_code": cause_code,
                        "cause_detail": f"IPS failed. {label} failed ({cond_str}).",
                        "alert_type": AlertType.FAILURE
                    })

        return alerts
