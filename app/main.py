import os
from pathlib import Path

from alembic import command
from alembic.config import Config
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.database import SessionLocal, engine
from app.auth_utils import get_current_user
from app.models.models import Base
from app.routers import zones, divisions, stations, gateway, decode, telemetry, assets, alerts, admin, equipment_room, maintenance
from app.routers import auth
from app.rbac_defaults import ensure_default_menus, ensure_default_roles_users_and_permissions, ensure_default_zones
try:
    from seed import seed as seed_zones_and_divisions
except ImportError:
    seed_zones_and_divisions = None


def run_database_migrations() -> None:
    if os.getenv("SKIP_AUTO_MIGRATIONS") == "1":
        return

    project_root = Path(__file__).resolve().parent.parent
    alembic_cfg = Config(str(project_root / "alembic.ini"))
    alembic_cfg.set_main_option("script_location", str(project_root / "alembic"))
    command.upgrade(alembic_cfg, "head")


run_database_migrations()
Base.metadata.create_all(bind=engine)
if seed_zones_and_divisions:
    try:
        seed_zones_and_divisions()
    except Exception as e:
        print(f"Startup seeding warning: {e}")

with SessionLocal() as db:
    ensure_default_zones(db)
    ensure_default_menus(db)
    ensure_default_roles_users_and_permissions(db)

app = FastAPI(
    title="RDPMS API",
    description="Remote Diagnostic and Predictive Maintenance System — RDSO/SPN/257/2025",
    version="1.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

protected_route = [Depends(get_current_user)]

# ── Reference data ────────────────────────────────────────────────────────────
app.include_router(zones.router, dependencies=protected_route)
app.include_router(divisions.router, dependencies=protected_route)
app.include_router(stations.router, dependencies=protected_route)

# ── Asset metadata & thresholds ───────────────────────────────────────────────
app.include_router(assets.router, dependencies=protected_route)

# ── Alerts summary, filters, and event records ────────────────────────────────
app.include_router(alerts.router, dependencies=protected_route)

# Add after the alerts router line:
app.include_router(admin.router, dependencies=protected_route)
app.include_router(equipment_room.router, dependencies=protected_route)
app.include_router(maintenance.router, dependencies=protected_route)
# ── Gateway ingestion ─────────────────────────────────────────────────────────
app.include_router(gateway.router, dependencies=protected_route)

# ── Telemetry query & live stream ─────────────────────────────────────────────
app.include_router(telemetry.router, dependencies=protected_route)
app.include_router(auth.router)
# ── Decode utilities ──────────────────────────────────────────────────────────
app.include_router(decode.router, dependencies=protected_route)


@app.get("/", tags=["Health"])
def root():
    return {"status": "ok", "message": "RDPMS API is running", "version": "1.1.0"}
