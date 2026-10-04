import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.database import SessionLocal
from app.models.models import Gateway, Station, RTU, SlaveCard, Telemetry

client = TestClient(app)


def get_auth_token():
    res = client.post("/auth/login", json={"employee_id": "hq_admin", "password": "admin123", "remember_me": False})
    assert res.status_code == 200, f"Login failed: {res.text}"
    return res.json()["data"]["token"]


@pytest.fixture(scope="module")
def auth_headers():
    token = get_auth_token()
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module")
def test_station():
    db = SessionLocal()
    stn = db.query(Station).filter(Station.station_code == "NDLS").first()
    if not stn:
        stn = db.query(Station).first()
    assert stn is not None, "Station must exist"
    db.close()
    return stn


def test_list_rtus(auth_headers):
    res = client.get("/rtu/?page=1&page_size=10", headers=auth_headers)
    assert res.status_code == 200
    data = res.json()["data"]
    assert "total" in data
    assert "rows" in data
    assert isinstance(data["rows"], list)


def test_preview_stngw_id(auth_headers, test_station):
    res = client.get(f"/rtu/preview-stngw-id?station_id={test_station.id}&gateway_number_hex=EE", headers=auth_headers)
    assert res.status_code == 200
    data = res.json()["data"]
    assert data["is_valid"] is True
    assert len(data["stngw_id"]) == 8
    assert data["gateway_number_hex"] == "EE"
    assert data["station_code"] == test_station.station_code


def test_preview_stngw_id_invalid_hex(auth_headers, test_station):
    res = client.get(f"/rtu/preview-stngw-id?station_id={test_station.id}&gateway_number_hex=ZZ", headers=auth_headers)
    assert res.status_code == 400


def test_create_and_delete_rtu_workflow(auth_headers, test_station):
    # 1. Create RTU with 2 master cards
    payload = {
        "station_id": test_station.id,
        "rtu_name": "RTU-Pytest-Unit",
        "location": "Relay Room East",
        "description": "Integration test RTU",
        "master_cards": [
            {"card_number": 1, "gateway_number_hex": "E1", "imei": "99988877766651"},
            {"card_number": 2, "gateway_number_hex": "E2", "imei": "99988877766652"},
        ],
    }
    create_res = client.post("/rtu/", json=payload, headers=auth_headers)
    assert create_res.status_code == 201, f"Create failed: {create_res.text}"
    created_rtu = create_res.json()["data"]
    rtu_id = created_rtu["id"]

    assert created_rtu["rtu_name"] == "RTU-Pytest-Unit"
    assert created_rtu["master_cards_count"] == 2
    assert len(created_rtu["master_cards"]) == 2

    # 2. Get RTU details
    get_res = client.get(f"/rtu/{rtu_id}", headers=auth_headers)
    assert get_res.status_code == 200
    assert get_res.json()["data"]["id"] == rtu_id

    # 3. Update RTU metadata
    update_res = client.put(f"/rtu/{rtu_id}", json={"location": "Relay Room West", "description": "Updated"}, headers=auth_headers)
    assert update_res.status_code == 200
    assert update_res.json()["data"]["location"] == "Relay Room West"

    # 4. Add another master card
    add_mc_res = client.post(
        f"/rtu/{rtu_id}/master-cards",
        json={"gateway_number_hex": "E3", "imei": "99988877766653"},
        headers=auth_headers,
    )
    assert add_mc_res.status_code == 200
    assert add_mc_res.json()["data"]["master_cards_count"] == 3

    # Find the added card ID
    added_card = next(c for c in add_mc_res.json()["data"]["master_cards"] if c["gateway_number_hex"] == "E3")

    # 5. Remove that master card
    rem_res = client.delete(f"/rtu/{rtu_id}/master-cards/{added_card['id']}", headers=auth_headers)
    assert rem_res.status_code == 200
    assert rem_res.json()["data"]["master_cards_count"] == 2

    # 6. Delete the RTU
    del_res = client.delete(f"/rtu/{rtu_id}", headers=auth_headers)
    assert del_res.status_code == 200

    # Verify 404 after deletion
    get_after = client.get(f"/rtu/{rtu_id}", headers=auth_headers)
    assert get_after.status_code == 404


def test_delete_rtu_blocked_by_slaves(auth_headers, test_station):
    db = SessionLocal()
    # Create an RTU with a master card that has a slave card
    payload = {
        "station_id": test_station.id,
        "rtu_name": "RTU-With-Slave",
        "location": "Test Loc",
        "master_cards": [{"gateway_number_hex": "E9", "imei": "99988877766699"}],
    }
    create_res = client.post("/rtu/", json=payload, headers=auth_headers)
    assert create_res.status_code == 201
    rtu_id = create_res.json()["data"]["id"]
    gw_id = create_res.json()["data"]["master_cards"][0]["id"]

    # Add a slave card to this gateway
    slave = SlaveCard(gateway_id=gw_id, card_address="98", card_type="Voltage")
    db.add(slave)
    db.commit()

    # Attempt deletion -> should fail with 400
    del_res = client.delete(f"/rtu/{rtu_id}", headers=auth_headers)
    assert del_res.status_code == 400
    assert "Slave Cards" in del_res.json()["message"] or "Slave Cards" in del_res.json().get("detail", "")

    # Cleanup slave then delete
    db.delete(slave)
    db.commit()
    db.close()

    cleanup_res = client.delete(f"/rtu/{rtu_id}", headers=auth_headers)
    assert cleanup_res.status_code == 200


def test_create_and_update_rtu_with_master_card_ids(auth_headers, test_station):
    db = SessionLocal()
    # Create a temporary unlinked gateway at this station
    temp_gw = Gateway(
        stngw_id="TESTGW99",
        imei="99988877799999",
        station_id=test_station.id,
    )
    db.add(temp_gw)
    db.commit()
    db.refresh(temp_gw)
    temp_gw_id = temp_gw.id
    db.close()

    try:
        # 1. Create RTU using master_card_ids array
        payload = {
            "station_id": test_station.id,
            "rtu_name": "RTU-With-MC-Ids",
            "location": "Relay Room Test",
            "master_card_ids": [temp_gw_id],
        }
        res = client.post("/rtu/", json=payload, headers=auth_headers)
        assert res.status_code == 201, f"Failed to create: {res.text}"
        data = res.json()["data"]
        rtu_id = data["id"]

        assert data["master_cards_count"] == 1
        assert temp_gw_id in data["master_card_ids"]
        assert data["master_cards"][0]["id"] == temp_gw_id

        # 2. Update RTU with master_cards_id alias (e.g. Imran's format)
        put_payload = {
            "master_cards_id": [temp_gw_id],
            "location": "Relay Room Updated",
        }
        put_res = client.put(f"/rtu/{rtu_id}", json=put_payload, headers=auth_headers)
        assert put_res.status_code == 200
        put_data = put_res.json()["data"]
        assert put_data["location"] == "Relay Room Updated"
        assert temp_gw_id in put_data["master_card_ids"]

        # 3. Clean up RTU
        del_res = client.delete(f"/rtu/{rtu_id}", headers=auth_headers)
        assert del_res.status_code == 200
    finally:
        # Ensure temp_gw is cleaned up if still present
        db2 = SessionLocal()
        gw_left = db2.query(Gateway).filter(Gateway.id == temp_gw_id).first()
        if gw_left:
            db2.delete(gw_left)
            db2.commit()
        db2.close()

