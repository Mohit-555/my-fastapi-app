# RDPMS Mobile App — Telemetry Live Screen API Integration Guide

This guide provides the complete technical specification for mobile application developers (Flutter, React Native, Swift, Kotlin) integrating the **Telemetry Live (03 · TELEMETRY LIVE)** screen with the RDPMS backend.

---

## 📱 Mobile Screen Mapping Overview

```
┌─────────────────────────────────────────────────────────────┐
│ 9:41                           RDPMS · IR-NET               │
│                                                             │
│ Telemetry Live                                              │
│  [Zone ▾]  [Div ▾]  [Stn ▾]  [Asset type ▾] [Asset No ▾]    │  ◄── 1. Top Filter Pills Bar
│ ─────────────────────────────────────────────────────────── │
│ ASSET SUMMARY CARD ──────────────────────────────────────   │
│ ┌─────────────────────────────────────────────────────────┐ │
│ │ PRYG · PT-101                                           │ │  ◄── 2. Asset Header
│ │ Point machine - last sync 4s ago                        │ │
│ │                                                         │ │
│ │  [ Failure ]   [ Predictive ]   [ Healthy ]             │ │  ◄── 3. Asset Status Pills
│ └─────────────────────────────────────────────────────────┘ │      (e.g., Healthy active)
│ ─────────────────────────────────────────────────────────── │
│ LIVE PARAMETERS ──────────────────────────────────────────  │
│ ┌─────────────────────────────────────────────────────────┐ │
│ │ PARAM        VALUE      RANGE        TREND              │ │  ◄── 4. Live Parameters Table
│ │ Current      4.6 A      3.8–5.2      stable             │ │
│ │ Voltage      110 V      105–115      stable             │ │
│ │ Throw time   4.1 s      <4.5         rising             │ │
│ │ Force        2.9 kN     2.5–3.5      stable             │ │
│ └─────────────────────────────────────────────────────────┘ │
│ ─────────────────────────────────────────────────────────── │
│ THROW TIME · LAST 12 CYCLES ─────────────────────────────   │  ◄── 5. Historical Cycle Chart
│ ┌─────────────────────────────────────────────────────────┐ │      (Threshold 4.5s)
│ │ SECONDS                             THRESHOLD 4.5S      │ │
│ │ [ 3.8s, 3.9s, 4.0s, 3.9s, 4.1s ... 4.1s ]               │ │
│ └─────────────────────────────────────────────────────────┘ │
│ ─────────────────────────────────────────────────────────── │
│   [DASHBOARD]   [ALERT]   [TELEMETRY]   [HEALTH]  [EQUIP]   │  ◄── 6. Bottom Navigation (Telemetry Active)
└─────────────────────────────────────────────────────────────┘
```

---

## 1. Authentication & Base URL

* **Production Base URL**: `https://my-fastapi-app-undz.onrender.com`
* **Production WebSocket/SSE Stream URL**: `https://my-fastapi-app-undz.onrender.com`
* **Authorization Header Required**:
  ```http
  Authorization: Bearer <JWT_TOKEN>
  Content-Type: application/json
  ```

---

## 2. API Specifications for Telemetry Live

### API 1: Top Horizontal Filter Bar (`Zone`, `Div`, `Stn`, `Asset type`, `Asset No`)

Populate filter options on page mount.

* **HTTP Method**: `GET`
* **Endpoint**: `/alerts/filters`
* **cURL Request**:
  ```bash
  curl -X GET "https://my-fastapi-app-undz.onrender.com/alerts/filters" \
       -H "Authorization: Bearer <YOUR_JWT_TOKEN>"
  ```

---

### API 2: Telemetry Live Card Data (Asset Meta, Parameters Table & 12 Cycles Chart)

Fetches the live parameters status, range thresholds, trends, and throw time historical cycles for the active asset card.

* **HTTP Method**: `GET`
* **Endpoint**: `/telemetry/live-card`
* **Query Parameters**:
  * `station_code` (string, e.g., `"PRYG"`)
  * `asset_number` (string, e.g., `"PT-101"`)

* **cURL Request**:
  ```bash
  curl -X GET "https://my-fastapi-app-undz.onrender.com/telemetry/live-card?station_code=PRYG&asset_number=PT-101" \
       -H "Authorization: Bearer <YOUR_JWT_TOKEN>"
  ```

* **Response Payload (`200 OK` — Real Backend Schema `TelemetryLiveCardResponse`)**:
  ```json
  {
    "station_code": "PRYG",
    "asset_number": "PT-101",
    "asset_type_name": "Point machine",
    "last_sync": "4s ago",
    "asset_status": "Healthy",
    "parameters": [
      {
        "param": "Current",
        "value": "4.6 A",
        "range": "3.8–5.2",
        "trend": "stable"
      },
      {
        "param": "Voltage",
        "value": "110 V",
        "range": "105–115",
        "trend": "stable"
      },
      {
        "param": "Throw time",
        "value": "4.1 s",
        "range": "<4.5",
        "trend": "rising"
      },
      {
        "param": "Force",
        "value": "2.9 kN",
        "range": "2.5–3.5",
        "trend": "stable"
      }
    ],
    "throw_time_cycles": [
      { "cycle": 1, "seconds": 3.8 },
      { "cycle": 2, "seconds": 3.9 },
      { "cycle": 3, "seconds": 4.0 },
      { "cycle": 4, "seconds": 3.9 },
      { "cycle": 5, "seconds": 4.1 },
      { "cycle": 6, "seconds": 4.0 },
      { "cycle": 7, "seconds": 4.2 },
      { "cycle": 8, "seconds": 4.1 },
      { "cycle": 9, "seconds": 4.3 },
      { "cycle": 10, "seconds": 4.1 },
      { "cycle": 11, "seconds": 4.2 },
      { "cycle": 12, "seconds": 4.1 }
    ],
    "threshold_seconds": 4.5
  }
  ```

* **UI Mapping**:
  - `station_code` + `asset_number` $\rightarrow$ Title Header `PRYG · PT-101`
  - `asset_type_name` + `last_sync` $\rightarrow$ Subtitle `Point machine - last sync 4s ago`
  - `asset_status` $\rightarrow$ Highlight active status pill (`Healthy` in Green)
  - `parameters[]` $\rightarrow$ Populate **LIVE PARAMETERS** table (Param, Value, Range, Trend)
  - `throw_time_cycles[]` $\rightarrow$ Render 12-cycle bar/line chart with `threshold_seconds` line (`THRESHOLD 4.5S`)

---

### API 3: Server-Sent Events (SSE) Live Telemetry Stream

Connect to SSE endpoint for continuous real-time parameter stream without polling HTTP GET repeatedly.

* **HTTP Method**: `GET`
* **Endpoint**: `/telemetry/live`
* **Query Parameters**:
  * `station_id` (integer, e.g. `1`)
  * `asset_number` (string, e.g. `"PT-101"`)
  * `poll_interval` (integer, default `5` seconds)

* **cURL Stream Test**:
  ```bash
  curl -N -X GET "https://my-fastapi-app-undz.onrender.com/telemetry/live?station_id=1&asset_number=PT-101&poll_interval=5" \
       -H "Authorization: Bearer <YOUR_JWT_TOKEN>"
  ```

* **Incoming Event Payload Example**:
  ```json
  data: {
    "para_id": "00010101",
    "stngw_id": "02011200",
    "asset_type_name": "Point machine",
    "parameter_name": "Average Current",
    "parameter_unit": "A",
    "points": [
      { "t": "2026-08-19T08:44:00Z", "v": 4.6 }
    ],
    "threshold_warning_high": 5.2,
    "threshold_critical_high": 6.5
  }
  ```

---

## 3. Flutter / Dart Mobile Implementation Code Example

```dart
import 'package:http/http.dart' as http;
import 'dart:convert';

class TelemetryLiveService {
  final String baseUrl = "https://my-fastapi-app-undz.onrender.com";
  final String token;

  TelemetryLiveService({required this.token});

  // 1. Fetch Telemetry Live Card Details
  Future<Map<String, dynamic>> fetchTelemetryLiveCard({
    required String stationCode,
    required String assetNumber,
  }) async {
    final uri = Uri.parse('$baseUrl/telemetry/live-card')
        .replace(queryParameters: {
      'station_code': stationCode,
      'asset_number': assetNumber,
    });

    final response = await http.get(
      uri,
      headers: {'Authorization': 'Bearer $token'},
    );

    if (response.statusCode == 200) {
      return jsonDecode(response.body);
    } else {
      throw Exception('Failed to load telemetry live card');
    }
  }
}
```

---

## 4. Mobile Developer Handoff Checklist

- [x] On screen mount, query `/alerts/filters` to populate top location and asset dropdowns.
- [x] Query `GET /telemetry/live-card` to fetch live parameter metrics, status pill indicator, and 12-cycle throw time chart data.
- [x] Render `LIVE PARAMETERS` table with `Current`, `Voltage`, `Throw time`, `Force` along with `value`, `range`, and `trend`.
- [x] Render historical cycle chart with critical threshold indicator line (`THRESHOLD 4.5S`).
- [x] Connect optional SSE stream `GET /telemetry/live` for real-time live telemetry stream updates.
