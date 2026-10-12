import pytest
from datetime import datetime, UTC
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from app.main import app
from app.database import Base, get_db
from app.auth_utils import get_current_user
from app.models.models import Station, Division, Zone, Asset, Gateway, AssetTypeMaster, Telemetry, User, Role

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

    # Hierarchy
    zone = Zone(id=1, zone_name="Northern Railway", zone_code="NR", zone_id_hex="01", status="Active")
    db.add(zone)
    db.commit()

    division = Division(id=1, division_name="Delhi", division_code="DLI", division_id_hex="01", zone_id=zone.id, status="Active")
    db.add(division)
    db.commit()

    station = Station(id=1, station_name="New Delhi", station_code="NDLS", station_id_hex="01", division_id=division.id, status="Active")
    db.add(station)
    db.commit()

    # Gateways
    gw = Gateway(id=1, stngw_id="GW01", station_id=station.id)
    db.add(gw)
    db.commit()

    # Asset Types
    atm_pm = AssetTypeMaster(id=1, asset_type_id="00", asset_type_code="PM", asset_type_name="Point Machine", is_equipment_room=False)
    atm_tc = AssetTypeMaster(id=2, asset_type_id="20", asset_type_code="DCT", asset_type_name="DC Track Circuit", is_equipment_room=False)
    atm_sig = AssetTypeMaster(id=3, asset_type_id="10", asset_type_code="LED", asset_type_name="Main Signal", is_equipment_room=False)
    db.add_all([atm_pm, atm_tc, atm_sig])
    db.commit()

    # Assets
    asset1 = Asset(
        id=1,
        smms_asset_code="SMMS-PT-101",
        smms_asset_name="Point Machine 101",
        asset_number_code="PT-101",
        asset_number_id="01",
        asset_type_hex="00",
        station_gateway_id="GW01",
        station_id=station.id,
        location="Location Box 1"
    )
    asset2 = Asset(
        id=2,
        smms_asset_code="SMMS-TC-12",
        smms_asset_name="Track Circuit 12",
        asset_number_code="TC-12",
        asset_number_id="01",
        asset_type_hex="20",
        station_gateway_id="GW01",
        station_id=station.id,
        location="Feed End Box"
    )
    asset3 = Asset(
        id=3,
        smms_asset_code="SMMS-MS-01",
        smms_asset_name="Main Signal 01",
        asset_number_code="MS-01",
        asset_number_id="01",
        asset_type_hex="10",
        station_gateway_id="GW01",
        station_id=station.id,
        location="Signal Location Box"
    )
    db.add_all([asset1, asset2, asset3])
    db.commit()

    # Add sample telemetry
    # PT-101: 00 (type) + 01 (num) + 00 (pt_type) + 30 (repr) -> 00010030
    telem1 = Telemetry(
        gateway_id=gw.id,
        para_id="00010030",
        prv=1.85,
        prt="12:30:45",
        received_at=datetime.now(UTC)
    )
    db.add(telem1)
    db.commit()

    yield db

    db.close()
    Base.metadata.drop_all(bind=engine)
    app.dependency_overrides.clear()


def test_telemetry_live_mode_a_point_machine():
    """
    Mode A: Filter by station and asset_type (without asset_no).
    Must return dynamic parameter rows containing:
    asset_no, parameter_name, parameter_code, pr_location, value, unit, status.
    """
    response = client.get("/telemetry/live?station_id=1&asset_type=Point Machine")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] is True
    res_data = data["data"]
    assert res_data["Asset_Type"] == "Point Machine"
    assert "rows" in res_data
    assert len(res_data["rows"]) > 0

    first_row = res_data["rows"][0]
    # Required columns in Mode A
    assert "asset_no" in first_row
    assert "parameter_name" in first_row
    assert "parameter_code" in first_row
    assert "pr_location" in first_row
    assert "value" in first_row
    assert "unit" in first_row
    assert "status" in first_row

    # Check for actual RDSO parameter codes
    codes = [r["parameter_code"] for r in res_data["rows"]]
    assert "IPT N" in codes or "IPT R" in codes
    assert any("VPT" in c for c in codes)


def test_telemetry_live_mode_b_specific_asset():
    """
    Mode B: Filter with specific asset_no.
    Must return rows containing timestamp for each row.
    """
    response = client.get("/telemetry/live?station_id=1&asset_type=Point Machine&asset_no=PT-101")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] is True
    res_data = data["data"]
    assert res_data["Asset_No"] == "PT-101"
    assert "rows" in res_data
    assert len(res_data["rows"]) > 0

    first_row = res_data["rows"][0]
    assert "parameter_name" in first_row
    assert "parameter_code" in first_row
    assert "pr_location" in first_row
    assert "value" in first_row
    assert "unit" in first_row
    assert "status" in first_row
    assert "timestamp" in first_row
    assert first_row["timestamp"] is not None


def test_telemetry_live_track_circuit_parameters():
    """
    Verify Track Circuit returns RDSO parameters.
    """
    response = client.get("/telemetry/live?station_id=1&asset_type=DC Track Circuit")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] is True
    codes = [r["parameter_code"] for r in data["data"]["rows"]]
    assert any("VTC" in c for c in codes)
    assert any("ITC" in c for c in codes)


def test_telemetry_live_main_signal_parameters():
    """
    Verify Main Signal returns RDSO parameters.
    """
    response = client.get("/telemetry/live?station_id=1&asset_type=Main Signal")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] is True
    codes = [r["parameter_code"] for r in data["data"]["rows"]]
    assert any("VSIG" in c for c in codes)
