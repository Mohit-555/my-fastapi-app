# RDPMS Mobile App — Performance Screen API Integration Guide

This guide provides the complete technical specification for mobile application developers (Flutter, React Native, Swift, Kotlin) integrating the **Performance of RDPMS (06 · PERFORMANCE)** screen with the RDPMS backend.

---

## 📱 Mobile Screen Mapping Overview

```
┌─────────────────────────────────────────────────────────────┐
│ 9:41                           RDPMS · IR-NET               │
│                                                             │
│ Performance                                                 │
│  [Zone ▾]  [Div ▾]  [Stns ▾]  [From date ▾] [To date ▾]     │  ◄── 1. Location & Date Filters
│ ─────────────────────────────────────────────────────────── │
│ OVERVIEW · NR / PRYJ · 01-15 JUL ─────────────────────────  │
│ ┌──────────────┐   ┌──────────────┐   ┌──────────────┐      │
│ │  ( 82% )     │   │  ( 71% )     │   │  ( 89% )     │      │  ◄── 2. Top Overview KPI Donut Cards
│ │  CONFIRMED   │   │  CONFIRMED   │   │  RDPMS VS    │      │      (Failure %, Predictive %, Actual %)
│ │  FAILURE     │   │  PREDICTIVE  │   │  ACTUAL      │      │
│ └──────────────┘   └──────────────┘   └──────────────┘      │
│ ─────────────────────────────────────────────────────────── │
│ BY STATION ───────────────────────────────────────────────  │
│  MJA                                                        │  ◄── 3. Station Performance Progress Bars
│  ████████████████████ 86%  (Failure Conf. - Green)          │
│  █████████████████    74%  (Predictive Conf. - Orange)        │
│  █████████████████████ 91% (RDPMS vs Actual - Blue)         │
│                                                             │
│  GZB                                                        │
│  ██████████████████   79%                                   │
│  ███████████████      66%                                   │
│  ███████████████████  84%                                   │
│ ─────────────────────────────────────────────────────────── │
│ 🟢 Failure conf.   🟠 Predictive conf.   🔵 RDPMS vs actual │  ◄── 4. Legend
│ ─────────────────────────────────────────────────────────── │
│   [DASHBOARD]   [ALERT]   [TELEMETRY]   [HEALTH]  [PERF]    │  ◄── 5. Bottom Navigation (Performance Active)
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

## 2. API Specifications for Performance Screen

### API 1: Filter Dropdowns (`Zone`, `Div`, `Stns`)

Populate filter options on page load.

* **HTTP Method**: `GET`
* **Endpoint**: `/alerts/filters`
* **cURL Request**:
  ```bash
  curl -X GET "https://my-fastapi-app-undz.onrender.com/alerts/filters" \
       -H "Authorization: Bearer <YOUR_JWT_TOKEN>"
  ```

---

### API 2: Performance Overview & Station Metrics (`GET /api/dashboard/performance-overview`)

Fetches the 3 top overview KPI donut percentages and station-wise performance comparison progress bars.

* **HTTP Method**: `GET`
* **Endpoint**: `/api/dashboard/performance-overview`
* **Query Parameters** (Optional Filters):
  * `zone_code` (string, e.g. `"NR"`)
  * `division_code` (string, e.g. `"PRYJ"`)
  * `station_code` (string, e.g. `"MJA"`)

* **cURL Request**:
  ```bash
  curl -X GET "https://my-fastapi-app-undz.onrender.com/api/dashboard/performance-overview?zone_code=NR&division_code=PRYJ" \
       -H "Authorization: Bearer <YOUR_JWT_TOKEN>"
  ```

* **Response Payload (`200 OK` — Real Backend Schema `PerformanceOverviewResponse`)**:
  ```json
  {
    "confirmed_failure_percentage": 82.0,
    "confirmed_predictive_percentage": 71.0,
    "actual_failures_caught_percentage": 89.0,
    "by_station": [
      {
        "station_code": "MJA",
        "station_name": "Meja Road",
        "failure_accuracy": 86.0,
        "predictive_accuracy": 74.0,
        "actual_detection_rate": 91.0
      },
      {
        "station_code": "GZB",
        "station_name": "Ghaziabad",
        "failure_accuracy": 79.0,
        "predictive_accuracy": 66.0,
        "actual_detection_rate": 84.0
      },
      {
        "station_code": "DHN",
        "station_name": "Dhanbad",
        "failure_accuracy": 80.0,
        "predictive_accuracy": 70.0,
        "actual_detection_rate": 88.0
      }
    ]
  }
  ```

* **UI Mapping**:
  - `confirmed_failure_percentage` $\rightarrow$ Render Card 1 Donut (`82%` Green)
  - `confirmed_predictive_percentage` $\rightarrow$ Render Card 2 Donut (`71%` Orange)
  - `actual_failures_caught_percentage` $\rightarrow$ Render Card 3 Donut (`89%` Blue)
  - `by_station[]` $\rightarrow$ Map each station to 3 horizontal progress bars:
    - 🟢 Green bar: `failure_accuracy`%
    - 🟠 Orange bar: `predictive_accuracy`%
    - 🔵 Blue bar: `actual_detection_rate`%

---

### API 3: Detailed Annexure F Station Performance Report (`POST /api/dashboard/performance`)

Used for exporting and viewing full tabular performance records across all stations.

* **HTTP Method**: `POST`
* **Endpoint**: `/api/dashboard/performance`
* **Request Body**:
  ```json
  {
    "start_date": "01/07/2026",
    "start_time": "00:00:00",
    "end_date": "15/07/2026",
    "end_time": "23:59:59",
    "request": {
      "zone": ["NR"],
      "division": ["PRYJ"]
    }
  }
  ```

---

## 3. Flutter / Dart Implementation Code Example

```dart
import 'package:http/http.dart' as http;
import 'dart:convert';

class PerformanceService {
  final String baseUrl = "https://my-fastapi-app-undz.onrender.com";
  final String token;

  PerformanceService({required this.token});

  // Fetch Performance Overview Metrics
  Future<Map<String, dynamic>> fetchPerformanceOverview({
    String? zoneCode,
    String? divisionCode,
  }) async {
    final uri = Uri.parse('$baseUrl/api/dashboard/performance-overview').replace(
      queryParameters: {
        if (zoneCode != null) 'zone_code': zoneCode,
        if (divisionCode != null) 'division_code': divisionCode,
      },
    );

    final response = await http.get(
      uri,
      headers: {'Authorization': 'Bearer $token'},
    );

    if (response.statusCode == 200) {
      return jsonDecode(response.body);
    } else {
      throw Exception('Failed to load performance metrics');
    }
  }
}
```

---

## 4. Mobile Developer Handoff Checklist

- [x] Query `/alerts/filters` on mount to populate top location and date filter pickers.
- [x] Query `GET /api/dashboard/performance-overview` to load the 3 Overview Donut Cards (`82%`, `71%`, `89%`).
- [x] Render the `BY STATION` list with 3 horizontal progress bars per station (`MJA`, `GZB`, `DHN`).
- [x] Align color coding: 🟢 Failure Accuracy (Green), 🟠 Predictive Accuracy (Orange), 🔵 Actual Failures Caught (Blue).
