# RDPMS Mobile App — Master API Integration Guide Index

Welcome to the official **RDPMS Mobile Application Integration Specification**. This master directory contains links and summary specifications for all **6 key mobile screens**.

---

## 🌐 Production Server & Authentication Details

* **Production REST Base URL**: `https://my-fastapi-app-undz.onrender.com`
* **Production WebSockets / SSE Base URL**: `wss://my-fastapi-app-undz.onrender.com` / `https://my-fastapi-app-undz.onrender.com`
* **Authentication Header**:
  ```http
  Authorization: Bearer <JWT_TOKEN>
  Content-Type: application/json
  ```
* **Test Login Credentials**:
  - `employee_id`: `"hq_admin"`
  - `password`: `"admin123"`

---

## 📱 Integration Guides Directory by Screen

| # | Screen Name | Detailed Guide File | Key APIs & Protocols | Primary UI Elements Covered |
| :-: | :--- | :--- | :--- | :--- |
| **01** | **Alert Live** | [`MOBILE_APP_ALERT_LIVE_INTEGRATION_GUIDE.md`](./MOBILE_APP_ALERT_LIVE_INTEGRATION_GUIDE.md) | `GET /alerts/live`<br>`POST /alerts/events/{id}/feedback`<br>`WS /ws/alerts/{station_code}` | Top Summary Counters (Predictive, Failure, Total), Active Alert Cards, Feedback Dialog (`T`, `PT`, `F`, `M`), Real-time WebSocket notifications. |
| **02** | **Equipment Room** | [`MOBILE_APP_EQUIPMENT_ROOM_INTEGRATION_GUIDE.md`](./MOBILE_APP_EQUIPMENT_ROOM_INTEGRATION_GUIDE.md) | `GET /equipment-room/live`<br>`WS /ws/telemetry/{stngw_id}` | Station Equipment Room Cards (`RR`, `IPS`, `BATT`), Temperature (°C), Humidity (%), Door Status (`OPEN`/`CLOSED`). |
| **03** | **Telemetry Live** | [`MOBILE_APP_TELEMETRY_LIVE_INTEGRATION_GUIDE.md`](./MOBILE_APP_TELEMETRY_LIVE_INTEGRATION_GUIDE.md) | `GET /telemetry/live-card`<br>`GET /telemetry/live` (SSE Stream) | Asset Summary Card (`PRYG · PT-101`), Status Pills (`Healthy`), Live Parameters Table (Current, Voltage, Throw Time, Force), 12-Cycle Stroke Chart. |
| **04** | **RDPMS Health** | [`MOBILE_APP_HEALTH_INTEGRATION_GUIDE.md`](./MOBILE_APP_HEALTH_INTEGRATION_GUIDE.md) | `GET /api/monitoring/health/totals`<br>`GET /api/monitoring/health/faulty-by-station`<br>`WS /ws/health/{station_code}` | 4 Summary KPI Grid (Sensors, IoT Devices, Network, Station Gateway), Faulty Hardware List by Station. |
| **05** | **Maintenance Mode** | [`MOBILE_APP_MAINTENANCE_MODE_INTEGRATION_GUIDE.md`](./MOBILE_APP_MAINTENANCE_MODE_INTEGRATION_GUIDE.md) | `GET /maintenance`<br>`POST /maintenance`<br>`POST /maintenance/{id}/clear` | Schedule Window Pickers, 24-Hour Maintenance Timeline Bar (00h–24h), Active & Scheduled Table with Early Clear action. |
| **06** | **Performance** | [`MOBILE_APP_PERFORMANCE_INTEGRATION_GUIDE.md`](./MOBILE_APP_PERFORMANCE_INTEGRATION_GUIDE.md) | `GET /api/dashboard/performance-overview`<br>`POST /api/dashboard/performance` | 3 Overview Donut Cards (Confirmed Failure %, Confirmed Predictive %, RDPMS vs Actual %), Station Performance Comparison Progress Bars. |

---

## 🛠️ Global Common Endpoints

### 1. Global Location & Asset Filters Dropdown
* **Endpoint**: `GET /alerts/filters`
* Populates all mobile screen top filter bars (`Zone`, `Division`, `Station`, `Asset Type`).

### 2. User Authentication & Profile
* **Login**: `POST /auth/login` (`{"employee_id": "...", "password": "..."}`)
* **Current User Profile**: `GET /auth/me`

---

## 🚀 Git Repository Status

All backend endpoints, Pydantic schemas, and markdown integration guides have been pushed to GitHub main repository:
`https://github.com/Mohit-555/my-fastapi-app.git`
