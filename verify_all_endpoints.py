import sys
from fastapi.testclient import TestClient
from app.main import app

def main():
    client = TestClient(app)
    print("Testing API standardization...")

    # 1. Login to get token
    login_payload = {
        "employee_id": "hq_admin",
        "password": "admin123",
        "remember_me": False
    }
    response = client.post("/auth/login", json=login_payload)
    if response.status_code != 200:
        print(f"Login failed: {response.text}")
        sys.exit(1)
    
    token = response.json()["data"]["token"]
    headers = {"Authorization": f"Bearer {token}"}
    print("Login successful. Token retrieved.")

    all_passed = True

    # Helper to check standard envelope structure
    def check_envelope(endpoint, response):
        nonlocal all_passed
        print(f"\nEndpoint: {endpoint}")
        print(f"Status Code: {response.status_code}")

        try:
            data = response.json()
        except Exception as e:
            print(f"FAILED to parse JSON: {e}")
            all_passed = False
            return False

        # Check status, message, data
        status_ok = "status" in data and isinstance(data["status"], bool)
        message_ok = "message" in data and isinstance(data["message"], str)
        data_ok = "data" in data

        if status_ok and message_ok and data_ok:
            print(f"PASSED: Standard response envelope verified. Status: {data['status']}, Message: '{data['message']}'")
            return True
        else:
            print(f"FAILED: Invalid envelope. Keys: {list(data.keys())}")
            if not status_ok:
                print("  - Missing/invalid 'status' (should be bool)")
            if not message_ok:
                print("  - Missing/invalid 'message' (should be str)")
            if not data_ok:
                print("  - Missing 'data'")
            all_passed = False
            return False

    # Test 1: config.py (/api/config/parameters)
    res = client.get("/api/config/parameters", headers=headers)
    check_envelope("GET /api/config/parameters", res)

    # Test 2: slave_card.py (/slave-cards)
    res = client.get("/slave-cards?page=1&page_size=2", headers=headers)
    check_envelope("GET /slave-cards", res)

    # Test 3: equipment_room.py (/equipment-room/live)
    res = client.get("/equipment-room/live", headers=headers)
    check_envelope("GET /equipment-room/live", res)

    # Test 4: equipment_room.py (/equipment-room/history)
    res = client.get("/equipment-room/history?page=1&page_size=2", headers=headers)
    check_envelope("GET /equipment-room/history", res)

    # Test 5: maintenance.py (/maintenance)
    res = client.get("/maintenance?page=1&page_size=2", headers=headers)
    check_envelope("GET /maintenance", res)

    # Test 6: decode.py (/decode/stngw/{stngw_id})
    res = client.get("/decode/stngw/05011200", headers=headers)
    check_envelope("GET /decode/stngw/05011200", res)

    # Test 7: admin.py (/admin/users)
    res = client.get("/admin/users?page=1&page_size=2", headers=headers)
    check_envelope("GET /admin/users", res)

    # Test 8: assets.py (/assets/utilization)
    res = client.get("/assets/utilization", headers=headers)
    check_envelope("GET /assets/utilization", res)

    if all_passed:
        print("\nALL STANDARDIZATION TESTS PASSED SUCCESSFULLY!")
        sys.exit(0)
    else:
        print("\nSOME STANDARDIZATION TESTS FAILED.")
        sys.exit(1)

if __name__ == "__main__":
    main()
