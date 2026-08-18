# RDPMS Mobile App — RDPMS Health Screen API Integration Guide

This guide provides the complete technical specification for mobile application developers (Flutter, React Native, Swift, Kotlin) integrating the **RDPMS Health (Mobile UI)** screen with the RDPMS backend.

---

## 📱 Mobile Screen Mapping Overview

```
┌─────────────────────────────────────────────────────────────┐
│ 9:41                           RDPMS · IR-NET               │
│                                                             │
│ RDPMS Health                                                │
│  [Zone ▾]  [Div ▾]  [Stn ▾]  [Asset type ▾]                 │  ◄── 1. Top Filter Pills Bar
│ ─────────────────────────────────────────────────────────── │
│ SYSTEM TOTALS · NR / PRYJ ──────────────────────────        │  ◄── 2. Location Indicator
│                                                             │
│ ┌──────────────────────────┐   ┌──────────────────────────┐ │
│ │ SENSORS                  │   │ IOT DEVICES              │ │
│ │ 500                 ▲ 20 │   │ 50                  ▲ 2  │ │  ◄── 3. System Totals KPI Grid
│ └──────────────────────────┘   └──────────────────────────┘ │      (4 Summary Cards)
│ ┌──────────────────────────┐   ┌──────────────────────────┐ │
│ │ NETWORK                  │   │ STATION GATEWAY          │ │
│ │ 50                  ▲ 2  │   │ 2                   ▲ 1  │ │
│ └──────────────────────────┘   └──────────────────────────┘ │
│ ─────────────────────────────────────────────────────────── │
│ FAULTY BY STATION ───────────────────────────────────────── │
│ ┌─────────────────────────────────────────────────────────┐ │
│ │ STN / ASSET      SENSOR        IOT          NET / GW    │ │  ◄── 4. Faulty By Station List
│ │ MJA · PT-04        2            1            0 / 0      │ │
│ │ GZB · TC-11        0            1            1 / 0      │ │
│ │ DHN · SIG-02       3            0            0 / 1      │ │
│ └─────────────────────────────────────────────────────────┘ │
│ ─────────────────────────────────────────────────────────── │
│   [DASHBOARD]   [ALERT]   [TELEMETRY]   [HEALTH]  [EQUIP]   │  ◄── 5. Bottom Navigation (Health Active)
└─────────────────────────────────────────────────────────────┘
```

---

## 1. Authentication & Base URL

* **Production Base URL**: `https://my-fastapi-app-undz.onrender.com`
* **Production WebSocket URL**: `wss://my-fastapi-app-undz.onrender.com`
* **Authorization Header Required**:
  ```http
  Authorization: Bearer <JWT_TOKEN>
  Content-Type: application/json
  ```

---

## 2. API Specifications for RDPMS Health

### API 1: Top Horizontal Filter Bar (`Zone`, `Div`, `Stn`, `Asset type`)

Populate filter pills on page mount.

* **HTTP Method**: `GET`
* **Endpoint**: `/alerts/filters`
* **cURL Request**:
  ```bash
  curl -X GET "https://my-fastapi-app-undz.onrender.com/alerts/filters" \
       -H "Authorization: Bearer <YOUR_JWT_TOKEN>"
  ```

---

### API 2: System Totals KPI Grid (`SENSORS`, `IOT DEVICES`, `NETWORK`, `STATION GATEWAY`)

Fetches total counts and faulty delta counts for the 4 summary KPI cards.

* **HTTP Method**: `GET`
* **Endpoint**: `/api/monitoring/health/totals`
* **Query Parameters (Optional Filters)**:
  * `zone_id` (integer)
  * `division_id` (integer)
  * `station_id` (integer)
  * `asset_type` (string)

* **cURL Request**:
  ```bash
  curl -X GET "https://my-fastapi-app-undz.onrender.com/api/monitoring/health/totals?division_id=5" \
       -H "Authorization: Bearer <YOUR_JWT_TOKEN>"
  ```

* **Response Payload (`200 OK` — Real Backend Schema `SystemHealthTotalsResponse`)**:
  ```json
  {
    "sensors": {
      "total": 500,
      "faulty": 20
    },
    "iot_devices": {
      "total": 50,
      "faulty": 2
    },
    "network": {
      "total": 50,
      "faulty": 2
    },
    "station_gateway": {
      "total": 2,
      "faulty": 1
    }
  }
  ```

* **UI Mapping**:
  - `sensors.total` $\rightarrow$ `500` | `sensors.faulty` $\rightarrow$ `▲ 20` (Red Delta)
  - `iot_devices.total` $\rightarrow$ `50` | `iot_devices.faulty` $\rightarrow$ `▲ 2` (Red Delta)
  - `network.total` $\rightarrow$ `50` | `network.faulty` $\rightarrow$ `▲ 2` (Red Delta)
  - `station_gateway.total` $\rightarrow$ `2` | `station_gateway.faulty` $\rightarrow$ `▲ 1` (Red Delta)

---

### API 3: Faulty By Station Table / List

Fetches the breakdown of faulty hardware grouped by station and asset.

* **HTTP Method**: `GET`
* **Endpoint**: `/api/monitoring/health/faulty-by-station`
* **Query Parameters (Optional Filters)**:
  * `zone_id` (integer)
  * `division_id` (integer)
  * `station_id` (integer)
  * `asset_type` (string)

* **cURL Request**:
  ```bash
  curl -X GET "https://my-fastapi-app-undz.onrender.com/api/monitoring/health/faulty-by-station" \
       -H "Authorization: Bearer <YOUR_JWT_TOKEN>"
  ```

* **Response Payload (`200 OK` — Real Backend Schema `FaultyByStationResponse`)**:
  ```json
  {
    "total": 3,
    "rows": [
      {
        "station_code": "MJA",
        "asset_code": "PT-04",
        "sensor_faulty": 2,
        "iot_faulty": 1,
        "net_faulty": 0,
        "gw_faulty": 0
      },
      {
        "station_code": "GZB",
        "asset_code": "TC-11",
        "sensor_faulty": 0,
        "iot_faulty": 1,
        "net_faulty": 1,
        "gw_faulty": 0
      },
      {
        "station_code": "DHN",
        "asset_code": "SIG-02",
        "sensor_faulty": 3,
        "iot_faulty": 0,
        "net_faulty": 0,
        "gw_faulty": 1
      }
    ]
  }
  ```

* **UI Table Mapping**:
  - Column 1 (`STN / ASSET`) $\rightarrow$ `${station_code} · ${asset_code}` (e.g. `MJA · PT-04`)
  - Column 2 (`SENSOR`) $\rightarrow$ `sensor_faulty` (e.g. `2`)
  - Column 3 (`IOT`) $\rightarrow$ `iot_faulty` (e.g. `1`)
  - Column 4 (`NET / GW`) $\rightarrow$ `${net_faulty} / ${gw_faulty}` (e.g. `0 / 0`)

---

### API 4: Real-Time WebSockets Health Stream

Connect to WebSocket endpoint to receive live streaming health updates when sensor/gateway faults occur.

* **WebSocket URL**: `wss://my-fastapi-app-undz.onrender.com/ws/health/{station_code}`
* **URL Example**: `wss://my-fastapi-app-undz.onrender.com/ws/health/MJA`

#### WebSocket Incoming Message Example:
```json
{
  "type": "initial_health",
  "data": {
    "station_code": "MJA",
    "timestamp": "2026-08-18T18:15:00Z",
    "gateway": { "status": "healthy" },
    "sensors": { "total": 12, "healthy": 10, "faulty": 2 },
    "iot": { "total": 4, "healthy": 3, "faulty": 1 }
  }
}
```

---

## 3. Flutter / Dart Mobile Code Example

```dart
import 'package:http/http.dart' as http;
import 'package:web_socket_channel/web_socket_channel.dart';
import 'dart:convert';

class HealthService {
  final String baseUrl = "https://my-fastapi-app-undz.onrender.com";
  final String token;

  HealthService({required this.token});

  // 1. Fetch System Health Totals
  Future<Map<String, dynamic>> fetchHealthTotals({int? divisionId}) async {
    final uri = Uri.parse('$baseUrl/api/monitoring/health/totals')
        .replace(queryParameters: divisionId != null ? {'division_id': divisionId.toString()} : null);

    final response = await http.get(
      uri,
      headers: {'Authorization': 'Bearer $token'},
    );
    return jsonDecode(response.body);
  }

  // 2. Fetch Faulty Devices by Station Table
  Future<Map<String, dynamic>> fetchFaultyByStation() async {
    final response = await http.get(
      Uri.parse('$baseUrl/api/monitoring/health/faulty-by-station'),
      headers: {'Authorization': 'Bearer $token'},
    );
    return jsonDecode(response.body);
  }

  // 3. Connect Live Health WebSocket Stream
  WebSocketChannel connectHealthStream(String stationCode) {
    return WebSocketChannel.connect(
      Uri.parse('wss://my-fastapi-app-undz.onrender.com/ws/health/$stationCode'),
    );
  }
}
```

---

## 4. Mobile Developer Summary Checklist

- [x] Call `GET /alerts/filters` once on screen launch to populate top filter pills (`Zone`, `Div`, `Stn`, `Asset type`).
- [x] Call `GET /api/monitoring/health/totals` to populate the 4 summary cards (`SENSORS`, `IOT DEVICES`, `NETWORK`, `STATION GATEWAY`).
- [x] Call `GET /api/monitoring/health/faulty-by-station` to render the table list of faulty hardware.
- [x] Optionally connect `wss://.../ws/health/{station_code}` for real-time live health streaming.
