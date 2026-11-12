import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from app.main import app
from app.database import Base, get_db
from app.auth_utils import get_current_user
from app.models.models import (
    Asset,
    AssetTypeMaster,
    Division,
    Gateway,
    Role,
    Station,
    User,
    Zone,
)

TEST_DB_URL = "sqlite:///:memory:"
engine = create_engine(
    TEST_DB_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)


@event.listens_for(engine, "connect")
def _enable_sqlite_fk(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(scope="module")
def cascade_db():
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()

    role = Role(id=1, name="HQ_ADMIN", display_name="HQ Administrator", level=1, is_active=True)
    db.add(role)
    db.commit()

    user = User(
        id=1,
        full_name="HQ Admin",
        employee_id="hq_admin",
        designation="Director",
        mobile_number="9999999999",
        email="hq@rdpms.in",
        hashed_password="pw",
        role_id=role.id,
        is_active=True,
    )
    db.add(user)

    zone = Zone(id=1, zone_name="Central Railway", zone_code="CR", zone_id_hex="00", status="Active")
    db.add(zone)
    db.commit()

    division = Division(
        id=1,
        division_name="Bhusaval",
        division_code="BSL",
        division_id_hex="00",
        zone_id=zone.id,
        status="Active",
    )
    db.add(division)
    db.commit()

    station = Station(
        id=9,
        station_name="Bhusaval Station",
        station_code="BSLS",
        station_id_hex="00",
        division_id=division.id,
        status="Active",
    )
    db.add(station)

    atm = AssetTypeMaster(
        id=1,
        asset_type_id="00",
        asset_type_code="EOP",
        asset_type_name="Point Machine",
        is_equipment_room=False,
    )
    db.add(atm)

    gw = Gateway(id=45, stngw_id="GW000009", imei="imei_GW000009", station_id=9)
    db.add(gw)
    db.commit()

    asset = Asset(
        id=21,
        smms_asset_code="SMMS-PM-101",
        smms_asset_name="Point Machine 101",
        asset_number_code="PM-101",
        asset_number_id="01",
        asset_type_hex="00",
        station_gateway_id="GW000009",
        station_id=9,
    )
    db.add(asset)
    db.commit()

    def override_get_db():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = lambda: user

    yield db

    db.close()
    Base.metadata.drop_all(bind=engine)
    app.dependency_overrides.clear()


def test_update_gateway_stngw_id_cascades_to_assets(cascade_db):
    """
    Renaming a gateway's stngw_id via PUT /gateway/{stngw_id} must succeed
    and cascade automatically to dependent Asset.station_gateway_id rows.
    """
    client = TestClient(app)
    res = client.put(
        "/gateway/GW000009",
        json={
            "stngw_id": "00000001",
            "imei": "2893479873598",
            "station_id": 9,
        },
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] is True
    assert body["data"]["stngw_id"] == "00000001"
    assert body["data"]["imei"] == "2893479873598"

    cascade_db.expire_all()
    updated_asset = cascade_db.query(Asset).filter(Asset.id == 21).first()
    assert updated_asset is not None
    assert updated_asset.station_gateway_id == "00000001"
