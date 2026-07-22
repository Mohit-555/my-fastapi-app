import os
from pathlib import Path

from alembic import command
from alembic.config import Config
from fastapi import Depends, FastAPI, Response
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST

from app.database import SessionLocal, engine
from app.auth_utils import get_current_user
from app.models.models import Base
from app.routers import zones, divisions, stations, gateway, decode, telemetry, assets, alerts, admin, equipment_room, maintenance, webhook, config, statistics, websocket, sse, realtime, smms_telemetry, dashboard, monitoring
from app.routers import auth
from app.rbac_defaults import ensure_default_menus, ensure_default_roles_users_and_permissions, ensure_default_zones, ensure_default_divisions, ensure_default_stations, ensure_default_asset_types, ensure_default_alert_causes, ensure_default_assets
from app.services.scheduler import scheduler
from app.services.redis_service import redis_service
from app.services.database_service import db_service
from app.services.alert_processor import alert_processor
from app.limiter import limiter
from slowapi.errors import RateLimitExceeded
from contextlib import asynccontextmanager
import asyncio
import logging

logger = logging.getLogger("main")

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


if os.getenv("SKIP_STARTUP_SEEDING") != "1":
    run_database_migrations()
    Base.metadata.create_all(bind=engine)
    if seed_zones_and_divisions:
        try:
            seed_zones_and_divisions()
        except Exception as e:
            print(f"Startup seeding warning: {e}")

    try:
        with SessionLocal() as db:
            ensure_default_zones(db)
            ensure_default_divisions(db)
            ensure_default_stations(db)
            ensure_default_menus(db)
            ensure_default_roles_users_and_permissions(db)
            ensure_default_asset_types(db)
            ensure_default_alert_causes(db)
            ensure_default_assets(db)
    except Exception as e:
        logger.warning(f"Startup default seeding warning (handled): {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Validating seed data...")
    try:
        from scripts.seed_data_validation import validate_seed_data, seed_missing_data
        validation_results = validate_seed_data()
        if validation_results.get("errors"):
            logger.warning("Seed data validation found errors. Attempting to seed missing data...")
            seed_missing_data()
            validation_results = validate_seed_data()
            if validation_results.get("errors"):
                logger.error(f"Seed data still has errors after seeding: {validation_results['errors']}")
    except Exception as e:
        logger.error(f"Failed to run seed data validation: {e}")

    await db_service.initialize()
    scheduler.start()
    alert_processor_task = asyncio.create_task(alert_processor.start())
    yield
    # Shutdown
    await alert_processor.stop()
    await alert_processor_task
    await scheduler.stop()
    await db_service.close()
    redis_service.close()


app = FastAPI(
    title="RDPMS API",
    description="Remote Diagnostic and Predictive Maintenance System — RDSO/SPN/257/2025",
    version="1.1.0",
    lifespan=lifespan,
)
app.state.limiter = limiter

@app.exception_handler(RateLimitExceeded)
async def rate_limit_exceeded_handler(request, exc):
    return JSONResponse(
        status_code=429,
        content={"status": False, "message": f"Rate limit exceeded: {exc.detail}"},
    )


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request, exc):
    return JSONResponse(
        status_code=exc.status_code,
        content={"status": False, "message": exc.detail},
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request, exc):
    errors = exc.errors()
    err_msgs = []
    for error in errors:
        loc = ".".join(str(x) for x in error.get("loc", []) if x != "body")
        msg = error.get("msg", "")
        err_msgs.append(f"{loc}: {msg}" if loc else msg)
    message = "Validation Error: " + ", ".join(err_msgs)
    return JSONResponse(
        status_code=422,
        content=jsonable_encoder({
            "status": False,
            "message": message,
            "detail": errors
        }),
    )


@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    import traceback
    traceback.print_exc()
    return JSONResponse(
        status_code=500,
        content={
            "status": False,
            "message": f"Internal Server Error: {str(exc)}"
        },
    )

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=".*",
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
app.include_router(telemetry.integration_router)
app.include_router(auth.router)
app.include_router(webhook.router)
app.include_router(websocket.router)
app.include_router(sse.router)
app.include_router(realtime.router)
app.include_router(smms_telemetry.router)
app.include_router(dashboard.router)
app.include_router(monitoring.router)
# ── Decode utilities ──────────────────────────────────────────────────────────
app.include_router(decode.router, dependencies=protected_route)
app.include_router(config.router, dependencies=protected_route)
app.include_router(statistics.router, dependencies=protected_route)


@app.get("/", tags=["Health"])
def root():
    return {"status": "ok", "message": "RDPMS API is running", "version": "1.1.0"}


@app.get("/metrics", tags=["Metrics"])
def metrics():
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)

