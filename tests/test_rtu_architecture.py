import os
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.models import Zone, Division, Station, RTU, Gateway, SlaveCard, Asset, AssetParameter, User
from app.routers.rtu import bulk_create_rtus, get_rtu_hierarchy, _build_rtu_response
from app.models.schemas import RTUBulkCreateRequest, AssetMappingAssignRequest, AssetMappingUnassignRequest
from app.routers.channel_assignment import map_asset_parameter, unmap_asset_parameter


@pytest.fixture
def memory_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    yield db
    db.close()


def test_rtu_architecture_workflow(memory_db):
    db = memory_db

    # 1. Setup Hierarchy
    z = Zone(zone_name="Central Railway", zone_code="CR", zone_id_hex="00")
    db.add(z)
    db.flush()

    d = Division(division_name="Bhusaval", division_code="BSL", division_id_hex="00", zone_id=z.id)
    db.add(d)
    db.flush()

    s = Station(station_name="Bhusaval Station", station_code="BSLS", station_id_hex="00", division_id=d.id)
    db.add(s)
    db.flush()

    u = User(employee_id="test_admin", full_name="Admin", designation="SSE", mobile_number="9999999999", hashed_password="xxx", email="admin@test.com")
    db.add(u)
    db.flush()

    # 2. Test Bulk RTU creation
    bulk_req = RTUBulkCreateRequest(station_id=s.id, count=5, prefix="RTU-", location="Relay Room")
    res = bulk_create_rtus(payload=bulk_req, db=db, current_user=u)
    assert res["status"] is True
    assert res["data"]["created_count"] == 5
    assert [r.rtu_name for r in res["data"]["rtus"]] == ["RTU-01", "RTU-02", "RTU-03", "RTU-04", "RTU-05"]

    # 3. Test RTU Coordinates
    rtu1 = db.query(RTU).filter(RTU.rtu_name == "RTU-01").first()
    rtu1.latitude = 21.0456
    rtu1.longitude = 75.7890
    db.commit()
    rtu1_resp = _build_rtu_response(rtu1, db)
    assert rtu1_resp.latitude == 21.0456
    assert rtu1_resp.longitude == 75.7890

    # 4. Test Hierarchy drill-down
    gw = Gateway(stngw_id="00000001", imei="867409070579901", station_id=s.id, rtu_id=rtu1.id)
    db.add(gw)
    db.flush()

    sc = SlaveCard(gateway_id=gw.id, card_address="81", card_type="Voltage")
    db.add(sc)
    db.commit()

    hier_res = get_rtu_hierarchy(rtu_id=rtu1.id, db=db, current_user=u)
    assert hier_res["status"] is True
    assert len(hier_res["data"]["master_cards"]) == 1
    assert len(hier_res["data"]["master_cards"][0].slave_cards) == 1
    assert len(hier_res["data"]["master_cards"][0].slave_cards[0].channels) == 12

    # 5. Test Decoupled Asset Mapping (Phase 2)
    asset = Asset(station_id=s.id, smms_asset_code="SMMS_PM_101", smms_asset_name="Point Machine 101", asset_number_code="PM-101", asset_number_id="01", asset_type_hex="00", station_gateway_id="00000001")
    db.add(asset)
    db.commit()

    map_req = AssetMappingAssignRequest(para_id="00018101", asset_id=asset.id, prloc="LB-01")
    map_res = map_asset_parameter(payload=map_req, db=db, current_user=u)
    assert map_res["status"] is True
    assert map_res["data"].is_assigned is True
    assert map_res["data"].asset_number_code == "PM-101"
    assert map_res["data"].prloc == "LB-01"

    # Link channel to slave card and verify in hierarchy drill-down
    ap = db.query(AssetParameter).filter(AssetParameter.para_id == "00018101").first()
    ap.slave_card_id = sc.id
    ap.channel_number = "CH1"
    db.commit()

    hier_res3 = get_rtu_hierarchy(rtu_id=rtu1.id, db=db, current_user=u)
    ch1_item = hier_res3["data"]["master_cards"][0].slave_cards[0].channels[0]
    assert ch1_item.channel_number == "CH1"
    assert ch1_item.para_id == "00018101"
    assert ch1_item.is_assigned is True
    assert ch1_item.asset_number_code == "PM-101"
    assert ch1_item.prloc == "LB-01"

    # Test unmap
    unmap_req = AssetMappingUnassignRequest(para_id="00018101")
    unmap_res = unmap_asset_parameter(payload=unmap_req, db=db, current_user=u)
    assert unmap_res["status"] is True
    assert unmap_res["data"].is_assigned is False
    assert unmap_res["data"].asset_id is None

