# 📚 RDPMS Application — Master Module to API Mapping Table

This document provides a verified, consolidated reference table mapping every module, sub-module, UI functionality, HTTP method, and FastAPI endpoint in the **RDPMS (Railway Device Performance & Maintenance System)** architecture.

---

## 📋 Master API Mapping Table

| Module | Sub-Module | Functionality | Method | API Endpoint | Description |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **1. Dashboard** | — | Nationwide Statistics | `GET` | `/api/dashboard/summary` | Returns total counts for active failures, predictive alerts, healthy gateways, and system health %. |
| **1. Dashboard** | — | Real-Time System Overview | `GET` | `/api/realtime/overview` | Fetches live gateway connection statuses and active telemetry summaries. |
| **1. Dashboard** | — | Geographic Filters | `GET` | `/zones`, `/divisions`, `/stations` | Populates Zone, Division, and Station dropdown selectors. |
| **2. Alerts** | **2.1 Alert Live** | Live Alert Cards & Summary | `GET` | `/alerts/live` | Retrieves active unresolved predictive and failure alert cards. |
| **2. Alerts** | **2.1 Alert Live** | Acknowledge Alert | `POST` | `/alerts/{id}/acknowledge` | Marks an active alert as acknowledged by an operator. |
| **2. Alerts** | **2.1 Alert Live** | Submit Feedback | `POST` | `/alerts/{id}/feedback` | Submits maintainer feedback (`True`, `Partially True`, `False`) and remarks. |
| **2. Alerts** | **2.1 Alert Live** | Filter Options | `GET` | `/alerts/filters` | Populates Zone, Division, Station, Asset Type, and Asset No dropdowns. |
| **2. Alerts** | **2.2 Alert History** | History Log Grid | `GET` | `/alerts/history` | Paginated search of alert events with incidence time, rectification time, duration, and remarks. |
| **2. Alerts** | **2.2 Alert History** | Export CSV Report | `GET` | `/alerts/history/download` | Exports filtered alert history dataset to CSV spreadsheet. |
| **2. Alerts** | **2.2 Alert History** | Filter Options | `GET` | `/alerts/filters` | Populates filter controls for search bar. |
| **2. Alerts** | **2.3 Alert Summary** | Summary Table Grid | `GET` | `/alerts/summary` | Aggregated breakdown of alert frequencies and accuracy rates per cause/station. |
| **2. Alerts** | **2.3 Alert Summary** | Export CSV Report | `GET` | `/alerts/summary/download` | Downloads aggregated alert summary table as CSV file. |
| **2. Alerts** | **2.3 Alert Summary** | Filter Options | `GET` | `/alerts/filters` | Populates filter dropdowns for search parameters. |
| **3. Telemetry** | **3.1 Live** | Live Telemetry Stream | `GET` | `/telemetry/live` | Retrieves real-time sensor voltage, current, and status packets. |
| **3. Telemetry** | **3.1 Live** | Gateway Telemetry Detail | `GET` | `/telemetry/live/{gateway_id}` | Returns live parameter values for a specific station gateway. |
| **3. Telemetry** | **3.2 History** | History Packet Grid | `GET` | `/telemetry/history` | Returns paginated telemetry packet records with timestamp range filters. |
| **3. Telemetry** | **3.2 History** | Export CSV Data | `GET` | `/telemetry/history/download` | Downloads historical telemetry packets as CSV spreadsheet. |
| **4. RDPMS Health** | **4.1 Health Live** | Top 4 KPI Cards | `GET` | `/api/monitoring/health/totals` | Returns total and faulty counts for Sensors, IoT Devices, Network, and Station Gateway. |
| **4. RDPMS Health** | **4.1 Health Live** | Faulty Components Grid | `GET` | `/api/monitoring/health/faulty-by-station` | Returns station-wise breakdown of faulty sensor, IoT, network, and gateway descriptions. |
| **4. RDPMS Health** | **4.2 Health Summary** | Summary Table Grid | `GET` | `/api/monitoring/health/summary` | Returns station list with % AVAIL. SENSORS, TOTAL SENSORS, and TOTAL IOTS. |
| **4. RDPMS Health** | **4.2 Health Summary** | Export CSV Report | `GET` | `/api/monitoring/health/summary/download` | Exports health summary dataset into downloadable CSV file. |
| **5. Equipment Room** | **5.1 Equipment Room Live** | Live Environmental Status | `GET` | `/equipment-room/live` | Retrieves real-time temperature, humidity, and door sensor statuses across Relay Rooms (RR), IPS, and Battery Rooms (BATT). |
| **5. Equipment Room** | **5.2 Equipment Room History** | History Log Grid | `GET` | `/equipment-room/history` | Paginated 30-min interval logs for TEMP (°C) and HUMIDITY (%). |
| **5. Equipment Room** | **5.2 Equipment Room History** | Export CSV Report | `GET` | `/equipment-room/history/download` | Downloads historical equipment room readings as CSV file. |
| **6. Maintenance** | — | Maintenance Log Grid | `GET` | `/maintenance` | Retrieves list of active, scheduled, and completed maintenance blocks with filters. |
| **6. Maintenance** | — | Activate Maintenance Mode | `POST` | `/maintenance` | Schedules a new maintenance window for an asset (STATION, ASSET NO, FROM DATE/TIME, TO DATE/TIME). |
| **6. Maintenance** | — | Clear Maintenance Block | `POST` | `/maintenance/{id}/clear` | Manually deactivates an active maintenance block early. |
| **6. Maintenance** | — | Export CSV Report | `GET` | `/maintenance/download` | Exports maintenance logs into downloadable CSV file. |
| **7. Asset** | **7.1 Asset Detail** | Asset Master Grid | `GET` | `/assets` | Retrieves asset registry list with ASSET CODE, ASSET NAME, ASSET NUMBER, ASSET TYPE, STATION, MAKE. |
| **7. Asset** | **7.1 Asset Detail** | Add New Asset | `POST` | `/assets` | Registers a new asset in the system database. |
| **7. Asset** | **7.1 Asset Detail** | Update Asset Modal | `PUT` | `/assets/{id}` | Updates existing asset properties (smms_asset_code, station_id, make, model, location, is_active). |
| **7. Asset** | **7.1 Asset Detail** | Delete Asset | `DELETE` | `/assets/{id}` | Deletes an asset record. |
| **7. Asset** | **7.1 Asset Detail** | Filter Options | `GET` | `/assets/filters` | Populates Zone, Division, Station, and Asset Type dropdowns. |
| **7. Asset** | **7.2 Asset Utilization** | Utilization Report Grid | `GET` | `/assets/utilization` | Paginated list of assets with filtered number_of_operations count. |
| **7. Asset** | **7.2 Asset Utilization** | Export CSV Report | `GET` | `/assets/utilization/download` | Downloads asset utilization table as CSV spreadsheet. |
| **8. Performance** | — | Performance Analytics & 3 KPIs | `GET` / `POST` | `/api/performance` | Single consolidated endpoint returning top 3 KPI averages + station performance table. |
| **8. Performance** | — | Enter Actual Failure | `POST` | `/api/performance/actual-failure` | Submits ground-truth site failure log for AI accuracy scoring. |
| **Authentication** | — | Login | `POST` | `/auth/login` | Authenticates user via employee_id and password, returning JWT Bearer token. |
