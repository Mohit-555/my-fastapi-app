import pytest
from datetime import datetime, UTC
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from app.main import app
from app.database import Base, get_db
from app.auth_utils import get_current_user
from app.models.models import AlertEvent, Station, Division, Zone, User, Role, AssetTypeMaster, AlertCauseMaster

TEST_DB_URL = "sqlite:///:memory:"
engine = create_engine(
    TEST_DB_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(scope="module", autouse=True)
def setup_test_data():
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()

    # 1. Role & User
    role = Role(id=1, name="Admin", display_name="Administrator", level=0, is_active=True)
    db.add(role)
    db.commit()

    user = User(
        id=1,
        full_name="HQ Admin",
        employee_id="hq_admin",
        designation="Admin",
        mobile_number="9999999999",
        email="admin@rdpms.in",
        hashed_password="hashed_dummy_password",
        role_id=role.id,
        is_active=True,
    )
    db.add(user)

    # 2. Hierarchy
    zone = Zone(id=1, zone_name="Northern Railway", zone_code="NR", zone_id_hex="01", status="Active")
    db.add(zone)
    db.commit()

    division = Division(id=1, division_name="Delhi", division_code="DLI", division_id_hex="01", zone_id=zone.id, status="Active")
    db.add(division)
    db.commit()

    station = Station(id=1, station_name="New Delhi", station_code="NDLS", station_id_hex="01", division_id=division.id, status="Active")
    db.add(station)

    # 3. Asset Type Master & Cause Master
    atm = AssetTypeMaster(id=1, asset_type_id="00", asset_type_code="PM", asset_type_name="Point Machine", is_equipment_room=False)
    db.add(atm)
    cause = AlertCauseMaster(cause_code="PT_OBS", cause_detail="Point Machine Obstruction", asset_type_id="00", alert_category="FAILURE")
    db.add(cause)
    db.commit()

    # Override dependencies
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user

    yield db

    db.close()
    Base.metadata.drop_all(bind=engine)
    app.dependency_overrides.clear()


@pytest.fixture
def client():
    return TestClient(app)


def test_live_alert_retained_with_cleared_status(client, setup_test_data):
    db = setup_test_data

    # Create an alert event with status "Active" and no feedback
    alert = AlertEvent(
        station_id=1,
        alert_type="Failure",
        asset_type_hex="00",
        asset_no="101T",
        cause="PT_OBS",
        alert_status="Active",
        feedback=None,
        acknowledged=False,
        alert_time=datetime.now(UTC),
    )
    db.add(alert)
    db.commit()
    db.refresh(alert)
    alert_id = alert.id

    # 1. Live view returns it as Active
    res = client.get("/alerts/live")
    assert res.status_code == 200
    data = res.json()["data"]
    found = next((a for a in data["alerts"] if a["id"] == alert_id), None)
    assert found is not None
    assert found["alert_status"] == "Active"

    # 2. Submit operator feedback
    fb_res = client.post(f"/alerts/{alert_id}/feedback", json={"feedback": "T", "remarks": "Obstruction removed"})
    assert fb_res.status_code == 200
    assert fb_res.json()["data"]["alert_status"] == "Cleared"
    assert fb_res.json()["data"]["feedback"] == "T"

    # 3. Alert is RETAINED in live view instead of removed, with 'Cleared' status
    res2 = client.get("/alerts/live")
    assert res2.status_code == 200
    data2 = res2.json()["data"]
    found2 = next((a for a in data2["alerts"] if a["id"] == alert_id), None)
    assert found2 is not None, "Alert must be retained in live view after operator feedback"
    assert found2["alert_status"] == "Cleared", "Alert status must be 'Cleared' in live view"
    assert found2["feedback"] == "T"


def test_history_alert_marked_pending_when_awaiting_feedback(client, setup_test_data):
    db = setup_test_data

    # Create an alert awaiting feedback
    alert = AlertEvent(
        station_id=1,
        alert_type="Failure",
        asset_type_hex="00",
        asset_no="102T",
        cause="PT_OBS",
        alert_status="Active",
        feedback=None,
        acknowledged=False,
        alert_time=datetime.now(UTC),
    )
    db.add(alert)
    db.commit()
    db.refresh(alert)
    alert_id = alert.id

    # Query history
    res = client.get(f"/alerts/history?asset_no=102T")
    assert res.status_code == 200
    rows = res.json()["data"]["rows"]
    found = next((r for r in rows if r["id"] == alert_id), None)
    assert found is not None
    assert found["alert_status"] == "Pending", "Alert awaiting feedback must be marked as 'Pending' in history"

    # Filter by alert_status=Pending
    res_pending = client.get("/alerts/history?alert_status=Pending")
    assert res_pending.status_code == 200
    assert any(r["id"] == alert_id for r in res_pending.json()["data"]["rows"])

    # Now submit feedback
    fb_res = client.post(f"/alerts/{alert_id}/feedback", json={"feedback": "PT", "remarks": "Partially verified"})
    assert fb_res.status_code == 200

    # Query history again: status should now be 'Cleared'
    res_after = client.get(f"/alerts/history?asset_no=102T")
    assert res_after.status_code == 200
    found_after = next((r for r in res_after.json()["data"]["rows"] if r["id"] == alert_id), None)
    assert found_after is not None
    assert found_after["alert_status"] == "Cleared", "Alert with feedback must have status 'Cleared' in history"

    # CSV download includes Cleared
    csv_res = client.get("/alerts/history/download?asset_no=102T")
    assert csv_res.status_code == 200
    assert "Cleared" in csv_res.text