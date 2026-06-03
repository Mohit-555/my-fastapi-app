from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.database import engine
from app.models.models import Base
from app.routers import zones, divisions, stations, gateway, decode, telemetry, assets

Base.metadata.create_all(bind=engine)

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

# ── Reference data ────────────────────────────────────────────────────────────
app.include_router(zones.router)
app.include_router(divisions.router)
app.include_router(stations.router)

# ── Asset metadata & thresholds ───────────────────────────────────────────────
app.include_router(assets.router)

# ── Gateway ingestion ─────────────────────────────────────────────────────────
app.include_router(gateway.router)

# ── Telemetry query & live stream ─────────────────────────────────────────────
app.include_router(telemetry.router)

# ── Decode utilities ──────────────────────────────────────────────────────────
app.include_router(decode.router)


@app.get("/", tags=["Health"])
def root():
    return {"status": "ok", "message": "RDPMS API is running", "version": "1.1.0"}
