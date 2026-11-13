import pytest
from datetime import datetime, UTC
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from app.main import app
from app.database import Base, get_db
from app.auth_utils import get_current_user
from app.models.models import (
    Station, Division, Zone, Asset, Gateway, AssetTypeMaster, Telemetry, User, Role, RTU, AlertEvent
)

TEST_DB_URL = "sqlite:///:memory:"
engine = create_engine(
    TEST_DB_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db
client = TestClient(app)


@pytest.fixture(scope="module", autouse=True)
def setup_test_data():
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()

    # Role & User
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
        hashed_password="pw",
        role_id=role.id,
        is_active=True,
    )
    db.add(user)
    db.commit()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = lambda: user

    # Hierarchy: Zone -> Division -> Stations
    z1 = Zone(id=1, zone_code="NR", zone_name="Northern Railway", zone_id_hex="01", status="Active")
    z2 = Zone(id=2, zone_code="CR", zone_name="Central Railway", zone_id_hex="02", status="Active")
    db.add_all([z1, z2])
    db.commit()

    d1 = Division(id=1, zone_id=1, division_code="LKO", division_name="Lucknow", division_id_hex="01", status="Active")
    d2 = Division(id=2, zone_id=2, division_code="BSL", division_name="Bhusaval", division_id_hex="02", status="Active")
    db.add_all([d1, d2])
    db.commit()

    s1 = Station(id=10, division_id=1, station_code="LKO", station_name="Lucknow Charbagh", station_id_hex="01", status="Active")
    s2 = Station(id=20, division_id=2, station_code="BSLS", station_name="Bhusaval Station", station_id_hex="02", status="Active")
    db.add_all([s1, s2])
    db.commit()

    # AssetTypeMaster
    atm = AssetTypeMaster(
        id=1,
        asset_type_id="01",
        asset_type_code="POINT_MACHINE",
        asset_type_name="Point Machine",
    )
    db.add(atm)
    db.commit()

    # RTUs
    # RTU 1: LKO station, has coordinates, healthy
    rtu1 = RTU(
        id=1,
        station_id=10,
        rtu_name="RTU-LKO-01",
        rtu_code="RTU-01",
        location="Relay Room North",
        description="Main Line RTU",
        latitude=26.8393,
        longitude=80.9231,
        is_active=True,
    )
    # RTU 2: BSL station, has coordinates, will have Failure alert
    rtu2 = RTU(
        id=2,
        station_id=20,
        rtu_name="RTU-BSL-01",
        rtu_code="RTU-02",
        location="Signal Equipment Room",
        description="Yard RTU",
        latitude=21.0455,
        longitude=75.8011,
        is_active=True,
    )
    # RTU 3: LKO station, NO coordinates (should be excluded from map pins)
    rtu3 = RTU(
        id=3,
        station_id=10,
        rtu_name="RTU-LKO-NO-COORDS",
        rtu_code="RTU-03",
        location="Substation",
        latitude=None,
        longitude=None,
        is_active=True,
    )
    db.add_all([rtu1, rtu2, rtu3])
    db.commit()

    # Gateways
    gw1 = Gateway(
        id=101,
        station_id=10,
        rtu_id=1,
        stngw_id="01010101",
        imei="imei_gw1",
    )
    gw2 = Gateway(
        id=102,
        station_id=20,
        rtu_id=2,
        stngw_id="02020201",
        imei="imei_gw2",
    )
    db.add_all([gw1, gw2])
    db.commit()

    # Assets
    a1 = Asset(
        id=1001,
        smms_asset_code="SMMS-PT-101",
        smms_asset_name="Point Machine 101",
        station_id=10,
        station_gateway_id="01010101",
        asset_type_hex="01",
        asset_number_id="01",
        asset_number_code="PT-101",
        is_active=True,
    )
    a2 = Asset(
        id=1002,
        smms_asset_code="SMMS-PT-201",
        smms_asset_name="Point Machine 201",
        station_id=20,
        station_gateway_id="02020201",
        asset_type_hex="01",
        asset_number_id="01",
        asset_number_code="PT-201",
        is_active=True,
    )
    db.add_all([a1, a2])
    db.commit()

    # Active alert for a2 (Failure alert)
    alert = AlertEvent(
        id=1,
        station_id=20,
        asset_id=1002,
        asset_no="PT-201",
        asset_type_hex="01",
        alert_type="Failure",
        alert_status="Active",
        cause="Motor Current Exceeded",
        alert_time=datetime.now(UTC),
    )
    db.add(alert)
    db.commit()

    yield

    db.close()


def test_get_dashboard_map_pins_all():
    """Test GET /api/dashboard/map-pins returns RTUs with coordinates and correct status."""
    res = client.get("/api/dashboard/map-pins")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] is True
    pins = body["data"]

    # Should only return rtu1 and rtu2 (rtu3 has null coordinates)
    assert len(pins) == 2
    rtu_ids = [p["rtu_id"] for p in pins]
    assert 1 in rtu_ids
    assert 2 in rtu_ids
    assert 3 not in rtu_ids

    # RTU 1 should be Healthy
    p1 = next(p for p in pins if p["rtu_id"] == 1)
    assert p1["status"] == "Healthy"
    assert p1["station_code"] == "LKO"
    assert p1["lat"] == 26.8393
    assert p1["lng"] == 80.9231
    assert p1["active_alerts_count"] == 0

    # RTU 2 should be Failure
    p2 = next(p for p in pins if p["rtu_id"] == 2)
    assert p2["status"] == "Failure"
    assert p2["station_code"] == "BSLS"
    assert p2["lat"] == 21.0455
    assert p2["lng"] == 75.8011
    assert p2["active_alerts_count"] == 1
    assert p2["failure_alerts_count"] == 1


def test_get_dashboard_map_pins_no_307():
    """Verify trailing slash /map-pins/ succeeds with 200 and no 307 redirect."""
    res = client.get("/api/dashboard/map-pins/", follow_redirects=False)
    assert res.status_code == 200
    assert res.json()["status"] is True


def test_get_dashboard_map_pins_filter_by_station():
    """Filter map pins by station_id."""
    res = client.get("/api/dashboard/map-pins?station_id=10")
    assert res.status_code == 200
    pins = res.json()["data"]
    assert len(pins) == 1
    assert pins[0]["rtu_id"] == 1
    assert pins[0]["station_id"] == 10


def test_get_dashboard_map_pins_filter_by_division():
    """Filter map pins by division_id."""
    res = client.get("/api/dashboard/map-pins?division_id=2")
    assert res.status_code == 200
    pins = res.json()["data"]
    assert len(pins) == 1
    assert pins[0]["rtu_id"] == 2
    assert pins[0]["division_code"] == "BSL"


def test_telemetry_live_filter_by_rtu_id():
    """Test that /telemetry/live?rtu_id=1 returns assets for RTU 1 and not RTU 2."""
    res = client.get("/telemetry/live?rtu_id=1")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] is True
    data = body["data"]

    # When rtu_id=1 is queried, it should only find assets linked to gateway gw1 (PT-101)
    if "rows" in data:
        rows = data["rows"]
        assert len(rows) > 0
        asset_nos = {r.get("asset_no") for r in rows if r.get("asset_no")}
        assert "PT-101" in asset_nos
        assert "PT-201" not in asset_nos


def test_telemetry_live_filter_by_rtu_2():
    """Test that /telemetry/live?rtu_id=2 returns PT-201 only."""
    res = client.get("/telemetry/live?rtu_id=2")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] is True
    data = body["data"]

    if "rows" in data:
        rows = data["rows"]
        assert len(rows) > 0
        asset_nos = {r.get("asset_no") for r in rows if r.get("asset_no")}
        assert "PT-201" in asset_nos
        assert "PT-101" not in asset_nos
