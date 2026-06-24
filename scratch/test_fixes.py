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
        print("Verified maintenance mode activation with both date and time fields successfully.")

    def test_maintenance_mode_status_and_endpoints(self):
        # 1. Fetch an existing asset
        assets_resp = self.client.get("/assets", headers=self.headers)
        self.assertEqual(assets_resp.status_code, 200)
        assets = assets_resp.json()["rows"]
        self.assertTrue(len(assets) > 0, "No assets found in database")
        asset = assets[0]
        station_id = asset["station_id"]
        asset_no = asset["asset_number_code"]
        
        # Let's import datetime and timedelta
        from datetime import datetime, timedelta

        # Clean up any existing active maintenance modes and alerts for this asset to avoid conflicts
        db_sess = SessionLocal()
        try:
            db_sess.query(AlertEvent).filter(
                AlertEvent.station_id == station_id,
                AlertEvent.asset_no == asset_no,
                AlertEvent.cause == "MAINT-EXCEED"
            ).delete()
            db_sess.query(MaintenanceMode).filter(
                MaintenanceMode.station_id == station_id,
                MaintenanceMode.asset_no == asset_no
            ).delete()
            db_sess.commit()
        finally:
            db_sess.close()

        now = datetime.utcnow()
        # 2. Create Active Maintenance Mode
        active_payload = {
            "station_id": station_id,
            "asset_no": asset_no,
            "from_time": (now - timedelta(minutes=10)).isoformat(),
            "to_time": (now + timedelta(minutes=10)).isoformat()
        }
        res_active = self.client.post("/maintenance", json=active_payload, headers=self.headers)
        self.assertEqual(res_active.status_code, 201, res_active.text)
        active_data = res_active.json()
        self.assertEqual(active_data["status"], "Active")

        # 3. Create Scheduled Maintenance Mode
        sched_payload = {
            "station_id": station_id,
            "asset_no": asset_no,
            "from_time": (now + timedelta(minutes=20)).isoformat(),
            "to_time": (now + timedelta(minutes=40)).isoformat()
        }
        res_sched = self.client.post("/maintenance", json=sched_payload, headers=self.headers)
        self.assertEqual(res_sched.status_code, 201, res_sched.text)
        sched_data = res_sched.json()
        self.assertEqual(sched_data["status"], "Scheduled")

        # 4. Create Completed Maintenance Mode (by past times)
        past_payload = {
            "station_id": station_id,
            "asset_no": asset_no,
            "from_time": (now - timedelta(minutes=40)).isoformat(),
            "to_time": (now - timedelta(minutes=20)).isoformat()
        }
        res_past = self.client.post("/maintenance", json=past_payload, headers=self.headers)
        self.assertEqual(res_past.status_code, 201, res_past.text)
        past_data = res_past.json()
        self.assertEqual(past_data["status"], "Completed")

        # 5. Verify GET /maintenance filtering by status
        # Active filter
        get_active = self.client.get("/maintenance?status=Active", headers=self.headers)
        self.assertEqual(get_active.status_code, 200)
        active_list = [row["id"] for row in get_active.json()["rows"]]
        self.assertIn(active_data["id"], active_list)
        self.assertNotIn(sched_data["id"], active_list)
        self.assertNotIn(past_data["id"], active_list)

        # Scheduled filter
        get_sched = self.client.get("/maintenance?status=Scheduled", headers=self.headers)
        self.assertEqual(get_sched.status_code, 200)
        sched_list = [row["id"] for row in get_sched.json()["rows"]]
        self.assertIn(sched_data["id"], sched_list)
        self.assertNotIn(active_data["id"], sched_list)

        # Completed filter
        get_completed = self.client.get("/maintenance?status=Completed", headers=self.headers)
        self.assertEqual(get_completed.status_code, 200)
        comp_list = [row["id"] for row in get_completed.json()["rows"]]
        self.assertIn(past_data["id"], comp_list)

        # 6. Test Alert Suppression during active maintenance
        # Try to post an alert for active asset - should fail with 400
        alert_payload = {
            "station_id": station_id,
            "alert_type": "Failure",
            "asset_type_hex": asset["asset_type_hex"],
            "asset_no": asset_no,
            "cause": "TEMP-HIGH",
            "alert_status": "Active"
        }
        res_alert_fail = self.client.post("/alerts/events", json=alert_payload, headers=self.headers)
        self.assertEqual(res_alert_fail.status_code, 400)
        self.assertIn("Alert suppressed", res_alert_fail.json()["message"])

        # 7. Test Manual Clear endpoint
        res_clear = self.client.post(f"/maintenance/{active_data['id']}/clear", headers=self.headers)
        self.assertEqual(res_clear.status_code, 200)
        clear_data = res_clear.json()
        self.assertEqual(clear_data["status"], "Completed")
        self.assertTrue(clear_data["is_cleared"])
        self.assertIsNotNone(clear_data["cleared_at"])

        # Now alerts should NOT be suppressed for this asset since maintenance is cleared/completed
        res_alert_ok = self.client.post("/alerts/events", json=alert_payload, headers=self.headers)
        self.assertEqual(res_alert_ok.status_code, 201)
        alert_ok_data = res_alert_ok.json()
        self.assertEqual(alert_ok_data["asset_no"], asset_no)

        # 8. Test Reminder Alerts for exceeded duration
        # Let's create an active maintenance mode for a Signal (type '10') that started 50 mins ago
        # Note: We need a station and asset of type '10' if possible. Let's find one or create one.
        # But we can also just use the current asset, but we can set its asset_type_hex to '10' in the payload or use '10'.
        # Since we resolved asset_type_hex dynamically from the asset, let's update our asset's type to '10' in DB or find an asset of type '10'.
        # Actually, let's find an asset with type '10' or '20' or '00'.
        signal_asset = None
        for a in assets:
            if a["asset_type_hex"] in ("10", "20", "00"):
                signal_asset = a
                break
        if not signal_asset:
            signal_asset = asset

        limit_payload = {
            "station_id": signal_asset["station_id"],
            "asset_no": signal_asset["asset_number_code"],
            # Started 50 mins ago (standard Signal limit is 45 min, standard other limit is 60 min, so 50 min exceeds Signal limit of 45 min)
            "from_time": (now - timedelta(minutes=50)).isoformat(),
            # Ends in 20 mins
            "to_time": (now + timedelta(minutes=20)).isoformat()
        }
        # If we need this to be treated as Signal, let's ensure its asset_type_hex in the database is '10'.
        # Let's query the DB and temporarily modify it, or just register it.
        # Actually, since from_time is 50 mins ago, let's force it to 70 mins ago so it exceeds 60 mins (which covers all asset types!).
        limit_payload["from_time"] = (now - timedelta(minutes=70)).isoformat()

        res_exceeded = self.client.post("/maintenance", json=limit_payload, headers=self.headers)
        self.assertEqual(res_exceeded.status_code, 201)
        exceeded_data = res_exceeded.json()
        self.assertEqual(exceeded_data["status"], "Active")

        # Now trigger check-reminders
        res_reminders = self.client.post("/maintenance/check-reminders", headers=self.headers)
        self.assertEqual(res_reminders.status_code, 200)
        reminders_data = res_reminders.json()
        self.assertTrue(len(reminders_data) > 0)
        
        # Verify the created reminder alert
        reminder_cause = [r["cause"] for r in reminders_data]
        self.assertIn("MAINT-EXCEED", reminder_cause)

        # 9. Test Modify & Cancel Scheduled maintenance modes
        # Can modify/delete Scheduled maintenance modes
        mod_payload = {
            "station_id": station_id,
            "asset_no": asset_no,
            "from_time": (now + timedelta(minutes=25)).isoformat(),
            "to_time": (now + timedelta(minutes=45)).isoformat()
        }
        res_mod = self.client.put(f"/maintenance/{sched_data['id']}", json=mod_payload, headers=self.headers)
        self.assertEqual(res_mod.status_code, 200)
        self.assertEqual(res_mod.json()["to_time"][:16], (now + timedelta(minutes=45)).strftime("%Y-%m-%dT%H:%M"))

        # Cannot modify Completed maintenance modes
        res_mod_past_fail = self.client.put(f"/maintenance/{past_data['id']}", json=mod_payload, headers=self.headers)
        self.assertEqual(res_mod_past_fail.status_code, 400)

        # Cannot modify Active maintenance modes
        # We need an active one: exceeded_data is active!
        res_mod_active_fail = self.client.put(f"/maintenance/{exceeded_data['id']}", json=mod_payload, headers=self.headers)
        self.assertEqual(res_mod_active_fail.status_code, 400)

        # Can cancel/delete Scheduled maintenance modes
        res_del = self.client.delete(f"/maintenance/{sched_data['id']}", headers=self.headers)
        self.assertIn(res_del.status_code, (204, 244))

        # Cannot cancel Completed maintenance modes
        res_del_past_fail = self.client.delete(f"/maintenance/{past_data['id']}", headers=self.headers)
        self.assertEqual(res_del_past_fail.status_code, 400)

        # Cannot cancel Active maintenance modes
        res_del_active_fail = self.client.delete(f"/maintenance/{exceeded_data['id']}", headers=self.headers)
        self.assertEqual(res_del_active_fail.status_code, 400)

        print("Verified maintenance mode statuses, manual clear, suppression, reminders, modification and cancellation successfully.")

if __name__ == "__main__":
    unittest.main()
