# RDPMS Real-Time Communication Guide

This document covers all real-time data streaming mechanisms available in the RDPMS backend: **WebSocket** (bidirectional), **Server-Sent Events / SSE** (server-push), and **REST polling** endpoints. It also explains the internal `ConnectionManager` architecture and how broadcasts are triggered from telemetry/alert ingestion.

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [WebSocket Endpoints](#2-websocket-endpoints)
   - [Live Telemetry](#21-live-telemetry-stream)
   - [Live Alerts](#22-live-alerts-stream)
   - [Live Health Status](#23-live-health-status-stream)
3. [Message Protocol (WebSocket)](#3-message-protocol-websocket)
   - [Server → Client Messages](#31-server--client-messages)
   - [Client → Server Messages](#32-client--server-messages)
4. [Server-Sent Events (SSE)](#4-server-sent-events-sse)
   - [SSE Telemetry](#41-sse-telemetry)
   - [SSE Alerts](#42-sse-alerts)
   - [SSE Health](#43-sse-health)
5. [REST Real-Time Polling Endpoints](#5-rest-real-time-polling-endpoints)
6. [Connection Manager Internals](#6-connection-manager-internals)
7. [How Broadcasts Are Triggered](#7-how-broadcasts-are-triggered)
8. [Frontend Integration Examples](#8-frontend-integration-examples)
9. [Error Handling & Reconnection](#9-error-handling--reconnection)

---

## 1. Architecture Overview

```
┌──────────────────────────────────────────────────────────────┐
│                    RDPMS Backend (FastAPI)                    │
│                                                              │
│  ┌──────────────┐    ┌──────────────┐    ┌───────────────┐  │
│  │  /ws/        │    │  /sse/       │    │ /api/realtime/│  │
│  │  WebSocket   │    │  SSE         │    │ REST polling  │  │
│  │  Endpoints   │    │  Endpoints   │    │ Endpoints     │  │
│  └──────┬───────┘    └──────┬───────┘    └───────────────┘  │
│         │                   │                                │
│         └─────────┬─────────┘                                │
│                   │                                          │
│         ┌─────────▼──────────┐                               │
│         │  ConnectionManager │  ← Singleton websocket_manager│
│         │  (websocket_manager│                               │
│         │   .py)             │                               │
│         └─────────┬──────────┘                               │
│                   │                                          │
│         ┌─────────▼──────────┐                               │
│         │   Redis / In-memory│  ← Latest telemetry values    │
│         │   Cache            │     gateway health, etc.      │
│         └────────────────────┘                               │
└──────────────────────────────────────────────────────────────┘
```

**When to use each mechanism:**

| Use Case | Recommended |
|---|---|
| Live dashboards that need instant push | **WebSocket** |
| Displaying live alerts as they arrive | **WebSocket** or **SSE** |
| Simple dashboards, no bidirectionality needed | **SSE** |
| Mobile / limited environment | **SSE** (HTTP/1.1 compatible) |
| One-time data fetch without streaming | **REST polling** |

---

## 2. WebSocket Endpoints

> **Base URL**: `ws://3.6.93.103` (production) or `ws://localhost:8000` (local)
>
> **Authentication**: No token required — WebSocket connections are opened directly.

---

### 2.1 Live Telemetry Stream

```
WS  /ws/telemetry/{station_code}
```

**Query Parameters:**

| Parameter | Type | Required | Description |
|---|---|---|---|
| `station_code` | `string` (path) | ✅ | e.g. `LKO`, `DLI` |
| `asset_type` | `string` (query) | ❌ | Filter by asset type hex, e.g. `01` |
| `asset_no` | `string` (query) | ❌ | Filter by asset number code, e.g. `PT-101` |

**Lifecycle:**
1. Client connects → server sends `initial_state` message with all cached parameter values.
2. Server broadcasts `telemetry_update` whenever a new telemetry packet arrives for the station.
3. Server sends `ping` every 30 seconds; client must reply with `pong`.

**Example URL:**
```
ws://3.6.93.103/ws/telemetry/LKO?asset_type=01&asset_no=PT-101
```

---

### 2.2 Live Alerts Stream

```
WS  /ws/alerts/{station_code}
```

**Query Parameters:**

| Parameter | Type | Required | Description |
|---|---|---|---|
| `station_code` | `string` (path) | ✅ | e.g. `LKO` |
| `alert_type` | `string` (query) | ❌ | `failure`, `predictive`, or `all` (default: `all`) |

**Lifecycle:**
1. Client connects → server sends `pending_alerts` message with currently active (uncleared) alerts.
2. Server broadcasts `new_alert` whenever a new alert is generated.
3. Client can send `acknowledge` action to mark an alert as acknowledged.

**Example URL:**
```
ws://3.6.93.103/ws/alerts/LKO?alert_type=failure
```

---

### 2.3 Live Health Status Stream

```
WS  /ws/health/{station_code}
```

**Query Parameters:**

| Parameter | Type | Required | Description |
|---|---|---|---|
| `station_code` | `string` (path) | ✅ | e.g. `LKO` |

**Lifecycle:**
1. Client connects → server sends `initial_health` message with current gateway/sensor health.
2. Server broadcasts `health_update` when a sensor or gateway health status changes.

**Example URL:**
```
ws://3.6.93.103/ws/health/LKO
```

---

## 3. Message Protocol (WebSocket)

All messages are **JSON encoded strings**. Both server-to-client and client-to-server messages use a `type`/`action` field to discriminate their intent.

---

### 3.1 Server → Client Messages

#### `initial_state` *(Telemetry WS)*
Sent immediately after connection to give the client the current parameter snapshot.

```json
{
  "type": "initial_state",
  "data": {
    "station_code": "LKO",
    "timestamp": "2026-08-03T10:00:00.000000",
    "parameters": {
      "0001000C": { "value": 5.12, "timestamp": "03-08-2026 09:55:00.000" },
      "0001000D": { "value": 220.5, "timestamp": "03-08-2026 09:55:00.000" }
    }
  }
}
```

---

#### `telemetry_update` *(Telemetry WS)*
Pushed every time a new telemetry data point arrives from the physical gateway.

```json
{
  "type": "telemetry_update",
  "data": {
    "stngw_id": "456523AB",
    "station_code": "LKO",
    "para_id": "0001000C",
    "value": 5.32,
    "timestamp": "03-08-2026 10:00:05.123",
    "asset_number_code": "PT-101"
  }
}
```

---

#### `pending_alerts` *(Alerts WS)*
Sent on connection to give the client all currently active alerts.

```json
{
  "type": "pending_alerts",
  "data": [
    {
      "id": 42,
      "alert_type": "Failure",
      "asset_no": "PT-101",
      "cause": "Motor Overload",
      "cause_detail": "Peak current exceeded 150A threshold",
      "time": "2026-08-03T08:30:00.000000",
      "acknowledged": false
    }
  ]
}
```

---

#### `new_alert` *(Alerts WS)*
Pushed immediately when a new alert is generated by the alert processor.

```json
{
  "type": "new_alert",
  "data": {
    "id": 43,
    "alert_type": "Predictive",
    "asset_no": "SIG-02",
    "cause": "Signal Voltage Degradation",
    "cause_detail": "Voltage trend approaching lower threshold",
    "station_code": "LKO",
    "time": "2026-08-03T10:15:00.000000"
  }
}
```

---

#### `initial_health` *(Health WS)*
Sent on connection to give the client the current hardware health snapshot.

```json
{
  "type": "initial_health",
  "data": {
    "station_code": "LKO",
    "timestamp": "2026-08-03T10:00:00.000000",
    "gateway": {
      "status": "healthy",
      "last_seen": "2026-08-03T09:58:00.000000",
      "vcc": "4500",
      "vgc": "3800",
      "version": "1.2.0",
      "registered": "True"
    },
    "sensors": {
      "total": 24,
      "healthy": 23,
      "faulty": 1
    },
    "iot": {
      "total": 4,
      "healthy": 4,
      "faulty": 0
    }
  }
}
```

---

#### `health_update` *(Health WS)*
Pushed when a gateway or sensor health status changes.

```json
{
  "type": "health_update",
  "data": {
    "device_type": "sensor",
    "device_id": "0001000C",
    "status": "faulty",
    "timestamp": "2026-08-03T10:02:00.000000"
  }
}
```

---

#### `maintenance_update` *(All WS)*
Pushed when an asset enters or leaves maintenance mode.

```json
{
  "type": "maintenance_update",
  "data": {
    "asset_number_code": "PT-101",
    "action": "activated",
    "from_time": "2026-08-03T10:00:00",
    "to_time": "2026-08-03T12:00:00"
  }
}
```

---

#### `ping` *(All WS)*
Heartbeat message sent by the server every **30 seconds**.

```json
{
  "type": "ping",
  "timestamp": "2026-08-03T10:05:00.000000"
}
```

---

#### `subscription_confirmed` *(All WS)*
Sent back to the client after a successful subscription change.

```json
{
  "type": "subscription_confirmed",
  "data": {
    "asset_type": "01",
    "asset_no": "PT-101"
  }
}
```

---

#### `acknowledged` *(Alerts WS)*
Sent back after the client successfully acknowledges an alert.

```json
{
  "type": "acknowledged",
  "data": {
    "alert_id": 42
  }
}
```

---

#### `error` *(All WS)*
Sent whenever the server encounters an error it can recover from.

```json
{
  "type": "error",
  "message": "Station LKO not found"
}
```

---

### 3.2 Client → Server Messages

#### `pong` — Reply to Heartbeat
Must be sent by the client within **60 seconds** of receiving a `ping`, otherwise the server will close the connection.

```json
{
  "type": "pong"
}
```

---

#### `subscribe` — Change Subscription Filters *(Telemetry WS)*
Dynamically update the filters for which asset's data is received.

```json
{
  "action": "subscribe",
  "asset_type": "01",
  "asset_no": "PM-203"
}
```

---

#### `subscribe` — Change Alert Subscription *(Alerts WS)*

```json
{
  "action": "subscribe",
  "alert_type": "predictive"
}
```

---

#### `acknowledge` — Acknowledge an Alert *(Alerts WS)*
Marks an alert as acknowledged in the database.

```json
{
  "action": "acknowledge",
  "alert_id": 42
}
```

---

## 4. Server-Sent Events (SSE)

SSE endpoints are **read-only server-push** streams over standard HTTP. They are ideal for environments where WebSocket support is limited (e.g. reverse proxies, older browsers, or mobile apps).

> **Authentication**: Requires `X-API-Key` header (same key used for webhook ingestion).
>
> **Base URL**: `http://3.6.93.103`

---

### 4.1 SSE Telemetry

```
GET /sse/telemetry/{station_code}
```

**Headers:**
```
X-API-Key: <your_api_key>
Accept: text/event-stream
```

**Query Parameters:**

| Parameter | Type | Required | Description |
|---|---|---|---|
| `asset_type` | `string` | ❌ | Filter by asset type |
| `asset_no` | `string` | ❌ | Filter by asset number |

**SSE Event Stream Format:**

```
event: initial
data: {"station_code": "LKO", "parameters": {"0001000C": {"value": 5.12, "timestamp": "..."}}}

event: update
data: {"station_code": "LKO", "changed": {"0001000C": {"value": 5.32, "timestamp": "..."}}, "timestamp": "2026-08-03T10:05:00"}

event: heartbeat
data: {"timestamp": "2026-08-03T10:05:05.000000"}
```

**Behaviour:**
- On connection → sends `initial` event with all current cached parameters.
- Every **5 seconds** → polls Redis for changes; sends `update` event only if parameters changed.
- Sends `heartbeat` event every 5 seconds to keep the connection alive.

---

### 4.2 SSE Alerts

```
GET /sse/alerts/{station_code}
```

**Headers:**
```
X-API-Key: <your_api_key>
Accept: text/event-stream
```

**Query Parameters:**

| Parameter | Type | Required | Description |
|---|---|---|---|
| `alert_type` | `string` | ❌ | `failure`, `predictive`, or `all` (default: `all`) |

**SSE Event Stream Format:**

```
event: pending
data: {"alerts": [{"id": 42, "asset_no": "PT-101", "cause": "Motor Overload", "time": "..."}]}

event: alert
data: {"id": 43, "alert_type": "Failure", "asset_no": "SIG-02", "cause": "...", "cause_detail": "...", "time": "..."}

event: heartbeat
data: {"timestamp": "2026-08-03T10:05:05.000000"}
```

**Behaviour:**
- On connection → sends `pending` event with up to 50 active alerts.
- Every **2 seconds** → polls database for new alerts not yet seen; sends one `alert` event per new alert.
- Sends `heartbeat` event every 2 seconds.

---

### 4.3 SSE Health

```
GET /sse/health/{station_code}
```

**Headers:**
```
X-API-Key: <your_api_key>
Accept: text/event-stream
```

**SSE Event Stream Format:**

```
event: update
data: {"gateway": {"status": "healthy", ...}, "sensors": {"total": 24, "healthy": 23, "faulty": 1}, "timestamp": "..."}

event: heartbeat
data: {"timestamp": "2026-08-03T10:35:00.000000"}
```

**Behaviour:**
- On connection → immediately sends current health state as `update` event.
- Every **30 seconds** → re-fetches health from Redis; sends `update` event only if something changed.
- Sends `heartbeat` event every 30 seconds.

---

## 5. REST Real-Time Polling Endpoints

These endpoints provide a **single-shot snapshot** (not streaming) of real-time data. Useful for initial page loads, or for dashboards polling at fixed intervals.

> **Authentication**: Requires `X-API-Key` header.
>
> **Base URL**: `http://3.6.93.103`

---

### `GET /api/realtime/telemetry/{station_code}`
Returns the latest cached value for all parameters of a station.

**Response (`200 OK`):**
```json
{
  "station_code": "LKO",
  "station_name": "Lucknow",
  "timestamp": "2026-08-03T10:00:00.000000",
  "parameter_count": 24,
  "parameters": {
    "0001000C": { "value": 5.12, "timestamp": "03-08-2026 09:55:00.000" },
    "0001000D": { "value": 220.5, "timestamp": "03-08-2026 09:55:00.000" }
  }
}
```

---

### `GET /api/realtime/telemetry/{station_code}/{para_id}/history`
Returns time-series history for a specific parameter from the database.

**Query Parameters:**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `hours` | `int` | `24` | Look-back window (1–168 hours = up to 1 week) |

**Response (`200 OK`):**
```json
{
  "para_id": "0001000C",
  "station_code": "LKO",
  "period": {
    "start": "2026-08-02T10:00:00",
    "end": "2026-08-03T10:00:00",
    "hours": 24
  },
  "data_points": 1440,
  "parameter_info": {
    "name": "Peak Current",
    "unit": "A",
    "min_safe": 0.5,
    "max_safe": 120.0
  },
  "values": [
    { "timestamp": "03-08-2026 09:00:00.000", "value": 4.95 },
    { "timestamp": "03-08-2026 09:01:00.000", "value": 5.10 }
  ]
}
```

---

### `GET /api/realtime/dashboard/{station_code}`
Returns a comprehensive dashboard snapshot including metrics, alerts, health, and telemetry summary.

**Response (`200 OK`):**
```json
{
  "station_code": "LKO",
  "station_name": "Lucknow",
  "timestamp": "2026-08-03T10:00:00.000000",
  "metrics": {
    "total_assets": 14,
    "failures": 2,
    "system_health": 88.5,
    "gateway_health": 100.0,
    "prediction_accuracy": 91.0,
    "mttr_hours": 4.2
  },
  "alerts": {
    "total": 5,
    "failure": 2,
    "predictive": 3,
    "pending": 2,
    "by_cause": { "Motor Overload": 2, "Voltage Degradation": 3 }
  },
  "health": {
    "gateway": "healthy",
    "sensors": { "total": 24, "healthy": 23, "faulty": 1 },
    "iot": { "total": 4, "healthy": 4, "faulty": 0 }
  },
  "telemetry": {
    "total_parameters": 24,
    "updated_in_last_hour": 22,
    "latest_timestamp": "03-08-2026 09:58:00.000"
  },
  "gateway_status": "online"
}
```

---

### `GET /api/realtime/asset-status/{station_code}/{asset_no}`
Returns a comprehensive real-time status for one specific asset.

**Response (`200 OK`):**
```json
{
  "station_code": "LKO",
  "asset_number_code": "PT-101",
  "asset_type_hex": "01",
  "asset_make": "ESCORTS",
  "asset_model": "HM-5005",
  "timestamp": "2026-08-03T10:00:00.000000",
  "parameters": {
    "0001000C": { "value": 5.12, "timestamp": "03-08-2026 09:55:00.000" }
  },
  "active_alerts": [
    {
      "id": 42,
      "alert_type": "Failure",
      "cause": "Motor Overload",
      "cause_detail": "Peak current exceeded threshold",
      "time": "2026-08-03T08:30:00.000000"
    }
  ],
  "sensor_health": {
    "0001000C": { "status": "healthy", "timestamp": "2026-08-03T09:55:00.000000" }
  },
  "status": "alerting"
}
```

---

## 6. Connection Manager Internals

The `ConnectionManager` (file: `app/services/websocket_manager.py`) is the central registry for all active WebSocket connections. It is a singleton instance shared across all requests.

### Key Data Structures

| Field | Type | Purpose |
|---|---|---|
| `station_connections` | `Dict[str, Set[WebSocket]]` | Maps station codes to their connected clients |
| `connection_metadata` | `Dict[str, ConnectionMetadata]` | Tracks per-connection metadata |

### ConnectionMetadata Fields

| Field | Description |
|---|---|
| `connection_id` | Unique ID (e.g. `conn_1`, `conn_2`) |
| `station_code` | Which station this connection is subscribed to |
| `connected_at` | When the connection was established |
| `last_ping` | When the server last sent a `ping` |
| `last_pong` | When the server last received a `pong` from client |
| `subscriptions` | Dict of active filters (`asset_type`, `asset_no`, `alert_type`) |

### Heartbeat Mechanism

```
Server                           Client
  |                                |
  |-- ping (every 30s) ----------->|
  |                                |
  |<-- pong ----------------------|
  |                                |
  |-- [if no pong in 60s] ------->| Connection closed (timeout)
```

### Broadcast Methods

| Method | When Called |
|---|---|
| `broadcast_to_station()` | Sends any message to all clients of a station |
| `broadcast_parameter_update()` | Called by telemetry ingestion for each new data point |
| `broadcast_alert()` | Called by alert processor when a new alert is created |
| `broadcast_health_update()` | Called by gateway router when device health changes |
| `broadcast_maintenance_mode()` | Called by maintenance router when mode changes |

---

## 7. How Broadcasts Are Triggered

The following chain shows how a telemetry packet received from a field gateway propagates to a connected frontend client:

```
Physical Gateway
      │
      │  POST /api/gateway/telemetry/{stngw_id}
      ▼
  gateway.py router
      │
      ├── Store to PostgreSQL (Telemetry table)
      ├── Store to Redis (latest value cache)
      ├── Evaluate alert thresholds → alert_processor.py
      │       └── if alert generated:
      │               └── websocket_manager.broadcast_alert(...)
      │
      └── websocket_manager.broadcast_parameter_update(...)
                │
                ▼
        All clients connected to
        /ws/telemetry/{station_code}
        receive: { "type": "telemetry_update", ... }
```

---

## 8. Frontend Integration Examples

### JavaScript — WebSocket Telemetry

```javascript
const ws = new WebSocket('ws://3.6.93.103/ws/telemetry/LKO?asset_no=PT-101');

ws.onopen = () => {
  console.log('Connected to RDPMS telemetry stream');
};

ws.onmessage = (event) => {
  const msg = JSON.parse(event.data);

  switch (msg.type) {
    case 'initial_state':
      // Populate dashboard with current values
      renderParameters(msg.data.parameters);
      break;

    case 'telemetry_update':
      // Update a specific value on the chart/gauge
      updateParameter(msg.data.para_id, msg.data.value, msg.data.timestamp);
      break;

    case 'ping':
      // Always reply to keep the connection alive
      ws.send(JSON.stringify({ type: 'pong' }));
      break;

    case 'error':
      console.error('Server error:', msg.message);
      break;
  }
};

ws.onclose = (event) => {
  console.log('WebSocket closed. Code:', event.code);
  // Implement reconnect logic below
};

ws.onerror = (error) => {
  console.error('WebSocket error:', error);
};
```

---

### JavaScript — WebSocket Alerts with Acknowledgement

```javascript
const ws = new WebSocket('ws://3.6.93.103/ws/alerts/LKO?alert_type=all');

ws.onmessage = (event) => {
  const msg = JSON.parse(event.data);

  if (msg.type === 'pending_alerts') {
    msg.data.forEach(alert => showAlert(alert));
  }

  if (msg.type === 'new_alert') {
    showAlert(msg.data);
  }

  if (msg.type === 'ping') {
    ws.send(JSON.stringify({ type: 'pong' }));
  }
};

// Call this when user clicks "Acknowledge" on an alert
function acknowledgeAlert(alertId) {
  ws.send(JSON.stringify({
    action: 'acknowledge',
    alert_id: alertId
  }));
}
```

---

### JavaScript — SSE Telemetry (EventSource)

```javascript
const eventSource = new EventSource(
  'http://3.6.93.103/sse/telemetry/LKO',
  {
    headers: { 'X-API-Key': 'your_api_key' }
  }
);

// Note: EventSource doesn't support custom headers in all browsers.
// Use a URL query param workaround if needed:
// new EventSource('http://3.6.93.103/sse/telemetry/LKO?api_key=...');

eventSource.addEventListener('initial', (event) => {
  const data = JSON.parse(event.data);
  renderParameters(data.parameters);
});

eventSource.addEventListener('update', (event) => {
  const data = JSON.parse(event.data);
  Object.entries(data.changed).forEach(([paraId, val]) => {
    updateParameter(paraId, val.value, val.timestamp);
  });
});

eventSource.addEventListener('heartbeat', (event) => {
  // Connection is alive
});

eventSource.onerror = (error) => {
  console.error('SSE error:', error);
  // EventSource auto-reconnects by default
};
```

---

### React Hook — WebSocket with Auto-Reconnect

```javascript
import { useEffect, useRef, useState } from 'react';

function useRdpmsWebSocket(stationCode, endpoint = 'telemetry') {
  const [data, setData] = useState(null);
  const wsRef = useRef(null);
  const reconnectTimer = useRef(null);

  const connect = () => {
    const ws = new WebSocket(
      `ws://3.6.93.103/ws/${endpoint}/${stationCode}`
    );

    ws.onmessage = (event) => {
      const msg = JSON.parse(event.data);
      if (msg.type === 'ping') {
        ws.send(JSON.stringify({ type: 'pong' }));
        return;
      }
      setData(msg);
    };

    ws.onclose = () => {
      // Auto-reconnect after 3 seconds
      reconnectTimer.current = setTimeout(connect, 3000);
    };

    wsRef.current = ws;
  };

  useEffect(() => {
    connect();
    return () => {
      clearTimeout(reconnectTimer.current);
      wsRef.current?.close();
    };
  }, [stationCode]);

  return data;
}

// Usage:
// const msg = useRdpmsWebSocket('LKO', 'alerts');
```

---

## 9. Error Handling & Reconnection

### Server-Side Rules

| Scenario | Server Behaviour |
|---|---|
| Invalid JSON from client | Server sends `{"type": "error", "message": "Invalid JSON format"}` and keeps connection open |
| Station not found | Server sends `{"type": "error", "message": "Station XYZ not found"}` |
| No gateway found | Server sends `{"type": "error", "message": "Gateway for station XYZ not found"}` |
| Client silent for > 60s | Server closes the connection (heartbeat timeout) |
| Client disconnect | Server removes connection from registry and stops heartbeat task |

### Client-Side Best Practices

1. **Always reply to `ping` with `pong`** — or the server will drop you after 60 seconds.
2. **Implement exponential back-off for reconnects** — e.g., retry at 1s, 2s, 4s, 8s up to 30s max.
3. **Re-subscribe after reconnect** — after a new `initial_state` or `pending_alerts` is received, re-apply any active filters by sending a `subscribe` action.
4. **SSE auto-reconnects** — The browser's `EventSource` API reconnects automatically; no manual handling needed.
5. **Handle `event: error`** — Display a user-visible notification rather than silently ignoring stream errors.

### Close Codes Reference

| Code | Meaning |
|---|---|
| `1000` | Normal closure |
| `1001` | Server going away (restart/deploy) |
| `1006` | Abnormal disconnect (network issue) — reconnect |
| `1011` | Server error — reconnect |
