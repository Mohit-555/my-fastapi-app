# RDPMS Mobile App — Equipment Room Screen API Integration Guide

This guide provides the complete technical specification for mobile application developers (Flutter, React Native, Swift, Kotlin) integrating the **Equipment Room (Mobile UI)** screen with the RDPMS backend.

---

## 📱 Mobile Screen Mapping Overview

```
┌─────────────────────────────────────────────────────────────┐
│ 9:41                           RDPMS · IR-NET               │
│                                                             │
│ Equipment Room                                              │
│  [Zone ▾]  [Div ▾]  [Stn ▾]   [ Table ] [ Pic ]             │  ◄── 1. Top Filters & View Mode
│ ─────────────────────────────────────────────────────────── │
│ ROOMS · NR / PRYJ ───────────────────────────               │  ◄── 2. Location Indicator
│                                                             │
│ ┌─────────────────────────────────────────────────────────┐ │
│ │ MJA — Relay Room A                             [ OPEN ] │ │  ◄── 3. Equipment Room Cards
│ │ Temp                                            34.2°C  │ │      (Door Status, Temp, Humidity)
│ │ Humidity                                           58%  │ │
│ └─────────────────────────────────────────────────────────┘ │
│ ┌─────────────────────────────────────────────────────────┐ │
│ │ GZB — Equipment Room 2                        [CLOSED]  │ │
│ │ Temp                                            27.8°C  │ │
│ │ Humidity                                           44%  │ │
│ └─────────────────────────────────────────────────────────┘ │
│ ┌─────────────────────────────────────────────────────────┐ │
│ │ DHN — Signal Room                             [CLOSED]  │ │
│ │ Temp                                            29.1°C  │ │
│ │ Humidity                                           49%  │ │
│ └─────────────────────────────────────────────────────────┘ │
│ ─────────────────────────────────────────────────────────── │
│   [DASHBOARD]   [ALERT]   [TELEMETRY]   [HEALTH]  [EQUIP]   │  ◄── 4. Bottom Navigation (Equip Active)
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

## 2. API Specifications for Equipment Room

### API 1: Fetch Top Filter Dropdown Options

Populate `Zone ▾`, `Div ▾`, and `Stn ▾` filter dropdowns.

* **HTTP Method**: `GET`
* **Endpoint**: `/alerts/filters`
* **cURL Request**:
  ```bash
  curl -X GET "https://my-fastapi-app-undz.onrender.com/alerts/filters" \
       -H "Authorization: Bearer <YOUR_JWT_TOKEN>"
  ```

---

### API 2: Fetch Live Equipment Rooms List (Main Endpoint)

Fetches real-time environmental telemetry (Temperature & Humidity) and door access security status (`OPEN` / `CLOSED`) for all equipment rooms.

* **HTTP Method**: `GET`
* **Endpoint**: `/equipment-room/live`
* **Query Parameters (Optional Filters)**:
  * `zone_id` (integer)
  * `division_id` (integer)
  * `station_id` (integer)
  * `room_type` (string: `RR` for Relay Room, `IPS` for Power Room, `BATT` for Battery Room)

* **cURL Request**:
  ```bash
  curl -X GET "https://my-fastapi-app-undz.onrender.com/equipment-room/live?station_id=23" \
       -H "Authorization: Bearer <YOUR_JWT_TOKEN>"
  ```

* **Response Payload (`200 OK` — Real Backend Schema `EquipmentRoomResponse`)**:
  ```json
  [
    {
      "id": 1,
      "station_id": 23,
      "zone_id": 1,
      "zone_code": "NR",
      "zone_name": "Northern Railway",
      "division_id": 5,
      "division_code": "PRYJ",
      "division_name": "Prayagraj",
      "station_code": "MJA",
      "station_name": "Meja Road",
      "room_type": "Relay Room A",
      "temperature": 34.2,
      "humidity": 58.0,
      "door_status": "OPEN",
      "updated_at": "2026-08-18T18:00:00Z"
    },
    {
      "id": 2,
      "station_id": 24,
      "zone_id": 1,
      "zone_code": "NR",
      "zone_name": "Northern Railway",
      "division_id": 5,
      "division_code": "PRYJ",
      "division_name": "Prayagraj",
      "station_code": "GZB",
      "station_name": "Ghaziabad",
      "room_type": "Equipment Room 2",
      "temperature": 27.8,
      "humidity": 44.0,
      "door_status": "CLOSED",
      "updated_at": "2026-08-18T18:00:00Z"
    },
    {
      "id": 3,
      "station_id": 25,
      "zone_id": 1,
      "zone_code": "NR",
      "zone_name": "Northern Railway",
      "division_id": 5,
      "division_code": "PRYJ",
      "division_name": "Prayagraj",
      "station_code": "DHN",
      "station_name": "Dhanbad",
      "room_type": "Signal Room",
      "temperature": 29.1,
      "humidity": 49.0,
      "door_status": "CLOSED",
      "updated_at": "2026-08-18T18:00:00Z"
    }
  ]
  ```

---

## 3. UI Component Data Mapping Guide

| Mobile UI Component | JSON Field Path | Rendering / Badge Styling |
| :--- | :--- | :--- |
| **Card Header Title** | `${station_code} — ${room_type}` | Render as string e.g. `MJA — Relay Room A` |
| **Door Lock Badge** | `door_status` | **`"OPEN"`** $\rightarrow$ Red Pill Badge (`#E53935`)<br>**`"CLOSED"`** $\rightarrow$ Green Pill Badge (`#4CAF50`) |
| **Temp Value** | `temperature` | Formatted float: `${temperature}°C` (e.g. `34.2°C`) |
| **Humidity Value** | `humidity` | Formatted float: `${humidity}%` (e.g. `58%`) |
| **Location Sub-Header** | `ROOMS · ${zone_code} / ${division_code}` | e.g. `ROOMS · NR / PRYJ` |
| **View Toggle Switch** | Local App State (`"Table"` vs `"Pic"`) | Swaps between List Card view and Spatial Layout picture view |

---

## 4. Flutter / Dart Mobile Implementation Example

```dart
import 'package:http/http.dart' as http;
import 'dart:convert';

class EquipmentRoomService {
  final String baseUrl = "https://my-fastapi-app-undz.onrender.com";
  final String token;

  EquipmentRoomService({required this.token});

  // Fetch Live Equipment Rooms Data
  Future<List<dynamic>> fetchEquipmentRooms({int? stationId, String? roomType}) async {
    final queryParams = <String, String>{};
    if (stationId != null) queryParams['station_id'] = stationId.toString();
    if (roomType != null) queryParams['room_type'] = roomType;

    final uri = Uri.parse('$baseUrl/equipment-room/live').replace(queryParameters: queryParams);

    final response = await http.get(
      uri,
      headers: {
        'Authorization': 'Bearer $token',
        'Content-Type': 'application/json',
      },
    );

    if (response.statusCode == 200) {
      return jsonDecode(response.body);
    } else {
      throw Exception('Failed to load equipment room data');
    }
  }
}
```

---

## 5. Mobile Developer Checklist

- [x] On screen mount, call `GET /equipment-room/live` to populate equipment room cards.
- [x] Format `temperature` with `°C` and `humidity` with `%`.
- [x] Apply red badge styling for `door_status == "OPEN"` and green badge styling for `door_status == "CLOSED"`.
- [x] Support filter dropdown changes (`Zone`, `Div`, `Stn`) by appending query parameters `?zone_id=X&division_id=Y&station_id=Z`.
- [x] Toggle between Card List (`Table`) and Picture View (`Pic`) using local state.
