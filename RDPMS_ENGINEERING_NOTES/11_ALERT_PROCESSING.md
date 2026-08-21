# 11 — Alert Processing

---

## Alert Lifecycle

```
Telemetry row written (is_processed=False)
        │
        │  (background, every 5s)
        ▼
AlertProcessor picks up the row
        │
        ├──► Asset not configured? ──────────────────────► Skip silently
        │
        ├──► In maintenance mode? ──────────────────────► Skip (suppress)
        │
        └──► AlertEngine.evaluate_telemetry()
                │
                ├──► Route by asset_type_hex
                │
                └──► Logic module returns alert candidates
                        │
                        └──► AlertEngine._generate_alert()
                                │
                                ├──► Already active? (in-memory) ─► Skip
                                │
                                ├──► Recently cleared? (< 1h ago) ─► Skip
                                │
                                └──► Write AlertEvent to DB (status=Active)
                                        │
                                        └──► Broadcast via WebSocket
                                                │
                                                ▼
                                         Frontend sees new_alert in real time

        [Human action: Acknowledge]
                │
                └──► alert_acknowledged=True (still Active)

        [Human action: Clear]
                │
                ├──► alert_status=Cleared
                ├──► rectification_time=now
                └──► AlertEngine.alert_history[key] = now
                        (prevents re-generation within 1 hour)
```

---

## Two Alert Types

### Failure Alert

**What it means:** The asset is currently malfunctioning. A Point Machine that won't move. A signal lamp that's out. Requires immediate action.

**Logic:** Compare current reading against absolute threshold (`min_fail` or `max_safe`). If value crosses the threshold → Failure.

**Example from code** (`app/services/logics/point_machine.py:96-121`):
```python
if param_config.min_fail is not None and value < param_config.min_fail:
    alerts.append({
        "cause_code": "PT_N_IND_VOLT_FAIL_AT_LOC",
        "cause_detail": "Point failed in Normal. Normal Indication Voltage at Loc is low...",
        "alert_type": AlertType.FAILURE
    })
```

### Predictive Alert

**What it means:** The asset is operating but its readings are trending toward failure. Current value has degraded below a percentage of the historical average. Time to inspect before it fails.

**Logic:** Calculate rolling average of the last 15 days (up to 100 readings). If current value < 80% of average → Predictive.

**Example from code** (`app/services/logics/point_machine.py:51-61`):
```python
threshold = min(avg_value * (PointMachineLogics.LD1 / 100), param_config.min_safe)
if value < threshold:
    alerts.append({
        "cause_code": "PT_N_VOLT_CURR_LOW",
        "cause_detail": "Predictive Alert: Voltage or Current for Normal operation Low at Loc",
        "alert_type": AlertType.PREDICTIVE
    })
```

---

## Logic Thresholds (from RDSO Annexure C)

| Constant | Value | Meaning |
|---|---|---|
| `LD1` | 80% | Lower deviation level 1 — predictive alert trigger |
| `LD2` | 90% | Lower deviation level 2 — cable check trigger |
| `HD` | 150% | Higher deviation — high-value failure |

---

## Alert Deduplication (Two Layers)

### Layer 1: In-Memory (AlertEngine)

**Source:** `app/services/alert_engine.py:121-141`

```python
def _should_generate_alert(self, asset_number_code, cause_code, alert_type):
    key = f"{asset_number_code}:{cause_code}:{alert_type.value}"
    if key in self.active_alerts:
        return False  # already active, don't duplicate
    if key in self.alert_history:
        if (datetime.now() - self.alert_history[key]).total_seconds() < 3600:
            return False  # cleared within last hour, don't regenerate
    return True
```

**Limitation:** In-memory. Lost on server restart. Per-process — multiple workers have separate state.

### Layer 2: Database (create_alert_event)

**Source:** `app/routers/alerts.py` — `create_alert_event()` function.

Before writing a new `AlertEvent`, the function checks if an active alert already exists for the same `(station_id, asset_no, cause)`. If one exists → the new alert is "suppressed" (raises HTTPException with "suppressed" in detail, caught silently by `alert_engine.py:187`).

This is the defensive DB-level check that catches the race condition where two workers both pass the in-memory check.

---

## Logic Modules by Asset Type

### Point Machine (`asset_type_hex = "00"`)

**File:** `app/services/logics/point_machine.py`

**Predictive logic (Annexure C §2.2(a)):**
- Voltage/Current for Normal operation trending low (< 80% of 15-day average)
- Voltage/Current for Reverse operation trending low

**Failure logic (Annexure C §2.2(b)):**
- Normal indication voltage below `min_fail` → PT failed Normal
- Reverse indication voltage below `min_fail` → PT failed Reverse
- Operation time > `max_safe` → Obstruction in Normal/Reverse

### DC Track Circuit (`asset_type_hex = "20"`)

**File:** `app/services/logics/track_circuit.py`

**Failure logic:** Relay voltage below threshold (track circuit not holding, train in section or equipment failure).

### Signals (`asset_type_hex = "10"` to `"13"`)

**File:** `app/services/logics/signal.py`

**Logic:** LED current and voltage monitoring. Out-of-range values indicate lamp failures.

### IPS - Integrated Power Supply (`asset_type_hex = "50"`)

**File:** `app/services/logics/ips.py`

**Logic:** Input/output voltage and current monitoring. Battery SOC monitoring.

---

## Business Rules for Alert Generation

1. **Must have para_id assigned to an asset** — `AssetParameter.is_assigned=True` and `asset_id` not NULL. Unassigned parameters are skipped.

2. **Must not be in maintenance mode** — checked via `AlertEngine._is_in_maintenance_mode()`. Maintenance mode is stored in-memory.

3. **Must have parameter configuration** — `param_config_service.get_parameter_config(para_id)` must return config with thresholds. Without config, no logic can run.

4. **Must pass deduplication** — same cause+asset must not already have an active alert (in-memory check + DB-level check).

5. **Must not have been recently cleared** — if the same cause was cleared < 1 hour ago, not regenerated.

---

## Alert Status Transitions

```
Created by AlertEngine
    ↓
"Active" (unacknowledged)
    ↓ (engineer views and clicks Acknowledge)
"Active" (acknowledged=True)
    ↓ (engineer fixes issue and clicks Clear)
"Cleared" (alert_status=Cleared, rectification_time=now)
```

**Note:** "Acknowledged" is a boolean flag, not a status transition. An alert can be Active+Acknowledged at the same time. "Cleared" is the status that marks resolution.

---

## Maintenance Mode and Alert Suppression

**What happens:** When an engineer activates maintenance mode for asset `"PT-101"`, the `AlertEngine` adds to its in-memory dict:
```python
self.maintenance_mode["456523AB:PT-101"] = to_time  # suppress until this datetime
```

**When telemetry arrives** for this asset, `_is_in_maintenance_mode()` returns `True` → no alerts evaluated.

**When maintenance ends** (time passes `to_time`), the dict entry is cleaned up on the next check.

**Limitation:** The in-memory state is lost on restart. A maintenance window set at 10:00 AM that runs until 12:00 PM will not suppress alerts after a server restart at 11:00 AM, even though the window is still active in the DB.

---

## KPIs Derived from Alerts

**System Health Score** (`app/routers/realtime.py`):
```
health_score = ((total_assets - failure_count) / total_assets) * 100
```

**MTTR (Mean Time to Repair):**
```
MTTR = average of (rectification_time - alert_time) for all Cleared alerts
```

**Prediction Accuracy:**
```
accuracy = (alerts with feedback='T' or 'PT') / (alerts with feedback) * 100
```

**Source:** `app/routers/realtime.py:204-219` and `app/routers/dashboard.py`.

---

## Alert Notification Chain

When an alert is generated, it currently propagates to:
1. **WebSocket clients** connected to `ws://.../ws/alerts/{station_code}` — instant push
2. **Dashboard REST API** — polled by clients not using WebSocket

**What's NOT implemented:**
- Email notifications
- SMS notifications
- Escalation (escalation fields exist in the model but escalation logic is not implemented)

The `AlertEvent` model has `escalation_level`, `escalated_at`, `escalated_to` columns — these are schema placeholders for a future escalation system.
