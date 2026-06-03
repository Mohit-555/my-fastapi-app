import json
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List

from app.database import get_db
from app.models.models import Gateway, Telemetry, Zone, Division, Station
from app.models.schemas import GatewayDataPayload, TelemetryResponse, GatewayResponse

router = APIRouter(prefix="/gateway", tags=["Gateway Telemetry"])


def _resolve_station_from_stngw_id(stngw_id: str, db: Session) -> int | None:
    """
    Decode the 8-char stngw_id and return the matching Station.id if found.
    stngw_id format: ZZ DD SS GG
      ZZ = zone_id_hex, DD = division_id_hex, SS = station_id_hex, GG = gateway number
    """
    if len(stngw_id) != 8:
        return None
    try:
        zone_hex    = stngw_id[0:2]
        div_hex     = stngw_id[2:4]
        station_hex = stngw_id[4:6]

        zone = db.query(Zone).filter(Zone.zone_id_hex == zone_hex).first()
        if not zone:
            return None

        division = db.query(Division).filter(
            Division.zone_id == zone.id,
            Division.division_id_hex == div_hex,
        ).first()
        if not division:
            return None

        station = db.query(Station).filter(
            Station.division_id == division.id,
            Station.station_id_hex == station_hex,
        ).first()

        return station.id if station else None
    except Exception:
        return None


@router.post("/data", status_code=202)
def receive_gateway_data(payload: GatewayDataPayload, db: Session = Depends(get_db)):
    """
    Receive telemetry JSON packet from a station gateway.

    Example payload:
    {
      "imei": "867409070579912",
      "stngw_id": "05011200",
      "parameters": [
        {
          "para_id": "50010A02",
          "prv": [220.5],
          "prt": ["04-11-2025 16:27:45.123"]
        }
      ]
    }

    On first sight of a stngw_id the gateway record is created and automatically
    linked to the correct Station by decoding the stngw_id.
    """
    stngw_id = payload.stngw_id.upper().strip()

    # Get or create gateway record
    gateway = db.query(Gateway).filter(Gateway.stngw_id == stngw_id).first()
    if not gateway:
        station_id = _resolve_station_from_stngw_id(stngw_id, db)
        gateway = Gateway(
            stngw_id=stngw_id,
            imei=payload.imei,
            station_id=station_id,
        )
        db.add(gateway)
        db.flush()
    else:
        # Update IMEI if it changed
        if gateway.imei != payload.imei:
            gateway.imei = payload.imei

        # Back-fill station_id if it was never set (e.g. station added after gateway)
        if gateway.station_id is None:
            gateway.station_id = _resolve_station_from_stngw_id(stngw_id, db)

    # Store each parameter reading
    saved_count = 0
    for param in payload.parameters:
        for i, value in enumerate(param.prv):
            timestamp = param.prt[i] if i < len(param.prt) else None
            record = Telemetry(
                gateway_id=gateway.id,
                para_id=param.para_id.upper(),
                prv=value,
                prt=timestamp,
                raw_payload=json.dumps({
                    "imei": payload.imei,
                    "stngw_id": stngw_id,
                    "para_id": param.para_id,
                    "prv": value,
                    "prt": timestamp,
                }),
            )
            db.add(record)
            saved_count += 1

    db.commit()
    return {
        "status": "accepted",
        "stngw_id": stngw_id,
        "station_id": gateway.station_id,
        "records_saved": saved_count,
    }


@router.get("/data/{stngw_id}", response_model=List[TelemetryResponse])
def get_gateway_telemetry(
    stngw_id: str,
    para_id: str = None,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    """
    Fetch stored telemetry readings for a gateway.
    Optionally filter by para_id.
    """
    gateway = db.query(Gateway).filter(
        Gateway.stngw_id == stngw_id.upper()
    ).first()

    if not gateway:
        raise HTTPException(
            status_code=404,
            detail=f"No gateway found with stngw_id '{stngw_id}'"
        )

    query = db.query(Telemetry).filter(Telemetry.gateway_id == gateway.id)

    if para_id:
        query = query.filter(Telemetry.para_id == para_id.upper())

    return (
        query
        .order_by(Telemetry.received_at.desc())
        .limit(limit)
        .all()
    )


@router.post("/{stngw_id}/link-station", response_model=GatewayResponse)
def link_gateway_station(stngw_id: str, db: Session = Depends(get_db)):
    """
    Manually trigger station auto-assignment for an existing gateway.
    Useful for back-filling gateways registered before their station was added.
    """
    gateway = db.query(Gateway).filter(
        Gateway.stngw_id == stngw_id.upper()
    ).first()
    if not gateway:
        raise HTTPException(status_code=404, detail=f"Gateway '{stngw_id}' not found")

    station_id = _resolve_station_from_stngw_id(stngw_id.upper(), db)
    if station_id is None:
        raise HTTPException(
            status_code=422,
            detail=f"Could not resolve a station for stngw_id '{stngw_id}'. "
                   "Make sure the zone, division, and station exist in the database."
        )

    gateway.station_id = station_id
    db.commit()
    db.refresh(gateway)
    return gateway


@router.get("/list", response_model=List[GatewayResponse])
def list_gateways(db: Session = Depends(get_db)):
    """List all registered gateways"""
    return db.query(Gateway).order_by(Gateway.stngw_id).all()


@router.get("/{stngw_id}/info", response_model=GatewayResponse)
def get_gateway_info(stngw_id: str, db: Session = Depends(get_db)):
    """Get gateway registration info"""
    gateway = db.query(Gateway).filter(
        Gateway.stngw_id == stngw_id.upper()
    ).first()
    if not gateway:
        raise HTTPException(status_code=404, detail=f"Gateway '{stngw_id}' not found")
    return gateway
