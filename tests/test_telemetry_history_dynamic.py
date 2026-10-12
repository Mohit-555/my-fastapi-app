import pytest
from datetime import datetime, UTC, timedelta
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
    atm1 = AssetTypeMaster(id=1, asset_type_id="00", asset_type_code="PM", asset_type_name="Point Machine", is_equipment_room=False)
    atm2 = AssetTypeMaster(id=2, asset_type_id="20", asset_type_code="TC", asset_type_name="DC Track Circuit", is_equipment_room=False)
    atm3 = AssetTypeMaster(id=3, asset_type_id="10", asset_type_code="MS", asset_type_name="Main Signal", is_equipment_room=False)
    db.add_all([atm1, atm2, atm3])
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
        location="Platform 1 North End"
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
    db.add_all([asset1, asset2])
    db.commit()

    now = datetime.now(UTC)
    # Add sample telemetry:
    # Point Machine current normal: 00 (type) + 01 (num) + 00 (current) + 0C (repr) -> 0001000C
    t1 = Telemetry(
        gateway_id=gw.id,
        para_id="0001000C",
        prv=2.45,
        prt="10:00:00",
        received_at=now - timedelta(minutes=10)
    )
    # Track Circuit TFC output voltage: 20 (type) + 01 (num) + 20 (volt) + 21 (repr) -> 20012021
    t2 = Telemetry(
        gateway_id=gw.id,
        para_id="20012021",
        prv=12.4,
        prt="10:05:00",
        received_at=now - timedelta(minutes=5)
    )
    db.add_all([t1, t2])
    db.commit()

    yield db

    db.close()
    Base.metadata.drop_all(bind=engine)
    app.dependency_overrides.clear()


@pytest.fixture
def client():
    return TestClient(app)


def test_telemetry_history_track_circuit_dynamic_columns(client, setup_test_data):
    """Verify Track Circuit history returns dynamic RDSO columns and rows."""
    res = client.get("/telemetry/history", params={
        "station_code": "NDLS",
        "asset_type": "DC Track Circuit",
        "asset_no": "TC-12"
    })
    assert res.status_code == 200
    data = res.json()["data"]
    assert data["Asset_Type"] == "DC Track Circuit"
    assert data["Asset_No"] == "TC-12"
    
    # Columns must contain RDSO codes
    col_codes = [c["parameter_code"] for c in data["columns"] if c.get("parameter_code")]
    assert "VTC TFC O/P" in col_codes
    assert "ITC TFC O/P" in col_codes

    # Data row has value for VTC TFC O/P
    assert len(data["rows"]) >= 1
    row = data["rows"][0]
    assert "VTC TFC O/P" in row["values"]
    assert row["values"]["VTC TFC O/P"] == 12.4


def test_telemetry_history_point_machine_dynamic_columns(client, setup_test_data):
    """Verify Point Machine history returns IPT N and legacy aliases."""
    res = client.get("/telemetry/history", params={
        "station_code": "NDLS",
        "asset_type": "Point Machine",
        "asset_no": "PT-101"
    })
    assert res.status_code == 200
    data = res.json()["data"]
    assert data["Asset_Type"] == "Point Machine"
    assert len(data["rows"]) >= 1

    # Check live_data compatibility
    live_rows = data["live_data"]
    assert len(live_rows) >= 1
    assert "IPT_N" in live_rows[0] or "I_avg" in live_rows[0]


def test_telemetry_history_vendor_and_canonical_columns(client, setup_test_data):
    """Verify Telemetry History returns Vendor Name, Zone, Division, Station, and Asset Type."""
    res = client.get("/telemetry/history", params={
        "station_code": "NDLS",
        "asset_type": "DC Track Circuit",
        "asset_no": "TC-12"
    })
    assert res.status_code == 200
    data = res.json()["data"]
    assert data["Vendor"] == "XYZ"
    assert data["Zone"] == "NR"
    assert data["Division"] == "DLI"
    assert data["Asset_Type"] == "DC Track Circuit"
    assert data["Asset_No"] == "TC-12"

    assert len(data["rows"]) >= 1
    row = data["rows"][0]
    assert row["vendor_name"] == "XYZ"
    assert row["zone"] == "NR"
    assert row["division"] == "DLI"
    assert row["asset_type"] == "DC Track Circuit"
    assert row["asset_no"] == "TC-12"

    assert len(data["live_data"]) >= 1
    live_row = data["live_data"][0]
    assert live_row["vendor_name"] == "XYZ"
    assert live_row["zone"] == "NR"
    assert live_row["division"] == "DLI"
    assert live_row["asset_type"] == "DC Track Circuit"
    assert live_row["asset_no"] == "TC-12"


def test_telemetry_history_csv_download(client, setup_test_data):
    """Verify CSV export contains Annexure F §3 canonical headers and vendor info."""
    res = client.get("/telemetry/history/download", params={
        "station_code": "NDLS",
        "asset_type": "DC Track Circuit",
        "asset_no": "TC-12"
    })
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/csv")
    csv_text = res.text
    assert "ZONE,DIVISION,STATION,VENDOR NAME,ASSET TYPE,ASSET NUMBER,DATE & TIME" in csv_text
    assert "VTC TFC O/P" in csv_text
    assert "XYZ" in csv_text


def test_telemetry_summary_aggregations(client, setup_test_data):
    """Verify Telemetry Summary aggregates min, max, avg, and metrics."""
    res = client.get("/telemetry/summary", params={
        "station_code": "NDLS",
        "asset_type": "DC Track Circuit"
    })
    assert res.status_code == 200
    data = res.json()["data"]
    assert "metrics" in data
    assert "rows" in data
    assert data["total"] >= 1

    summary_row = data["rows"][0]
    assert summary_row["station"] == "NDLS"
    assert summary_row["asset_type"] == "DC Track Circuit"
    assert summary_row["parameter_code"] == "VTC TFC O/P"
    assert summary_row["min_value"] == 12.4
    assert summary_row["max_value"] == 12.4
    assert summary_row["avg_value"] == 12.4
    assert summary_row["total_samples"] >= 1
    assert summary_row["status"] in ("Healthy", "Predictive", "Failure")


def test_telemetry_summary_csv_download(client, setup_test_data):
    """Verify Telemetry Summary CSV export."""
    res = client.get("/telemetry/summary/download", params={
        "station_code": "NDLS",
        "asset_type": "DC Track Circuit"
    })
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/csv")
    csv_text = res.text
    assert "SR,ZONE,DIVISION,STATION" in csv_text
    assert "PARAMETER CODE" in csv_text
    assert "VTC TFC O/P" in csv_text


def test_telemetry_history_point_machine_all_rdso_columns(client, setup_test_data):
    """Verify Point Machine history returns exactly the 14 RDSO canonical parameters."""
    res = client.get("/telemetry/history", params={
        "station_code": "NDLS",
        "asset_type": "Point Machine",
        "asset_no": "PT-101"
    })
    assert res.status_code == 200
    data = res.json()["data"]
    col_codes = [c["parameter_code"] for c in data["columns"] if c.get("parameter_code")]

    expected_codes = [
        "IPT N", "IPT R",
        "VPT 110 DC LOC N", "VPT 110 DC LOC R",
        "VPT 24 DC LOC N", "VPT 24 DC LOC R",
        "VPT NWKR", "VPT RWKR",
        "TPT N", "TPT R",
        "NWKR", "RWKR", "NWCR", "RWCR"
    ]
    for code in expected_codes:
        assert code in col_codes, f"Expected {code} in Point Machine columns"

    # Verify legacy artifacts are not catalog columns
    assert "AVG_CUR" not in col_codes
    assert "PEAK_CUR" not in col_codes
    assert "BAT_VOLT" not in col_codes


def test_telemetry_history_csv_header_format_compliance(client, setup_test_data):
    """Verify CSV header strictly adheres to <Name> [<Code>] (<Unit>) and omits unit for status."""
    res = client.get("/telemetry/history/download", params={
        "station_code": "NDLS",
        "asset_type": "Point Machine",
        "asset_no": "PT-101"
    })
    assert res.status_code == 200
    csv_text = res.text
    header_line = csv_text.splitlines()[0]
    
    # Check fixed headers
    assert "ZONE,DIVISION,STATION,VENDOR NAME,ASSET TYPE,ASSET NUMBER,DATE & TIME" in header_line
    # Check analog parameter header format
    assert "Point Machine Current Normal [IPT N] (A)" in header_line
    assert "110V DC Loc Normal [VPT 110 DC LOC N] (V)" in header_line
    assert "Normal Operation Time [TPT N] (s)" in header_line
    # Check digital status parameter header format (no status/empty parens)
    assert "NWKR Digital Status [NWKR]" in header_line
    assert "NWKR Digital Status [NWKR] ()" not in header_line
    assert "NWKR Digital Status [NWKR] (status)" not in header_line


