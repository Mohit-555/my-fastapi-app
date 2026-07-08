# RDPMS Codebase Structure & File Overview

This document provides a comprehensive map of the Remote Diagnostic and Predictive Maintenance System (RDPMS) codebase. It explains the purpose and responsibility of each directory and file in the project.

---

## 1. Project Root Directory

| File / Folder | Purpose / Responsibility |
| :--- | :--- |
| **`app/`** | The main application package containing all backend logic, models, API routers, and services. |
| **`alembic/`** | Contains database migration scripts and version histories. |
| **`scripts/`** | Contains auxiliary CLI scripts (e.g., `seed_data_validation.py` for startup checks). |
| **`scratch/`** | Contains developer-only utility scripts, API testers, and debugging files. |
| **`alembic.ini`** | Configuration file for database migrations with Alembic. |
| **`Dockerfile`** | Directives for building the container image of the FastAPI application. |
| **`docker-compose.yml`** | Configures multi-container runtime environments (App, Postgres, Redis). |
| **`requirements.txt`** | Lists all third-party Python dependencies (FastAPI, SQLAlchemy, psycopg2, etc.). |
| **`start.sh`** | Startup script executed by the Docker container (running migrations and starting Uvicorn). |
| **`.env`** | Stores local configuration secrets and database connection credentials. |
| **`.env.example`** | Template file showing required environment variables. |

---

## 2. The `app/` Directory

### Core Files
* **`main.py`**: The entrypoint of the FastAPI app. Configures middlewares, lifespan hooks (scheduler, background alert processor), runs database migrations, registers routing endpoints, and initializes seed validation.
* **`database.py`**: Initializes the database engine, manages connection pooling via SQLAlchemy, and defines application configuration settings.
* **`auth_utils.py`**: Contains helper functions for authentication, token generation (JWT), password hashing, and user privilege checking.
* **`constants.py`**: Stores application constants such as asset mappings, sensor bounds, and static definitions.
* **`rbac_defaults.py`**: Sets up Role-Based Access Control (RBAC) definitions and initializes default roles and permissions in the database.

---

### A. The `app/models/` Directory (Data Schemas)
* **`models.py`**: Contains SQLAlchemy database schemas, column relationships, composite indices (for performance query optimizations), and event hooks.
* **`database_models.py`**: Declares shared structural dataclasses and helper schemas.
* **`schemas.py`**: Defines Pydantic validation models for inbound request payloads and outbound API serialization (ensures strict schema validation).

---

### B. The `app/routers/` Directory (API Gateways)
This folder houses all routing endpoints, mapped logically by domain resources:

| Router | Purpose |
| :--- | :--- |
| **`auth.py`** | Handles user authentication, login tokens, refresh tokens, and session management. |
| **`admin.py`** | Exposes administrative settings, menu configurations, user roles, and database tables. |
| **`assets.py`** | CRUD endpoints for managing stations, assets, parameter configurations, and zones. |
| **`telemetry.py`** | Retrieves, queries, and aggregates telemetry metrics for dashboard visualization. |
| **`alerts.py`** | Handles CRUD actions, histories, updates, and feedback remarks on triggered alert events. |
| **`gateway.py`** | Handles high-throughput raw telemetry packet ingestion from IoT sensor gateways. |
| **`webhook.py`** | Listens for external vendor-specific alert webhooks (processes and records vendor alerts). |
| **`websocket.py`** | Manages WebSocket connections for live telemetry, live health, and live alert streams. |
| **`realtime.py`** | Fallback HTTP endpoints for checking current active/real-time telemetry parameters. |
| **`sse.py`** | Exposes Server-Sent Events (SSE) channels for push notifications. |
| **`dashboard.py`** | Aggregates and delivers cross-system metrics for the main visual dashboard. |
| **`monitoring.py`** | Exposes `/api/monitoring/health` health checks (reporting DB, Redis, and task statuses). |
| **`smms_telemetry.py`** | Ingests data updates originating from SMMS (railway maintenance client interface). |
| **`maintenance.py`** | Manages asset maintenance modes, schedules, and active downtime registers. |
| **`decode.py`** | Decodes incoming hex payload streams to readable telemetry parameters. |
| **`zones.py` / `divisions.py` / `stations.py`** | Direct CRUD APIs to manage geographical subdivisions and local station hubs. |
| **`equipment_room.py`** | CRUD endpoints to manage station equipment rooms. |
| **`statistics.py`** | Quick statistics and metrics retrieval. |

---

### C. The `app/services/` Directory (Business Logic Services)
* **`redis_service.py`**: Encapsulates Redis caching commands (storing/retrieving the latest parameters). Implements a dictionary-based fallback to support running without Redis.
* **`websocket_manager.py`**: Handles active WebSocket client states and broadcasts data. Implements periodic ping/pong loops to disconnect dead clients automatically.
* **`alert_processor.py`**: Manages the background alert execution queue. Evaluates telemetry inputs against rules and triggers alerts.
* **`alert_engine.py`**: Core algorithm verifying asset limits and conditions to determine if alert rules are violated.
* **`scheduler.py`**: Asynchronous task scheduler. Runs daily synchronization tasks (e.g., daily 2:00 AM asset syncs).
* **`smms_client.py`**: Client logic communicating with the external Railway SMMS API to keep local asset information synchronized.
* **`database_service.py`**: Custom query wrappers and helpers for transactions.
* **`parameter_config_service.py`**: Initializes, caches, and retrieves default parameter boundary configurations.
* **`statistics_service.py`**: Business logic behind dashboard report aggregations.

#### Subfolder: `app/services/logics/` (Asset Rules)
Contains rule evaluation classes for different asset categories:
* **`point_machine.py`**: Diagnostic rules verifying point machine current peaks and normal/reverse times.
* **`track_circuit.py`**: Rules checking track voltage levels.
* **`signal.py`**: Rules checking signal aspect configurations and current limits.
* **`ips.py`**: Rules for Integrated Power Supply (IPS) system status diagnostics.

---

## 3. Other Directories

### `alembic/versions/`
Stores auto-generated and custom database migration files. When you update database classes in `models.py`, you create a new file in this directory to align the live SQL tables.
* **Latest Revision (`e96aa4f26b5d`)**: Safely updates database tables to add missing columns (`vendor_code`, `escalated_to`, `last_sync`) and creates query indexes.

### `scripts/`
* **`seed_data_validation.py`**: Executed during application startup. Checks database schemas, registers missing core asset categories, and prints database integrity diagnostics.
