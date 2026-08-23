import unittest
from fastapi.testclient import TestClient
from app.main import app
from app.database import SessionLocal
from app.models.models import Gateway, Station, AssetParameter, SlaveCard, Zone, Division

class TestSlaveCardCRUD(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        cls.db = SessionLocal()

        # Clean up existing test records if any from previous dirty run
        cls.db.query(AssetParameter).filter(AssetParameter.para_id == "99999999").delete()
        cls.db.query(SlaveCard).filter(SlaveCard.card_address.in_(["81", "82", "83"])).delete()
        cls.db.query(Gateway).filter(Gateway.stngw_id == "BBBBGG01").delete()
        cls.db.query(Station).filter(Station.station_code == "TSS").delete()
        cls.db.query(Division).filter(Division.division_code == "TSD").delete()
        cls.db.query(Zone).filter(Zone.zone_code == "TSZ").delete()
        cls.db.commit()

        # Create a test Zone -> Division -> Station hierarchy
        cls.zone = Zone(zone_name="TEST SLAVE ZONE", zone_code="TSZ", zone_id_hex="BB")
        cls.db.add(cls.zone)
        cls.db.flush()

        cls.division = Division(division_name="TEST SLAVE DIV", division_code="TSD", division_id_hex="BB", zone_id=cls.zone.id)
        cls.db.add(cls.division)
        cls.db.flush()

        cls.station = Station(station_name="TEST SLAVE STN", station_code="TSS", station_id_hex="BB", division_id=cls.division.id)
        cls.db.add(cls.station)
        cls.db.flush()

        # Create a test Gateway linked to this station
        cls.gateway = Gateway(stngw_id="BBBBGG01", imei="987654321098765", station_id=cls.station.id)
        cls.db.add(cls.gateway)
        cls.db.commit()

        # Get Admin Login Token for auth headers
        login_payload = {
            "employee_id": "hq_admin",
            "password": "admin123",
            "remember_me": False
        }
        r = cls.client.post("/auth/login", json=login_payload)
        token = r.json()["data"]["token"]
        cls.headers = {"Authorization": f"Bearer {token}"}

    @classmethod
    def tearDownClass(cls):
        cls.db.query(AssetParameter).filter(AssetParameter.para_id == "99999999").delete()
        cls.db.query(SlaveCard).filter(SlaveCard.gateway_id == cls.gateway.id).delete()
        cls.db.query(Gateway).filter(Gateway.id == cls.gateway.id).delete()
        cls.db.query(Station).filter(Station.id == cls.station.id).delete()
        cls.db.query(Division).filter(Division.id == cls.division.id).delete()
        cls.db.query(Zone).filter(Zone.id == cls.zone.id).delete()
        cls.db.commit()
        cls.db.close()

    def test_slave_card_crud_operations(self):
        # 1. Attempt to create with invalid gateway
        invalid_payload = {
            "gateway_id": 99999,
            "card_address": "81",
            "card_type": "Voltage"
        }
        r = self.client.post("/slave-cards", json=invalid_payload, headers=self.headers)
        self.assertEqual(r.status_code, 404)

        # 2. Create a valid Slave Card
        valid_payload = {
            "gateway_id": self.gateway.id,
            "card_address": "81",
            "card_type": "Voltage"
        }
        r = self.client.post("/slave-cards", json=valid_payload, headers=self.headers)
        self.assertEqual(r.status_code, 201)
        card_data = r.json()["data"]
        self.assertEqual(card_data["card_address"], "81")
        self.assertEqual(card_data["card_type"], "Voltage")
        card_id = card_data["id"]

        # 3. Attempt to create a duplicate (should fail with 409 Conflict)
        r = self.client.post("/slave-cards", json=valid_payload, headers=self.headers)
        self.assertEqual(r.status_code, 409)

        # 4. Get the created Slave Card
        r = self.client.get(f"/slave-cards/{card_id}", headers=self.headers)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["data"]["card_type"], "Voltage")

        # 5. List Slave Cards with filtering by gateway_id
        r = self.client.get(f"/slave-cards?gateway_id={self.gateway.id}", headers=self.headers)
        self.assertEqual(r.status_code, 200)
        list_data = r.json()["data"]
        self.assertGreaterEqual(list_data["total"], 1)
        self.assertEqual(list_data["rows"][0]["id"], card_id)

        # 6. Update Slave Card configuration
        update_payload = {
            "card_address": "82",
            "card_type": "Analog"
        }
        r = self.client.put(f"/slave-cards/{card_id}", json=update_payload, headers=self.headers)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["data"]["card_address"], "82")
        self.assertEqual(r.json()["data"]["card_type"], "Analog")

        # 7. Create another card to test update conflict
        other_payload = {
            "gateway_id": self.gateway.id,
            "card_address": "83",
            "card_type": "DI"
        }
        r = self.client.post("/slave-cards", json=other_payload, headers=self.headers)
        self.assertEqual(r.status_code, 201)
        other_card_id = r.json()["data"]["id"]

        # Attempt to update second card to address "82"/Analog (should fail with 409)
        conflict_update = {
            "card_address": "82",
            "card_type": "Analog"
        }
        r = self.client.put(f"/slave-cards/{other_card_id}", json=conflict_update, headers=self.headers)
        self.assertEqual(r.status_code, 409)

        # 8. Test delete and cascading behavior on AssetParameter
        # Create an AssetParameter linked to this card
        ap = AssetParameter(para_id="99999999", slave_card_id=card_id)
        self.db.add(ap)
        self.db.commit()

        # Delete the card
        r = self.client.delete(f"/slave-cards/{card_id}", headers=self.headers)
        self.assertEqual(r.status_code, 204)

        # Verify the card is deleted from DB
        deleted_card = self.db.query(SlaveCard).filter(SlaveCard.id == card_id).first()
        self.assertIsNone(deleted_card)

        # Verify the AssetParameter now has slave_card_id = NULL
        self.db.refresh(ap)
        self.assertIsNone(ap.slave_card_id)

        # Clean up second card
        r = self.client.delete(f"/slave-cards/{other_card_id}", headers=self.headers)
        self.assertEqual(r.status_code, 204)

if __name__ == "__main__":
    unittest.main()
