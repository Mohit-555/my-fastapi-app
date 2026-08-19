# RDPMS Mobile App — Maintenance Mode Screen API Integration Guide

This guide provides the complete technical specification for mobile application developers (Flutter, React Native, Swift, Kotlin) integrating the **Maintenance Mode (05 · MAINTENANCE MODE)** screen with the RDPMS backend.

---

## 📱 Mobile Screen Mapping Overview

```
┌─────────────────────────────────────────────────────────────┐
│ 9:41                           RDPMS · IR-NET               │
│                                                             │
│ Maintenance Mode                                            │
│  [Zone ▾]  [Div ▾]  [Stn ▾]  [Asset type ▾]                 │  ◄── 1. Location & Asset Filters
│ ─────────────────────────────────────────────────────────── │
│ SCHEDULE WINDOW ──────────────────────────────────────────  │
│ FROM DATE / TIME              TO DATE / TIME                │  ◄── 2. Time Window Pickers
│ ┌──────────────────────┐      ┌──────────────────────┐      │
│ │ 03 Jul · 06:00       │      │ 03 Jul · 14:00       │      │
│ └──────────────────────┘      └──────────────────────┘      │
│ ─────────────────────────────────────────────────────────── │
│ TODAY · ZONE NR / DIV PRYJ ───────────────────────────────  │
│  00h      06h      12h      18h      24h                    │  ◄── 3. 24-Hour Maintenance Timeline
│  MJA · PT-04        [06:00-14:00]                           │      (Visual timeline bars)
│  GZB · TC-11   [02:00-05:30]                                │
│  DHN · SIG-02                        [20:00-23:00]          │
│ ─────────────────────────────────────────────────────────── │
│ ACTIVE & SCHEDULED ───────────────────────────────────────  │
│ STN / ASSET      ACTIVATES      CLEARS        ACTION        │  ◄── 4. Active & Scheduled List Table
│ ┌─────────────────────────────────────────────────────────┐ │
│ │ MJA · PT-04    03 Jul 06:00   03 Jul 14:00   [ Clear ]  │ │
│ │ GZB · TC-11    03 Jul 02:00   03 Jul 05:30   [ Clear ]  │ │
│ │ DHN · SIG-02   03 Jul 20:00   03 Jul 23:00   [ Clear ]  │ │
│ └─────────────────────────────────────────────────────────┘ │
│ ─────────────────────────────────────────────────────────── │
│   [DASHBOARD]   [ALERT]   [TELEMETRY]   [HEALTH]  [EQUIP]   │  ◄── 5. Bottom Navigation (Maintenance Active)
└─────────────────────────────────────────────────────────────┘
```

---

## 1. Authentication & Base URL

* **Production Base URL**: `https://my-fastapi-app-undz.onrender.com`
* **Authorization Header Required**:
  ```http
  Authorization: Bearer <JWT_TOKEN>
  Content-Type: application/json
  ```

---

## 2. API Specifications for Maintenance Mode

### API 1: Top Location & Asset Filter Options

Populate the filter bar dropdowns on screen mount.

* **HTTP Method**: `GET`
* **Endpoint**: `/alerts/filters`
* **cURL Request**:
  ```bash
  curl -X GET "https://my-fastapi-app-undz.onrender.com/alerts/filters" \
       -H "Authorization: Bearer <YOUR_JWT_TOKEN>"
  ```

---

### API 2: Fetch Active & Scheduled Maintenance List (`GET /maintenance`)

Fetches all active, scheduled, or completed maintenance mode records for the timeline view and active list table.

* **HTTP Method**: `GET`
* **Endpoint**: `/maintenance`
* **Query Parameters** (Optional Filters):
  * `zone_id` (integer)
  * `division_id` (integer)
  * `station_id` (integer)
  * `asset_type` (string, e.g. `"00"` for Point Machine)
  * `asset_no` (string, e.g. `"PT-04"`)
  * `status` (string, e.g. `"Active"`, `"Scheduled"`, or `"Completed"`)
  * `page` (integer, default `1`)
  * `page_size` (integer, default `20`)

* **cURL Request**:
  ```bash
  curl -X GET "https://my-fastapi-app-undz.onrender.com/maintenance?status=Active" \
       -H "Authorization: Bearer <YOUR_JWT_TOKEN>"
  ```

* **Response Payload (`200 OK` — Real Backend Schema `MaintenanceModeListResponse`)**:
  ```json
  {
    "total": 3,
    "page": 1,
    "page_size": 20,
    "total_pages": 1,
    "rows": [
      {
        "id": 1,
        "zone_id": 8,
        "zone_code": "NR",
        "zone_name": "NORTHERN RAILWAY",
        "division_id": 32,
        "division_code": "PRYJ",
        "division_name": "PRAYAGRAJ",
        "station_id": 1,
        "station_code": "MJA",
        "station_name": "Meja Road",
        "asset_type_hex": "00",
        "asset_type_name": "Point Machine",
        "asset_no": "PT-04",
        "from_time": "2026-07-03T06:00:00",
        "to_time": "2026-07-03T14:00:00",
        "status": "Active",
        "is_cleared": false,
        "cleared_at": null,
        "created_at": "2026-07-03T05:45:00"
      },
      {
        "id": 2,
        "zone_id": 8,
        "zone_code": "NR",
        "zone_name": "NORTHERN RAILWAY",
        "division_id": 32,
        "division_code": "PRYJ",
        "division_name": "PRAYAGRAJ",
        "station_id": 2,
        "station_code": "GZB",
        "station_name": "Ghaziabad",
        "asset_type_hex": "20",
        "asset_type_name": "Track Circuit",
        "asset_no": "TC-11",
        "from_time": "2026-07-03T02:00:00",
        "to_time": "2026-07-03T05:30:00",
        "status": "Completed",
        "is_cleared": false,
        "cleared_at": null,
        "created_at": "2026-07-03T01:30:00"
      }
    ]
  }
  ```

* **UI Mapping**:
  - `station_code` + `asset_no` $\rightarrow$ Display Title `MJA · PT-04`
  - `from_time` $\rightarrow$ Display `ACTIVATES` date (`03 Jul 06:00`) & timeline start bar (`06:00`)
  - `to_time` $\rightarrow$ Display `CLEARS` date (`03 Jul 14:00`) & timeline end bar (`14:00`)
  - `[ Clear ]` button $\rightarrow$ Triggers `POST /maintenance/{id}/clear`

---

### API 3: Activate / Schedule New Maintenance Mode (`POST /maintenance`)

Schedules or activates a new maintenance window for a physical railway asset.

* **HTTP Method**: `POST`
* **Endpoint**: `/maintenance`
* **Request Body Payload (`MaintenanceModeRequest`)**:
  ```json
  {
    "station_id": 1,
    "asset_no": "PT-04",
    "from_time": "2026-07-03T06:00:00",
    "to_time": "2026-07-03T14:00:00"
  }
  ```

* **cURL Request**:
  ```bash
  curl -X POST "https://my-fastapi-app-undz.onrender.com/maintenance" \
       -H "Authorization: Bearer <YOUR_JWT_TOKEN>" \
       -H "Content-Type: application/json" \
       -d '{
             "station_id": 1,
             "asset_no": "PT-04",
             "from_time": "2026-07-03T06:00:00",
             "to_time": "2026-07-03T14:00:00"
           }'
  ```

---

### API 4: Clear Maintenance Mode Early (`POST /maintenance/{id}/clear`)

Manually clears/terminates an active or scheduled maintenance window before its configured end time.

* **HTTP Method**: `POST`
* **Endpoint**: `/maintenance/{id}/clear`

* **cURL Request**:
  ```bash
  curl -X POST "https://my-fastapi-app-undz.onrender.com/maintenance/1/clear" \
       -H "Authorization: Bearer <YOUR_JWT_TOKEN>"
  ```

* **Response Payload (`200 OK`)**:
  ```json
  {
    "id": 1,
    "station_code": "MJA",
    "asset_no": "PT-04",
    "status": "Completed",
    "is_cleared": true,
    "cleared_at": "2026-07-03T10:15:22"
  }
  ```

---

### API 5: Export Maintenance Records CSV (`GET /maintenance/download`)

Downloads filtered maintenance records as a CSV spreadsheet.

* **HTTP Method**: `GET`
* **Endpoint**: `/maintenance/download`
* **cURL Request**:
  ```bash
  curl -X GET "https://my-fastapi-app-undz.onrender.com/maintenance/download" \
       -H "Authorization: Bearer <YOUR_JWT_TOKEN>" \
       --output maintenance_report.csv
  ```

---

## 3. Flutter / Dart Implementation Code Example

```dart
import 'package:http/http.dart' as http;
import 'dart:convert';

class MaintenanceService {
  final String baseUrl = "https://my-fastapi-app-undz.onrender.com";
  final String token;

  MaintenanceService({required this.token});

  // 1. Fetch Maintenance Records
  Future<List<dynamic>> fetchMaintenanceList({String? status}) async {
    final uri = Uri.parse('$baseUrl/maintenance').replace(
      queryParameters: status != null ? {'status': status} : null,
    );

    final response = await http.get(
      uri,
      headers: {'Authorization': 'Bearer $token'},
    );

    if (response.statusCode == 200) {
      final data = jsonDecode(response.body);
      return data['rows'];
    } else {
      throw Exception('Failed to load maintenance records');
    }
  }

  // 2. Clear Maintenance Mode Early
  Future<bool> clearMaintenanceMode(int id) async {
    final uri = Uri.parse('$baseUrl/maintenance/$id/clear');

    final response = await http.post(
      uri,
      headers: {'Authorization': 'Bearer $token'},
    );

    return response.statusCode == 200;
  }

  // 3. Schedule New Maintenance Mode
  Future<bool> activateMaintenance({
    required int stationId,
    required String assetNo,
    required String fromTimeISO,
    required String toTimeISO,
  }) async {
    final uri = Uri.parse('$baseUrl/maintenance');

    final response = await http.post(
      uri,
      headers: {
        'Authorization': 'Bearer $token',
        'Content-Type': 'application/json',
      },
      body: jsonEncode({
        'station_id': stationId,
        'asset_no': assetNo,
        'from_time': fromTimeISO,
        'to_time': toTimeISO,
      }),
    );

    return response.statusCode == 201;
  }
}
```

---

## 4. Mobile Developer Handoff Checklist

- [x] Query `/alerts/filters` on load to populate Zone, Division, Station, and Asset Type filters.
- [x] Query `GET /maintenance` to populate the 24-hour horizontal timeline bars and the `ACTIVE & SCHEDULED` table list.
- [x] Bind the `[ Clear ]` button in each table row to `POST /maintenance/{id}/clear` to terminate maintenance early.
- [x] Bind the schedule dialog to `POST /maintenance` with `station_id`, `asset_no`, `from_time`, and `to_time`.
- [x] Ensure alerts are suppressed on mobile when an asset is in active maintenance mode.
