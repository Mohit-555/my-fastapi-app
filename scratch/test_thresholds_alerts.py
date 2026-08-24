import sys
from unittest.mock import MagicMock
from app.services.parameter_config_service import param_config_service
from app.services.logics.track_circuit import TrackCircuitLogics
from app.services.logics.ips import IPSLogics
from app.services.logics.point_machine import PointMachineLogics
from app.services.logics.signal import SignalLogics
from app.models.models import Telemetry

def test_parameter_configs():
    print("Verifying parameter config registrations...")
    # IPS
    ips_config = param_config_service.get_parameter_config("50012000") # IPS 110 DC
    assert ips_config is not None, "IPS 110 DC config not found"
    assert ips_config.min_safe == 99.0, f"Expected min_safe=99.0, got {ips_config.min_safe}"
    assert ips_config.max_safe == 121.0, f"Expected max_safe=121.0, got {ips_config.max_safe}"
    assert ips_config.min_fail == 88.0, f"Expected min_fail=88.0, got {ips_config.min_fail}"
    assert ips_config.max_fail == 132.0, f"Expected max_fail=132.0, got {ips_config.max_fail}"
    
    ips_24_config = param_config_service.get_parameter_config("50012040") # IPS DC R INT
    assert ips_24_config is not None, "IPS DC R INT config not found"
    assert ips_24_config.min_safe == 21.6, f"Expected min_safe=21.6, got {ips_24_config.min_safe}"
    
    ips_12_config = param_config_service.get_parameter_config("50012068") # IPS DC DATALOG
    assert ips_12_config is not None, "IPS DC DATALOG config not found"
    assert ips_12_config.min_safe == 10.8, f"Expected min_safe=10.8, got {ips_12_config.min_safe}"

    # Main Signal Aspect Voltages
    sig_config = param_config_service.get_parameter_config("10013030") # VSIG DG
    assert sig_config is not None, "VSIG DG config not found"
    assert sig_config.min_safe == 90.0, f"Expected min_safe=90.0, got {sig_config.min_safe}"
    assert sig_config.min_fail == 85.0, f"Expected min_fail=85.0, got {sig_config.min_fail}"

    # Point Machine TPT N
    pm_time_config = param_config_service.get_parameter_config("00019060") # TPT N
    assert pm_time_config is not None, "TPT N config not found"
    assert pm_time_config.max_safe == 5.0, f"Expected max_safe=5.0, got {pm_time_config.max_safe}"
    assert pm_time_config.max_fail == 8.0, f"Expected max_fail=8.0, got {pm_time_config.max_fail}"

    # Track Circuit VTC TR
    tc_tr_config = param_config_service.get_parameter_config("20012042") # VTC TR
    assert tc_tr_config is not None, "VTC TR config not found"
    assert tc_tr_config.min_safe == 2.1, f"Expected min_safe=2.1, got {tc_tr_config.min_safe}"
    assert tc_tr_config.max_safe == 4.2, f"Expected max_safe=4.2, got {tc_tr_config.max_safe}"
    assert tc_tr_config.min_fail == 1.4, f"Expected min_fail=1.4, got {tc_tr_config.min_fail}"

    print("Parameter configs look PERFECT!")

def test_track_circuit_logics():
    print("Verifying Track Circuit logic fixes...")
    # Mock DB session
    db_mock = MagicMock()
    
    # We want average of VTC TR to be 3.0V
    recent_telemetry = [
        Telemetry(prv=3.0, prt="2026-08-24T12:00:00Z"),
        Telemetry(prv=3.0, prt="2026-08-24T12:05:00Z"),
    ]
    db_mock.query().filter().order_by().limit().all.return_value = recent_telemetry
    
    # Test over-energization: value = 4.8V.
    # threshold_high = max(avg_value * 1.2, max_safe (4.2)) = max(3.6, 4.2) = 4.2V
    # value 4.8 > 4.2, so it should trigger TC_TR_OVER_ENERIZATION.
    alerts = TrackCircuitLogics.check_predictive_alerts(
        gateway_id=1, stngw_id="ST1", para_id="20012042", value=4.8, timestamp="now", asset=None, db=db_mock
    )
    print("VTC TR high voltage alerts triggered:", alerts)
    assert len(alerts) == 1, f"Expected 1 alert, got {len(alerts)}"
    assert alerts[0]["cause_code"] == "TC_TR_OVER_ENERIZATION"

    # Test under-energization (low): value = 1.9V.
    # threshold_low = min(avg_value * 0.8, min_safe (2.1)) = min(2.4, 2.1) = 2.1V
    # value 1.9 < 2.1, so it should trigger TC_TR_VOLT_LOW.
    alerts_low = TrackCircuitLogics.check_predictive_alerts(
        gateway_id=1, stngw_id="ST1", para_id="20012042", value=1.9, timestamp="now", asset=None, db=db_mock
    )
    print("VTC TR low voltage alerts triggered:", alerts_low)
    assert len(alerts_low) == 1, f"Expected 1 alert, got {len(alerts_low)}"
    assert alerts_low[0]["cause_code"] == "TC_TR_VOLT_LOW"
    
    print("Track Circuit logics look PERFECT!")

def test_ips_logics():
    print("Verifying IPS logic fixes...")
    db_mock = MagicMock()
    recent_telemetry = [Telemetry(prv=110.0, prt="now"), Telemetry(prv=110.0, prt="now")]
    db_mock.query().filter().order_by().limit().all.return_value = recent_telemetry
    
    # Test low voltage check
    # avg_value = 110.0. LD = 90%. min_safe = 99.0.
    # threshold = min(110.0 * 0.9 (99.0), 99.0) = 99.0V
    # value = 95.0. 95.0 < 99.0, should trigger alert.
    alerts = IPSLogics.check_predictive_alerts(
        gateway_id=1, stngw_id="ST1", para_id="50012000", value=95.0, timestamp="now", asset=None, db=db_mock
    )
    print("IPS low voltage alerts triggered:", alerts)
    assert len(alerts) == 1, f"Expected 1 alert, got {len(alerts)}"
    assert alerts[0]["cause_code"] == "IPS_110_DC_VOLT_LOW"
    
    print("IPS logics look PERFECT!")

def test_point_machine_logics():
    print("Verifying Point Machine logics...")
    # Test obstruction alert (failure)
    # TPT N has max_safe = 5.0. value = 6.0 should trigger PT_N_OBS.
    alerts = PointMachineLogics.check_failure_alerts(
        gateway_id=1, stngw_id="ST1", para_id="00019060", value=6.0, timestamp="now", asset=None, db=None
    )
    print("Point Machine obstruction failure alerts triggered:", alerts)
    assert len(alerts) == 1, f"Expected 1 alert, got {len(alerts)}"
    assert alerts[0]["cause_code"] == "PT_N_OBS"

    print("Point Machine logics look PERFECT!")

def test_none_thresholds_safety():
    print("Verifying None-threshold handling and logging...")
    db_mock = MagicMock()
    recent_telemetry = [Telemetry(prv=100.0, prt="now")]
    db_mock.query().filter().order_by().limit().all.return_value = recent_telemetry

    # Mock an AssetParameter with min_safe/max_safe = None
    class MockParamConfig:
        def __init__(self, code, min_safe=None, max_safe=None):
            self.parameter_representation_code = code
            self.min_safe = min_safe
            self.max_safe = max_safe

    # 1. IPS with None min_safe
    from unittest.mock import patch
    with patch('app.services.parameter_config_service.param_config_service.get_parameter_config') as mock_get:
        mock_get.return_value = MockParamConfig("VIPS 110 DC", min_safe=None)
        alerts = IPSLogics.check_predictive_alerts(
            gateway_id=1, stngw_id="ST1", para_id="50012000", value=95.0, timestamp="now", asset=None, db=db_mock
        )
        assert len(alerts) == 0, f"Expected 0 alerts when min_safe is None, got {len(alerts)}"

    # 2. Point Machine with None min_safe
    with patch('app.services.parameter_config_service.param_config_service.get_parameter_config') as mock_get:
        mock_get.return_value = MockParamConfig("VPT 110 DC LOC N", min_safe=None)
        alerts = PointMachineLogics.check_predictive_alerts(
            gateway_id=1, stngw_id="ST1", para_id="00019010", value=95.0, timestamp="now", asset=None, db=db_mock
        )
        assert len(alerts) == 0, f"Expected 0 alerts when min_safe is None, got {len(alerts)}"

    # 3. Track Circuit VTC TR with None min_safe / max_safe
    with patch('app.services.parameter_config_service.param_config_service.get_parameter_config') as mock_get:
        mock_get.return_value = MockParamConfig("VTC TR", min_safe=None, max_safe=None)
        alerts = TrackCircuitLogics.check_predictive_alerts(
            gateway_id=1, stngw_id="ST1", para_id="20012042", value=95.0, timestamp="now", asset=None, db=db_mock
        )
        assert len(alerts) == 0, f"Expected 0 alerts when thresholds are None, got {len(alerts)}"

    print("None-threshold safety checks passed cleanly without throwing NameError!")

def test_signal_unknown_aspect_logics():
    print("Verifying Signal unknown aspect fallback logic...")
    from unittest.mock import patch, MagicMock
    db_mock = MagicMock()

    class MockParamConfig:
        def __init__(self, code, min_safe=None, max_safe=None, min_fail=None, max_fail=None):
            self.parameter_representation_code = code
            self.min_safe = min_safe
            self.max_safe = max_safe
            self.min_fail = min_fail
            self.max_fail = max_fail

    # Test unknown aspect predictive alert: VSIG X
    with patch('app.services.parameter_config_service.param_config_service.get_parameter_config') as mock_get:
        mock_get.return_value = MockParamConfig("VSIG X", min_safe=90.0)
        alerts = SignalLogics.check_predictive_alerts(
            gateway_id=1, stngw_id="ST1", para_id="10013030", value=85.0, timestamp="now", asset=None, db=db_mock
        )
        print("Signal unknown aspect predictive alerts:", alerts)
        assert len(alerts) == 1
        assert alerts[0]["cause_code"] == "SIG_UNKNOWN_VOLT_CURR_LOW"

    # Test unknown aspect failure alert: VSIG X
    with patch('app.services.parameter_config_service.param_config_service.get_parameter_config') as mock_get:
        mock_get.return_value = MockParamConfig("VSIG X", min_fail=85.0)
        alerts = SignalLogics.check_failure_alerts(
            gateway_id=1, stngw_id="ST1", para_id="10013030", value=80.0, timestamp="now", asset=None, db=db_mock
        )
        print("Signal unknown aspect failure alerts:", alerts)
        assert len(alerts) == 1
        assert alerts[0]["cause_code"] == "SIG_UNKNOWN_VOLT_CURR_FAIL"

    # Test unknown Shunt aspect failure alert: SHSIG UNKNOWN
    with patch('app.services.parameter_config_service.param_config_service.get_parameter_config') as mock_get:
        mock_get.return_value = MockParamConfig("SHSIG UNKNOWN", min_fail=85.0)
        alerts = SignalLogics.check_failure_alerts(
            gateway_id=1, stngw_id="ST1", para_id="10013030", value=80.0, timestamp="now", asset=None, db=db_mock
        )
        print("Shunt unknown aspect failure alerts:", alerts)
        assert len(alerts) == 1
        assert alerts[0]["cause_code"] == "SHSIG_UNKNOWN_VOLT_CURR_FAIL"

    print("Signal unknown aspect fallback logic works PERFECTLY!")

def test_ips_current_and_resolution_logics():
    print("Verifying IPS current and alert deduplication resolution logic...")
    from unittest.mock import patch, MagicMock
    from app.services.alert_engine import AlertEngine, AlertType
    from app.models.models import AlertEvent
    
    db_mock = MagicMock()
    
    # 1. Test battery over-current failure (value > max_fail)
    class MockParamConfig:
        def __init__(self, code, min_fail=None, max_fail=None):
            self.parameter_representation_code = code
            self.min_fail = min_fail
            self.max_fail = max_fail

    with patch('app.services.parameter_config_service.param_config_service.get_parameter_config') as mock_get:
        mock_get.return_value = MockParamConfig("IIPS BATT CHAR 110 DC", min_fail=5.0, max_fail=20.0)
        alerts = IPSLogics.check_failure_alerts(
            gateway_id=1, stngw_id="ST1", para_id="50010001", value=25.0, timestamp="now", asset=None, db=db_mock
        )
        print("IPS Battery Charging over-current failure alerts:", alerts)
        assert len(alerts) == 1
        assert alerts[0]["cause_code"] == "IPS_BATT_CHAR_CURR_OVER"

    # 2. Test AlertEngine cross-type resolution logic
    engine = AlertEngine()
    
    # Track an active predictive alert in engine
    pred_alert_mock = MagicMock(spec=AlertEvent)
    pred_alert_mock.id = 123
    pred_alert_mock.alert_status = "Active"
    
    # Key formatting: {asset_number_code}:{cause_code}:{alert_type.value}
    pred_key = "PT-101:PT_N_VOLT_CURR_LOW:Predictive"
    engine.active_alerts[pred_key] = {
        "alert_id": pred_alert_mock.id,
        "timestamp": "now"
    }
    
    # Mock database query for AlertEvent update
    db_mock.query().filter().first.return_value = pred_alert_mock
    
    # Trigger a failure alert check (which should check if predictive is active)
    # Failure cause code is PT_N_VOLT_CURR_FAIL. Since this is a failure alert, 
    # should_generate_alert will look up the mapped predictive code: PT_N_VOLT_CURR_LOW.
    # We call should_generate_alert with AlertType.FAILURE
    result = engine._should_generate_alert(
        asset_number_code="PT-101",
        cause_code="PT_N_VOLT_CURR_FAIL",
        alert_type=AlertType.FAILURE,
        db=db_mock
    )
    
    assert result is True, "Should allow generating the Failure alert"
    assert pred_key not in engine.active_alerts, "Predictive alert should be removed from active alerts"
    assert pred_key in engine.alert_history, "Predictive alert should be moved to alert history"
    assert pred_alert_mock.alert_status == "Cleared", "Predictive alert status in DB should be marked Cleared"
    assert "Escalated to Failure" in pred_alert_mock.remark, "Predictive alert remark should state Escalated to Failure"
    
    print("IPS current and alert deduplication resolution logic works PERFECTLY!")

if __name__ == "__main__":
    test_parameter_configs()
    test_track_circuit_logics()
    test_ips_logics()
    test_point_machine_logics()
    test_none_thresholds_safety()
    test_signal_unknown_aspect_logics()
    test_ips_current_and_resolution_logics()
    print("ALL VERIFICATION TESTS PASSED SUCCESSFULLY!")
