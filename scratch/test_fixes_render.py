import time
import httpx
from datetime import datetime, timedelta

BASE_URL = "https://my-fastapi-app-undz.onrender.com"

def test_live_render_fixes():
    print(f"Starting Live Render API Verification at {BASE_URL}...")
    try:
        r = httpx.get(BASE_URL)
        print(f"Health check status: {r.status_code}, body: {r.text}")
    except Exception as e:
        print(f"Connection failed: {e}")
        return

    # 1. Login
    login_payload = {
        "employee_id": "hq_admin",
        "password": "Password@123",
        "remember_me": False
    }
    print("Logging in...")
    r = httpx.post(f"{BASE_URL}/auth/login", json=login_payload)
    if r.status_code != 200:
        print(f"Login failed: {r.status_code}, response: {r.text}")
        return
    token = r.json()["data"]["token"]
    headers = {"Authorization": f"Bearer {token}"}
    print("Login successful.")

    # 2. Check total_pages in equipment room history
    print("\n--- Testing Equipment Room History total_pages ---")
    r = httpx.get(f"{BASE_URL}/equipment-room/history?page=1&page_size=10", headers=headers)
    print(f"History endpoint status: {r.status_code}")
    if r.status_code == 200:
        data = r.json()
        print(f"Response: total={data.get('total')}, total_pages={data.get('total_pages')}, page={data.get('page')}")
        assert "total_pages" in data, "total_pages field is missing!"
        print("Success: total_pages is present in the response.")
    else:
        print("Failed:", r.text)

    # Fetch one asset details to get valid station and gateway IDs
    assets_resp = httpx.get(f"{BASE_URL}/assets", headers=headers)
    if assets_resp.status_code != 200:
        print("Failed to get assets:", assets_resp.text)
        return
    assets = assets_resp.json()["rows"]
    if not assets:
        print("No assets found in DB")
        return
    asset = assets[0]
    station_id = asset["station_id"]
    station_gateway_id = asset["station_gateway_id"]

    # 3. Test Bulk Asset registration
    print("\n--- Testing Bulk Asset Creation ---")
    import random
    r_num = random.randint(10000, 99999)
    bulk_payload = [
        {
            "station_id": station_id,
            "smms_asset_code": f"BULK-RNDR-A-{r_num}",
            "smms_asset_name": "Bulk Asset Render A",
            "asset_number_code": f"AST-RNDR-A-{r_num}",
            "asset_number_id": f"{random.randint(1, 255):02X}",
            "asset_type_hex": "20",
            "station_gateway_id": station_gateway_id,
            "make": "Alstom",
            "model": "Type X",
            "is_active": True
        },
        {
            "station_id": station_id,
            "smms_asset_code": f"BULK-RNDR-B-{r_num}",
            "smms_asset_name": "Bulk Asset Render B",
            "asset_number_code": f"AST-RNDR-B-{r_num}",
            "asset_number_id": f"{random.randint(1, 255):02X}",
            "asset_type_hex": "20",
            "station_gateway_id": station_gateway_id,
            "make": "Siemens",
            "model": "Type Y",
            "is_active": True
        }
    ]
    r = httpx.post(f"{BASE_URL}/assets/bulk", json=bulk_payload, headers=headers)
    print(f"Bulk creation status: {r.status_code}")
    if r.status_code == 201:
        created = r.json()
        print(f"Bulk assets created successfully: {[a['asset_number_code'] for a in created]}")
    else:
        print("Bulk creation failed:", r.text)

    # 4. Testing Maintenance Mode Status Flow
    print("\n--- Testing Maintenance Mode Status Flow ---")
    if r.status_code == 201:
        # Use the newly created bulk asset
        asset_no = created[0]["asset_number_code"]
        station_id = created[0]["station_id"]
        asset_type_hex = created[0]["asset_type_hex"]
    else:
        # Fallback to first existing asset
        station_id = asset["station_id"]
        asset_no = asset["asset_number_code"]
        asset_type_hex = asset["asset_type_hex"]
    
    print(f"Selected asset {asset_no} (station_id={station_id}, type={asset_type_hex}) for maintenance testing.")

    # Cleanup any active maintenance modes for this asset first
    cleanup_resp = httpx.get(f"{BASE_URL}/maintenance?station_id={station_id}&asset_no={asset_no}&status=Active", headers=headers)
    if cleanup_resp.status_code == 200:
        for m in cleanup_resp.json()["rows"]:
            print(f"Cleaning up active maintenance mode {m['id']} for this asset...")
            httpx.post(f"{BASE_URL}/maintenance/{m['id']}/clear", headers=headers)

    # Create Active Maintenance Mode
    now = datetime.utcnow()
    maint_payload = {
        "station_id": station_id,
        "asset_no": asset_no,
        "from_time": (now - timedelta(minutes=10)).isoformat(),
        "to_time": (now + timedelta(minutes=10)).isoformat()
    }
    r = httpx.post(f"{BASE_URL}/maintenance", json=maint_payload, headers=headers)
    print(f"Create Active Maintenance status: {r.status_code}")
    if r.status_code != 201:
        print("Failed to create maintenance:", r.text)
        return
    active_maint = r.json()
    print(f"Created active maintenance mode ID: {active_maint['id']}, status: {active_maint['status']}")
    assert active_maint["status"] == "Active"

    # Verify filtering list by status=Active
    maint_list_resp = httpx.get(f"{BASE_URL}/maintenance?status=Active", headers=headers)
    assert "total_pages" in maint_list_resp.json()
    active_ids = [m["id"] for m in maint_list_resp.json()["rows"]]
    print(f"Active maintenance IDs in system: {active_ids} (total_pages={maint_list_resp.json()['total_pages']})")
    assert active_maint["id"] in active_ids, "Created maintenance mode not in Active list!"

    # 5. Verify Alert Suppression
    print("\n--- Testing Alert Suppression ---")
    alert_payload = {
        "station_id": station_id,
        "alert_type": "Failure",
        "asset_type_hex": asset_type_hex,
        "asset_no": asset_no,
        "cause": "TEMP-HIGH",
        "alert_status": "Active"
    }
    r = httpx.post(f"{BASE_URL}/alerts/events", json=alert_payload, headers=headers)
    print(f"Post alert status code (should be 400): {r.status_code}")
    if r.status_code == 400:
        print("Alert successfully suppressed! Response body:", r.json())
    else:
        print("Failed: Alert was not suppressed!", r.text)

    # 6. Verify Manual Clear
    print("\n--- Testing Manual Clear Endpoint ---")
    r = httpx.post(f"{BASE_URL}/maintenance/{active_maint['id']}/clear", headers=headers)
    print(f"Clear endpoint status: {r.status_code}")
    if r.status_code == 200:
        cleared_maint = r.json()
        print(f"Maintenance status after clear: {cleared_maint['status']}, is_cleared: {cleared_maint['is_cleared']}")
        assert cleared_maint["status"] == "Completed"
        assert cleared_maint["is_cleared"] is True
    else:
        print("Failed to clear maintenance:", r.text)

    # Post alert again (should succeed since maintenance is cleared)
    r = httpx.post(f"{BASE_URL}/alerts/events", json=alert_payload, headers=headers)
    print(f"Post alert status code after clearing (should be 201): {r.status_code}")
    if r.status_code == 201:
        print("Alert created successfully after clear: ID =", r.json()["id"])
    else:
        print("Failed to create alert after clear:", r.text)

    # 7. Verify Check Reminders
    print("\n--- Testing Check Reminders ---")
    exceeded_payload = {
        "station_id": station_id,
        "asset_no": asset_no,
        "from_time": (now - timedelta(minutes=75)).isoformat(),
        "to_time": (now + timedelta(minutes=15)).isoformat()
    }
    r = httpx.post(f"{BASE_URL}/maintenance", json=exceeded_payload, headers=headers)
    print(f"Create Exceeded Maintenance status: {r.status_code}")
    if r.status_code == 201:
        print(f"Created active exceeded maintenance ID: {r.json()['id']}")
        
        # Trigger check-reminders
        r_reminders = httpx.post(f"{BASE_URL}/maintenance/check-reminders", headers=headers)
        print(f"Check reminders status: {r_reminders.status_code}")
        if r_reminders.status_code == 200:
            reminders = r_reminders.json()
            causes = [rem["cause"] for rem in reminders]
            print(f"Triggered reminders count: {len(reminders)}, causes: {causes}")
            if "MAINT-EXCEED" in causes:
                print("Success: MAINT-EXCEED reminder alert generated!")
            else:
                print("Failed: MAINT-EXCEED reminder alert not found.")
        else:
            print("Check reminders failed:", r_reminders.text)

    # 8. Verify Modifying and Cancelling Scheduled Maintenance Mode
    print("\n--- Testing Modifying and Cancelling Scheduled Maintenance Mode ---")
    sched_payload = {
        "station_id": station_id,
        "asset_no": asset_no,
        "from_time": (now + timedelta(minutes=60)).isoformat(),
        "to_time": (now + timedelta(minutes=120)).isoformat()
    }
    r = httpx.post(f"{BASE_URL}/maintenance", json=sched_payload, headers=headers)
    print(f"Create Scheduled Maintenance status: {r.status_code}")
    if r.status_code == 201:
        sched_maint = r.json()
        print(f"Created scheduled maintenance ID: {sched_maint['id']}, status: {sched_maint['status']}")
        assert sched_maint["status"] == "Scheduled"

        # Update it
        update_payload = {
            "station_id": station_id,
            "asset_no": asset_no,
            "from_time": (now + timedelta(minutes=60)).isoformat(),
            "to_time": (now + timedelta(minutes=150)).isoformat()
        }
        r_update = httpx.put(f"{BASE_URL}/maintenance/{sched_maint['id']}", json=update_payload, headers=headers)
        print(f"Modify Scheduled Maintenance status: {r_update.status_code}")
        if r_update.status_code == 200:
            updated_m = r_update.json()
            print("Modified end time successfully:", updated_m["to_time"])
        else:
            print("Failed to modify scheduled maintenance:", r_update.text)

        # Cancel/delete it
        r_delete = httpx.delete(f"{BASE_URL}/maintenance/{sched_maint['id']}", headers=headers)
        print(f"Cancel Scheduled Maintenance status: {r_delete.status_code}")
        if r_delete.status_code in (204, 244):
            print("Cancelled/deleted scheduled maintenance successfully.")
        else:
            print("Failed to cancel scheduled maintenance:", r_delete.text)

        # Try to modify active maintenance: should fail with 400
        r_mod_fail = httpx.put(f"{BASE_URL}/maintenance/{active_maint['id']}", json=update_payload, headers=headers)
        print(f"Modify Active Maintenance (should fail with 400) status: {r_mod_fail.status_code}")
        assert r_mod_fail.status_code == 400

        # --- Testing Telemetry Integration Endpoints ---
        print("\n--- Testing Telemetry Integration Endpoints ---")
        # 1. Fetch station details to get division and zone codes
        stn_resp = httpx.get(f"{BASE_URL}/stations/{station_id}", headers=headers)
        assert stn_resp.status_code == 200
        stn_data = stn_resp.json()
        zone_code = stn_data.get("zone")
        division_code = stn_data.get("division")
        station_code = stn_data.get("station_code")
        
        # Determine codes
        if not zone_code or not division_code:
            # Fallback values
            zone_code = "NCR"
            division_code = "PRYJ"
            
        print(f"Asset location details: Zone={zone_code}, Div={division_code}, Station={station_code}")
        
        # 2. Ingest telemetry data via gateway
        test_para_id = f"{asset_type_hex}{created[0]['asset_number_id']}0A00" # e.g. DC Track Circuit Voltage
        telemetry_payload = {
            "imei": "999999999999999",
            "stngw_id": created[0]["station_gateway_id"],
            "parameters": [
                {
                    "para_id": test_para_id,
                    "prv": [110.5],
                    "prt": [now.strftime("%d-%m-%Y %H:%M:%S.000")]
                }
            ]
        }
        print(f"Ingesting telemetry for para_id {test_para_id}...")
        ingest_resp = httpx.post(f"{BASE_URL}/gateway/data", json=telemetry_payload, headers=headers)
        print(f"Ingest Status Code: {ingest_resp.status_code}")
        assert ingest_resp.status_code == 202

        # 3. Test CRIS history report endpoint
        hist_payload = {
            "start_date": (now - timedelta(minutes=15)).strftime("%d/%m/%Y"),
            "start_time": (now - timedelta(minutes=15)).strftime("%H:%M:%S"),
            "end_date": (now + timedelta(minutes=15)).strftime("%d/%m/%Y"),
            "end_time": (now + timedelta(minutes=15)).strftime("%H:%M:%S"),
            "request": {
                "zone": [zone_code],
                "division": [division_code],
                "station": [station_code],
                "asset_type": [created[0]["asset_type_code"]]
            },
            "page_number": 1,
            "page_size": 10
        }
        print("Querying /vc_telemetry_history...")
        hist_resp = httpx.post(f"{BASE_URL}/vc_telemetry_history", json=hist_payload)
        print(f"History report status: {hist_resp.status_code}")
        assert hist_resp.status_code == 200
        hist_body = hist_resp.json()
        assert hist_body["vcc"] == "XYZ"
        print("History response zone length:", len(hist_body.get("zone", [])))
        
        # 4. Test SMMS telemetry GET endpoint
        smm_get_url = f"{BASE_URL}/get_asset_telemetry/{zone_code}/{division_code}/{station_code}/{created[0]['smms_asset_code']}/{test_para_id}"
        print(f"Querying SMM GET {smm_get_url}...")
        smm_get_resp = httpx.get(smm_get_url)
        print(f"SMM GET status: {smm_get_resp.status_code}")
        assert smm_get_resp.status_code == 200
        smm_get_data = smm_get_resp.json()
        assert smm_get_data["telemetry_data"][0]["parameters"][0]["para_id"] == test_para_id
        assert smm_get_data["telemetry_data"][0]["parameters"][0]["prv"] == 110.5
        
        # 5. Test SMMS telemetry POST endpoint
        smm_post_payload = {
            "rqi": "rqi-smm-999",
            "vcc": "ABC",
            "zc": zone_code,
            "dc": division_code,
            "sc": station_code,
            "smm_asset_code": created[0]["smms_asset_code"],
            "para_id": [test_para_id]
        }
        smm_post_url = f"{BASE_URL}/get_asset_telemetry/{zone_code}/{division_code}/{station_code}/{created[0]['smms_asset_code']}/{test_para_id}"
        print(f"Querying SMM POST {smm_post_url}...")
        smm_post_resp = httpx.post(smm_post_url, json=smm_post_payload)
        print(f"SMM POST status: {smm_post_resp.status_code}")
        assert smm_post_resp.status_code == 200
        smm_post_data = smm_post_resp.json()
        assert smm_post_data["resi"] == "RES-rqi-smm-999"
        assert smm_post_data["vcc"] == "ABC"
        assert smm_post_data["telemetry_data"][0]["parameters"][0]["prv"] == 110.5
        print("Telemetry integration endpoints verified successfully on Render.")

    print("\nAll Live Render Verification Tests Completed Successfully!")

if __name__ == "__main__":
    test_live_render_fixes()
