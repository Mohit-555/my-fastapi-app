# RDPMS Mobile App — Alert Live Screen API Integration Guide

This guide provides the complete technical specification for mobile application developers (Flutter, React Native, Swift, Kotlin) integrating the **Alert Live (Mobile UI)** screen with the RDPMS backend.

---

## 📱 Mobile Screen Mapping Overview

```
┌─────────────────────────────────────────────────────────────┐
│ 9:41                           RDPMS · IR-NET               │
│                                                             │
│  [Zone ▾]  [Div ▾]  [Stn ▾]  [Alert type ▾]                 │  ◄── 1. Filter Dropdowns
│ ─────────────────────────────────────────────────────────── │
│  ┌────────────┐   ┌────────────┐   ┌────────────┐           │
│  │     50     │   │     10     │   │     5      │           │  ◄── 2. KPI Summary Counters
│  │   NORMAL   │   │ PREDICTIVE │   │  FAILURE   │           │
│  └────────────┘   └────────────┘   └────────────┘           │
│ ─────────────────────────────────────────────────────────── │
│  FEED ───────────────────────────────────────────────────   │
│  ┌───────────────────────────────────────────────────────┐  │
│  │ PRYG · AST-04812                         [ FAILURE ]  │  │
│  │ 02-12-2022 · 19:34                                    │  │  ◄── 3. Live Alert Cards
│  │ Cause code: over-current on track relay circuit       │  │      (HTTP Initial + WS Stream)
│  │ [Ack] [ T ] [ PT ] [ F ] [ M ]       [ Remark → ]     │  │  ◄── 4. Card Action Buttons
│  └───────────────────────────────────────────────────────┘  │
│ ─────────────────────────────────────────────────────────── │
│   [DASHBOARD]   [ALERT]   [TELEMETRY]   [HEALTH]  [EQUIP]   │  ◄── 5. Bottom Navigation
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

## 2. Component API Specifications

### Component 1: Top Horizontal Filter Bar (`Zone`, `Div`, `Stn`, `Alert type`)

Populate all mobile filter pill dropdowns using a single global filter call on page mount.

* **HTTP Method**: `GET`
* **Endpoint**: `/alerts/filters`
* **cURL Request**:
  ```bash
  curl -X GET "https://my-fastapi-app-undz.onrender.com/alerts/filters" \
       -H "Authorization: Bearer <YOUR_JWT_TOKEN>"
  ```
* **Response Payload (`200 OK`)**:
  ```json
  {
    "zones": [
      { "id": 1, "label": "Northern Railway", "code": "NR", "value": "NR" }
    ],
    "divisions": [
      { "id": 5, "label": "Lucknow", "code": "LKO", "value": "LKO", "zone_id": 1 }
    ],
    "stations": [
      { "id": 23, "label": "Lucknow Charbagh", "code": "LKO", "value": "LKO", "division_id": 5 }
    ],
    "alert_types": [
      { "id": 1, "label": "All", "value": "ALL" },
      { "id": 2, "label": "Predictive", "value": "Predictive" },
      { "id": 3, "label": "Failure", "value": "Failure" }
    ],
    "card_types": [
      { "id": 1, "label": "Voltage", "value": "Voltage" },
      { "id": 2, "label": "Analog", "value": "Analog" },
      { "id": 3, "label": "DI", "value": "DI" }
    ]
  }
  ```

---

### Component 2: KPI Summary Counters (`NORMAL`, `PREDICTIVE`, `FAILURE`)

Fetch live counters for the top summary cards.

* **HTTP Method**: `GET`
* **Endpoint**: `/alerts/live`
* **Query Parameters (Optional Filters)**:
  * `zone_id` (int)
  * `division_id` (int)
  * `station_id` (int)
  * `alert_type` (string: `Predictive` | `Failure` | `ALL`)
* **cURL Request**:
  ```bash
  curl -X GET "https://my-fastapi-app-undz.onrender.com/alerts/live?station_id=23" \
       -H "Authorization: Bearer <YOUR_JWT_TOKEN>"
  ```
* **Response Payload (`200 OK`)**:
  ```json
  {
    "summary": {
      "normal": 50,
      "predictive": 10,
      "failure": 5,
      "total": 65
    },
    "alerts": [ ... ]
  }
  ```
* **UI Mapping**:
  - `summary.normal` $\rightarrow$ Green **NORMAL** Box (`50`)
  - `summary.predictive` $\rightarrow$ Yellow **PREDICTIVE** Box (`10`)
  - `summary.failure` $\rightarrow$ Red **FAILURE** Box (`5`)

---

### Component 3: Live Feed Cards List (Initial Load)

* **HTTP Method**: `GET`
* **Endpoint**: `/alerts/live`
* **Response Payload (`200 OK`)**:
  ```json
  {
    "alerts": [
      {
        "id": 4812,
        "station_name": "PRYG",
        "asset_code": "AST-04812",
        "alert_type": "Failure",
        "alert_status": "Active",
        "time": "02-12-2022 · 19:34",
        "cause": "over-current on track relay circuit",
        "feedback": null,
        "remark": null
      },
      {
        "id": 3310,
        "station_name": "PRYG",
        "asset_code": "AST-03310",
        "alert_type": "Predictive",
        "alert_status": "Active",
        "time": "02-12-2023 · 18:36",
        "cause": "vibration trend exceeding baseline",
        "feedback": null,
        "remark": null
      }
    ]
  }
  ```

---

### Component 4: Real-Time WebSockets Feed (Live Streaming)

Connect to the WebSocket endpoint to receive live updates in real time without polling HTTP GET requests.

* **WebSocket URL**: `wss://my-fastapi-app-undz.onrender.com/ws/alerts/{station_code}?alert_type=all`
* **URL Example**: `wss://my-fastapi-app-undz.onrender.com/ws/alerts/PRYG?alert_type=all`

#### WebSocket Incoming Message Types:
1. **Initial State (On Connect)**:
   ```json
   {
     "type": "pending_alerts",
     "data": [
       {
         "id": 4812,
         "alert_type": "Failure",
         "asset_no": "AST-04812",
         "cause": "over-current on track relay circuit",
         "time": "2022-12-02T19:34:00Z",
         "acknowledged": false
       }
     ]
   }
   ```
2. **Live Alert Event (Pushed when hardware fails)**:
   ```json
   {
     "type": "alert_update",
     "data": {
       "id": 5100,
       "station_name": "MJA",
       "asset_code": "AST-01147",
       "alert_type": "Failure",
       "alert_status": "Active",
       "time": "03-12-2023 · 07:12",
       "cause": "LC gate motor timeout"
     }
   }
   ```

---

### Component 5: Card Interactive Action Buttons (`Ack`, `T`, `PT`, `F`, `M`, `Remark`)

#### Action 1: `Ack` (Acknowledge Alert)
Changes card status badge from **Active** to **Acknowledged**.

* **HTTP Method**: `POST`
* **Endpoint**: `/alerts/events/{event_id}/acknowledge`
* **cURL Request**:
  ```bash
  curl -X POST "https://my-fastapi-app-undz.onrender.com/alerts/events/4812/acknowledge" \
       -H "Authorization: Bearer <YOUR_JWT_TOKEN>"
  ```
* **Response Payload (`200 OK`)**:
  ```json
  {
    "id": 4812,
    "acknowledged": true,
    "alert_status": "Acknowledged"
  }
  ```

---

#### Action 2: `T`, `PT`, `F`, `M` (Feedback Buttons)
Submits maintenance feedback and clears the alert card.
* **Buttons**:
  * `T` = True Positive Alert
  * `PT` = Partially True Alert
  * `F` = False Alarm
  * `M` = Maintenance / Testing

* **HTTP Method**: `POST`
* **Endpoint**: `/alerts/events/{event_id}/feedback`
* **Request Body**:
  ```json
  {
    "feedback": "T"
  }
  ```
* **cURL Request**:
  ```bash
  curl -X POST "https://my-fastapi-app-undz.onrender.com/alerts/events/4812/feedback" \
       -H "Authorization: Bearer <YOUR_JWT_TOKEN>" \
       -H "Content-Type: application/json" \
       -d '{"feedback": "T"}'
  ```

---

#### Action 3: `Remark →` (Submit Remark / Notes)
Opens a modal or bottom sheet in the mobile app for custom text notes.

* **HTTP Method**: `POST`
* **Endpoint**: `/alerts/events/{event_id}/remark`
* **Request Body**:
  ```json
  {
    "remark": "Found stone chip in point machine obstacle point"
  }
  ```
* **cURL Request**:
  ```bash
  curl -X POST "https://my-fastapi-app-undz.onrender.com/alerts/events/4812/remark" \
       -H "Authorization: Bearer <YOUR_JWT_TOKEN>" \
       -H "Content-Type: application/json" \
       -d '{"remark": "Found stone chip in point machine obstacle point"}'
  ```

---

### Component 6: Bottom Navigation Tab Endpoints

| Tab Icon | Feature Name | Primary Endpoint | WebSocket Endpoint |
| :---: | :--- | :--- | :--- |
| 🔲 **DASHBOARD** | Station Dashboard | `GET /api/realtime/dashboard/{station_code}` | N/A |
| 🔔 **ALERT** | Alert Live Screen *(Current)* | `GET /alerts/live`<br>`GET /alerts/filters` | `wss://.../ws/alerts/{station_code}` |
| 📈 **TELEMETRY** | Live Sensor Waveforms | `GET /api/realtime/telemetry/{station_code}` | `wss://.../ws/telemetry/{station_code}` |
| ❇️ **HEALTH** | System & Sensor Health | `GET /api/realtime/dashboard/{station_code}` | `wss://.../ws/health/{station_code}` |
| 🧰 **EQUIPMENT** | Hardware Configuration | `GET /gateway/list`<br>`GET /slave-cards` | N/A |

---

## 3. Flutter / Dart Mobile Code Example

```dart
import 'package:http/http.dart' as http;
import 'package:web_socket_channel/web_socket_channel.dart';
import 'dart:convert';

class AlertLiveService {
  final String baseUrl = "https://my-fastapi-app-undz.onrender.com";
  final String token;

  AlertLiveService({required this.token});

  // 1. Fetch Top Filter Options
  Future<Map<String, dynamic>> fetchFilters() async {
    final response = await http.get(
      Uri.parse('$baseUrl/alerts/filters'),
      headers: {'Authorization': 'Bearer $token'},
    );
    return jsonDecode(response.body);
  }

  // 2. Fetch Initial Live Cards & Counters
  Future<Map<String, dynamic>> fetchAlertLive() async {
    final response = await http.get(
      Uri.parse('$baseUrl/alerts/live'),
      headers: {'Authorization': 'Bearer $token'},
    );
    return jsonDecode(response.body);
  }

  // 3. Acknowledge Alert
  Future<bool> acknowledgeAlert(int alertId) async {
    final response = await http.post(
      Uri.parse('$baseUrl/alerts/events/$alertId/acknowledge'),
      headers: {'Authorization': 'Bearer $token'},
    );
    return response.statusCode == 200;
  }

  // 4. Submit Feedback (T, PT, F, M)
  Future<bool> submitFeedback(int alertId, String feedback) async {
    final response = await http.post(
      Uri.parse('$baseUrl/alerts/events/$alertId/feedback'),
      headers: {
        'Authorization': 'Bearer $token',
        'Content-Type': 'application/json',
      },
      body: jsonEncode({'feedback': feedback}),
    );
    return response.statusCode == 200;
  }

  // 5. Connect WebSocket Live Stream
  WebSocketChannel connectLiveAlertStream(String stationCode) {
    return WebSocketChannel.connect(
      Uri.parse('wss://my-fastapi-app-undz.onrender.com/ws/alerts/$stationCode?alert_type=all'),
    );
  }
}
```

---

## 4. Summary Checklist for Mobile Developer

- [x] Use `GET /alerts/filters` once on screen launch to populate top filter pills (`Zone`, `Div`, `Stn`, `Alert type`).
- [x] Use `GET /alerts/live` for initial load of KPI counters (`NORMAL`, `PREDICTIVE`, `FAILURE`) and alert cards list.
- [x] Connect `wss://.../ws/alerts/{station_code}` WebSocket for real-time live alert stream.
- [x] Bind `Ack` button to `POST /alerts/events/{id}/acknowledge`.
- [x] Bind `T`, `PT`, `F`, `M` buttons to `POST /alerts/events/{id}/feedback`.
- [x] Bind `Remark →` button to `POST /alerts/events/{id}/remark`.
