# RDPMS Mobile App — Main Dashboard Screen API Integration Guide

This guide provides the complete technical specification for mobile application developers (Flutter, React Native, Swift, Kotlin) integrating the **Main Dashboard (02 — DASHBOARD)** screen with the RDPMS backend.

---

## 📱 Mobile Screen Mapping Overview

```
┌─────────────────────────────────────────────────────────────┐
│ 9:41                           RDPMS · IR-NET               │
│                                                             │
│ Dashboard                                                   │
│ NR · PRYJ · MJA                                             │  ◄── 1. Active Location Subtitle
│  [Zone: NR ▾]  [Division ▾]  [Station ▾]  [Others ▾]        │  ◄── 2. Top Location Filter Pills
│ ─────────────────────────────────────────────────────────── │
│ LIVE ALERTS ──────────────────────────────────────────────  │
│ ┌──────────────────────┐      ┌──────────────────────┐      │
│ │  🔴 Alert History    │      │  🟢 Alert Live       │      │  ◄── 3. Shortcut Navigation Cards
│ └──────────────────────┘      └──────────────────────┘      │
│ ─────────────────────────────────────────────────────────── │
│ ASSETS BY CATEGORY ───────────────────────────────────────  │
│ ┌──────────────────────┐      ┌──────────────────────┐      │
│ │ PT — M/C             │      │ Track Circuit        │      │  ◄── 4. 2-Column Asset Category Grid Cards
│ │  🟢 Normal       50  │      │  🟢 Normal       40  │      │      (Normal, Failed, Predicted)
│ │  🔴 Failed        5  │      │  🔴 Failed        4  │      │
│ │  🟡 Predicted    10  │      │  🟡 Predicted     7  │      │
│ └──────────────────────┘      └──────────────────────┘      │
│ ┌──────────────────────┐      ┌──────────────────────┐      │
│ │ Signal               │      │ Axle Counter         │      │
│ │  🟢 Normal       45  │      │  🟢 Normal       55  │      │
│ │  🔴 Failed        6  │      │  🔴 Failed        8  │      │
│ │  🟡 Predicted    10  │      │  🟡 Predicted    10  │      │
│ └──────────────────────┘      └──────────────────────┘      │
│ ┌──────────────────────┐      ┌──────────────────────┐      │
│ │ LC Gate              │      │ Other Gears          │      │
│ │  🟢 Normal       10  │      │  🟢 Normal       30  │      │
│ │  🔴 Failed        1  │      │  🔴 Failed        2  │      │
│ │  🟡 Predicted     2  │      │  🟡 Predicted     5  │      │
│ └──────────────────────┘      └──────────────────────┘      │
│ ─────────────────────────────────────────────────────────── │
│ FLEET HEALTH · ALL CATEGORIES ────────────────────────────  │
│ ┌─────────────────────────────────────────────────────────┐ │
│ │  ( 77% NORMAL )  🟢 Normal: 230  🟡 Predicted: 44       │ │  ◄── 5. Overall Fleet Health Donut & Totals
│ │                  🔴 Failed: 26                          │ │
│ └─────────────────────────────────────────────────────────┘ │
│ ─────────────────────────────────────────────────────────── │
│ INFRASTRUCTURE ───────────────────────────────────────────  │
│ ┌────────────┐  ┌────────────┐  ┌────────────┐  ┌──────────┐│
│ │ 55 SENSORS │  │ 8 SENSORS  │  │ 55 IOT OK  │  │ 8 IOT    ││  ◄── 6. Infrastructure Status Cards
│ │    OK      │  │   FLT      │  │            │  │   FLT    ││
│ └────────────┘  └────────────┘  └────────────┘  └──────────┘│
│ ─────────────────────────────────────────────────────────── │
│   [DASHBOARD]   [ALERT]   [TELEMETRY]   [HEALTH]  [EQUIP]   │  ◄── 7. Bottom Navigation (Dashboard Active)
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

## 2. API Specifications for Dashboard Screen

### API 1: Top Location Filter Dropdowns (`Zone`, `Division`, `Station`)

Populate filter options on page load.

* **HTTP Method**: `GET`
* **Endpoint**: `/alerts/filters`
* **cURL Request**:
  ```bash
  curl -X GET "https://my-fastapi-app-undz.onrender.com/alerts/filters" \
       -H "Authorization: Bearer <YOUR_JWT_TOKEN>"
  ```

---

### API 2: Dashboard Overview & Asset Category Summary (`GET /api/dashboard/mobile-summary`)

Fetches live alert shortcut counters, 6 asset category status breakdown cards, fleet health donut, and infrastructure KPI blocks.

* **HTTP Method**: `GET`
* **Endpoint**: `/api/dashboard/mobile-summary`
* **Query Parameters** (Optional Location Filters):
  * `zone_code` (string, e.g. `"NR"`)
  * `division_code` (string, e.g. `"PRYJ"`)
  * `station_code` (string, e.g. `"MJA"`)

* **cURL Request**:
  ```bash
  curl -X GET "https://my-fastapi-app-undz.onrender.com/api/dashboard/mobile-summary?zone_code=NR&division_code=PRYJ&station_code=MJA" \
       -H "Authorization: Bearer <YOUR_JWT_TOKEN>"
  ```

* **Response Payload (`200 OK` — Real Backend Schema `MobileDashboardSummaryResponse`)**:
  ```json
  {
    "zone_code": "NR",
    "division_code": "PRYJ",
    "station_code": "MJA",
    "live_alerts": {
      "alert_history_count": 142,
      "alert_live_count": 8
    },
    "assets_by_category": [
      {
        "category_key": "PT_MC",
        "category_name": "PT — M/C",
        "normal_count": 50,
        "failed_count": 5,
        "predicted_count": 10
      },
      {
        "category_key": "TRACK_CIRCUIT",
        "category_name": "Track Circuit",
        "normal_count": 40,
        "failed_count": 4,
        "predicted_count": 7
      },
      {
        "category_key": "SIGNAL",
        "category_name": "Signal",
        "normal_count": 45,
        "failed_count": 6,
        "predicted_count": 10
      },
      {
        "category_key": "AXLE_COUNTER",
        "category_name": "Axle Counter",
        "normal_count": 55,
        "failed_count": 8,
        "predicted_count": 10
      },
      {
        "category_key": "LC_GATE",
        "category_name": "LC Gate",
        "normal_count": 10,
        "failed_count": 1,
        "predicted_count": 2
      },
      {
        "category_key": "OTHER_GEARS",
        "category_name": "Other Gears",
        "normal_count": 30,
        "failed_count": 2,
        "predicted_count": 5
      }
    ],
    "fleet_health": {
      "normal_percentage": 77.0,
      "normal_count": 230,
      "predicted_count": 44,
      "failed_count": 26
    },
    "infrastructure": {
      "sensors_ok": 55,
      "sensors_flt": 8,
      "iot_ok": 55,
      "iot_flt": 8
    }
  }
  ```

* **UI Mapping**:
  - `zone_code` · `division_code` · `station_code` $\rightarrow$ Subtitle `NR · PRYJ · MJA`
  - `live_alerts.alert_live_count` $\rightarrow$ Badge on `🟢 Alert Live` card button
  - `assets_by_category[]` $\rightarrow$ Populate 6 Category Cards Grid:
    - 🟢 `normal_count` (Green)
    - 🔴 `failed_count` (Red)
    - 🟡 `predicted_count` (Yellow/Orange)
  - `fleet_health` $\rightarrow$ Render **FLEET HEALTH · ALL CATEGORIES** Donut (`77% NORMAL`), `Normal: 230`, `Predicted: 44`, `Failed: 26`.
  - `infrastructure` $\rightarrow$ Render **INFRASTRUCTURE** 4 KPI boxes (`55 SENSORS OK`, `8 SENSORS FLT`, `55 IOT OK`, `8 IOT FLT`).


---

## 3. Flutter / Dart Implementation Code Example

```dart
import 'package:http/http.dart' as http;
import 'dart:convert';

class MobileDashboardService {
  final String baseUrl = "https://my-fastapi-app-undz.onrender.com";
  final String token;

  MobileDashboardService({required this.token});

  // Fetch Mobile Dashboard Summary
  Future<Map<String, dynamic>> fetchDashboardSummary({
    String? zoneCode,
    String? divisionCode,
    String? stationCode,
  }) async {
    final uri = Uri.parse('$baseUrl/api/dashboard/mobile-summary').replace(
      queryParameters: {
        if (zoneCode != null) 'zone_code': zoneCode,
        if (divisionCode != null) 'division_code': divisionCode,
        if (stationCode != null) 'station_code': stationCode,
      },
    );

    final response = await http.get(
      uri,
      headers: {'Authorization': 'Bearer $token'},
    );

    if (response.statusCode == 200) {
      return jsonDecode(response.body);
    } else {
      throw Exception('Failed to load dashboard summary');
    }
  }
}
```

---

## 4. Mobile Developer Handoff Checklist

- [x] Query `/alerts/filters` on mount to populate Location filters (`Zone`, `Division`, `Station`).
- [x] Query `GET /api/dashboard/mobile-summary` to load `LIVE ALERTS` shortcut counts and `ASSETS BY CATEGORY` grid cards.
- [x] Bind `Alert Live` shortcut button to navigate to `01 · ALERT LIVE` screen.
- [x] Render the 6 Asset Category cards (`PT — M/C`, `Track Circuit`, `Signal`, `Axle Counter`, `LC Gate`, `Other Gears`).
