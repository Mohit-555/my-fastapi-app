import unittest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from datetime import datetime

from app.main import app
from app.database import get_db, SessionLocal
from app.models.models import Zone, Division, Station, Gateway, Telemetry, Asset, AlertEvent, EquipmentRoom, MaintenanceMode, Role, User, AlertCauseMaster, AssetTypeMaster

class TestFixesAndFeatures(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        
        # 1. Login to get HQ Admin token
        login_payload = {
            "employee_id": "hq_admin",
            "password": "Password@123",
            "remember_me": False
        }
        response = cls.client.post("/auth/login", json=login_payload)
        assert response.status_code == 200, f"Login failed: {response.text}"
        cls.token = response.json()["data"]["token"]
        cls.headers = {"Authorization": f"Bearer {cls.token}"}

    def test_alert_filters_contains_makes(self):
        # Verify that get_alert_filters returns asset_makes
        response = self.client.get("/alerts/filters", headers=self.headers)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("asset_makes", data)
        print("Alert Filters response data 'asset_makes':", data["asset_makes"])

    def test_admin_user_create_and_delete(self):
        # 1. Create a user via POST /admin/users
        payload = {
            "full_name": "Test Admin Created User",
            "employee_id": "test_admin_emp_99",
            "designation": "SSE Signal",
            "role_id": 4, # Division Engineer
            "mobile_number": "9999999999",
            "email": "test_admin_emp_99@rdpms.gov.in",
            "password": "Password@123",
            "confirm_password": "Password@123"
        }
        
        # Verify creating
        response = self.client.post("/admin/users", json=payload, headers=self.headers)
        self.assertEqual(response.status_code, 201, response.text)
        user_data = response.json()
        self.assertEqual(user_data["employee_id"], "test_admin_emp_99")
        created_user_id = user_data["id"]
        print(f"Created user with ID: {created_user_id} via Admin API.")

        # Try to create with duplicate employee_id should fail
        response_dup = self.client.post("/admin/users", json=payload, headers=self.headers)
        self.assertEqual(response_dup.status_code, 400)

        # 1.5. Update user password via PUT /admin/users/{user_id}
        update_payload = {
            "full_name": "Test Admin Created User Updated",
            "password": "NewPassword@123",
            "confirm_password": "NewPassword@123"
        }
        response_update = self.client.put(f"/admin/users/{created_user_id}", json=update_payload, headers=self.headers)
        self.assertEqual(response_update.status_code, 200)
        self.assertEqual(response_update.json()["full_name"], "Test Admin Created User Updated")
        print("Updated user password via Admin PUT API.")

        # Test login with the new password
        login_test_payload = {
            "employee_id": "test_admin_emp_99",
            "password": "NewPassword@123",
            "remember_me": False
        }
        response_login = self.client.post("/auth/login", json=login_test_payload)
        self.assertEqual(response_login.status_code, 200)
        print("Successfully verified logging in with the updated password.")

        # 2. Delete the user via DELETE /admin/users/{user_id}
        response_del = self.client.delete(f"/admin/users/{created_user_id}", headers=self.headers)
        self.assertEqual(response_del.status_code, 204)
        print(f"Deleted user with ID: {created_user_id} via Admin API.")

        # Double check user is gone
        response_get = self.client.get(f"/admin/users/{created_user_id}", headers=self.headers)
        self.assertEqual(response_get.status_code, 404)

    def test_cascade_delete_master(self):
        # Setup session
        db = SessionLocal()
        
        # 1. Create a test hierarchy
        zone = Zone(zone_name="CASCADE TEST ZONE", zone_code="CTZ", zone_id_hex="AA")
        db.add(zone)
        db.flush()

        division = Division(division_name="CASCADE TEST DIV", division_code="CTD", division_id_hex="AA", zone_id=zone.id)
        db.add(division)
        db.flush()

        station = Station(station_name="CASCADE TEST STN", station_code="CTS", station_id_hex="AA", division_id=division.id)
        db.add(station)
        db.flush()

        gateway = Gateway(stngw_id="CTSGWAAA", imei="987654321012345", station_id=station.id)
        db.add(gateway)
        db.flush()

        telemetry = Telemetry(gateway_id=gateway.id, para_id="88888888", prv=1.0, prt="2026-06-16T12:00:00")
        db.add(telemetry)
        
        asset = Asset(
            smms_asset_code="CT-ASSET-001",
            smms_asset_name="Cascade Test Asset",
            asset_number_code="CT-A1",
            asset_number_id="01",
            asset_type_hex="00",
            station_gateway_id=gateway.stngw_id,
            station_id=station.id
        )
        db.add(asset)
        db.flush()

        alert = AlertEvent(
            station_id=station.id,
            alert_type="Failure",
            asset_type_hex="00",
            asset_no="CT-A1",
            cause="TEST-CAUSE",
            alert_status="Active"
        )
        db.add(alert)

        eq_room = EquipmentRoom(
            station_id=station.id,
            room_type="RR",
            temperature=22.5,
            humidity=45.0,
            updated_at=datetime.utcnow()
        )
        db.add(eq_room)

        maint = MaintenanceMode(
            station_id=station.id,
            asset_type_hex="00",
            asset_no="CT-A1",
            from_time=datetime.utcnow(),
            to_time=datetime.utcnow()
        )
        db.add(maint)

        db.commit()
        print("Hierarchy for cascade test created.")

        # Store IDs for verification
        zone_id = zone.id
        div_id = division.id
        stn_id = station.id
        gw_id = gateway.id
        tel_id = telemetry.id
        asset_id = asset.id
        alert_id = alert.id
        eq_id = eq_room.id
        maint_id = maint.id

        # 2. Call the DELETE /zones/{zone_id} endpoint
        response = self.client.delete(f"/zones/{zone_id}", headers=self.headers)
        self.assertEqual(response.status_code, 204)
        print("Zone delete call completed successfully.")

        # 3. Verify all associated records are gone
        db.close()
        db = SessionLocal()
        
        self.assertIsNone(db.query(Zone).filter(Zone.id == zone_id).first())
        self.assertIsNone(db.query(Division).filter(Division.id == div_id).first())
        self.assertIsNone(db.query(Station).filter(Station.id == stn_id).first())
        self.assertIsNone(db.query(Gateway).filter(Gateway.id == gw_id).first())
        self.assertIsNone(db.query(Telemetry).filter(Telemetry.id == tel_id).first())
        self.assertIsNone(db.query(Asset).filter(Asset.id == asset_id).first())
        self.assertIsNone(db.query(AlertEvent).filter(AlertEvent.id == alert_id).first())
        self.assertIsNone(db.query(EquipmentRoom).filter(EquipmentRoom.id == eq_id).first())
        self.assertIsNone(db.query(MaintenanceMode).filter(MaintenanceMode.id == maint_id).first())
        print("Verified that all related tables cascade deleted correctly without DB constraints failing.")
        
        db.close()

    def test_remove_menu_from_role_validations(self):
        # 1. Invalid role_id
        response = self.client.delete("/admin/roles/9999/menus/1", headers=self.headers)
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["message"], "Role 9999 not found")

        # 2. Invalid menu_id with valid role_id
        response = self.client.delete("/admin/roles/1/menus/9999", headers=headers) if not hasattr(self, 'headers') else self.client.delete("/admin/roles/1/menus/9999", headers=self.headers)
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["message"], "Menu 9999 not found")

        print("Verified delete role menu endpoint validations successfully.")

    def test_equipment_room_history_total_pages(self):
        response = self.client.get("/equipment-room/history?page=1&page_size=10", headers=self.headers)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("total_pages", data)
        self.assertEqual(data["page"], 1)
        self.assertEqual(data["page_size"], 10)
        print("Verified equipment room history returns 'total_pages' field: ", data["total_pages"])

    def test_maintenance_mode_activation_with_new_fields(self):
        # 1. Fetch an existing asset to use its station_id and asset_number_code
        assets_resp = self.client.get("/assets", headers=self.headers)
        self.assertEqual(assets_resp.status_code, 200)
        assets = assets_resp.json()["rows"]
        self.assertTrue(len(assets) > 0, "No assets found in database to perform maintenance mode test")
        
        asset = assets[0]
        station_id = asset["station_id"]
        asset_no = asset["asset_number_code"] # or smms_asset_code
        
        # 2. Call POST /maintenance
        payload = {
            "station_id": station_id,
            "asset_no": asset_no,
            "from_date": "2026-06-24T12:00:00Z",
            "to_date": "2026-06-24T18:00:00Z"
        }
        response = self.client.post("/maintenance", json=payload, headers=self.headers)
        self.assertEqual(response.status_code, 201, response.text)
        
        data = response.json()
        self.assertEqual(data["station_id"], station_id)
        self.assertEqual(data["asset_no"], asset_no)
        self.assertIn("from_date", data)
        self.assertIn("to_date", data)
        self.assertIn("from_time", data)
        self.assertIn("to_time", data)
        self.assertEqual(data["asset_type_hex"], asset["asset_type_hex"])
        print("Verified maintenance mode activation with new fields successfully.")

if __name__ == "__main__":
    unittest.main()
