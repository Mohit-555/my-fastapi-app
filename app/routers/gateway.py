import json
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from typing import List

from app.database import get_db
from app.models.models import Gateway, Telemetry, Zone, Division, Station, AssetParameter
from app.models.schemas import GatewayDataPayload, TelemetryResponse, GatewayResponse

router = APIRouter(prefix="/gateway", tags=["Gateway Telemetry"])

# Gateway timestamp format per RDSO/SPN/257/2025 Annexure-A/B: DD-MM-YYYY HH:mm:ss.SSS
_GATEWAY_TS_FORMAT = "%d-%m-%Y %H:%M:%S.%f"


def _offset_event_timestamp(first_ts: str, sample_index: int, interval_ms: int) -> str:
    """
    Compute the timestamp of the Nth sample in an event-based (Annexure-B 5.10)
    burst, given the timestamp of the first sample and the fixed sampling
    interval. Returns the original string unchanged if it can't be parsed
    (e.g. unexpected format from a non-conforming gateway) so ingestion
    doesn't fail outright on a single malformed packet.
    """
    if sample_index == 0:
        return first_ts
    try:
        # Gateway sends milliseconds as 3 digits (.123); Python's %f wants 6.
        ts_str = first_ts.strip()
        if "." in ts_str:
            base, ms = ts_str.split(".")
            ts_str = f"{base}.{ms.ljust(6, '0')}"
        dt = datetime.strptime(ts_str, _GATEWAY_TS_FORMAT)
        dt += timedelta(milliseconds=interval_ms * sample_index)
        return dt.strftime("%d-%m-%Y %H:%M:%S.") + f"{dt.microsecond // 1000:03d}"
    except (ValueError, AttributeError):
        return first_ts


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

    Two packet types are defined in RDSO/SPN/257/2025 Annexure-B, both using
    the same para_id/prv/prt structure — they differ only in what `prt` is:

    Clause 5.9 — Fixed interval packet (every 5s, configurable), prt is an
    ARRAY of timestamps aligned 1:1 with prv:
    {
      "imei": "867409070579912",
      "stngw_id": "456523AB",
      "parameters": [
        {"para_id": "0001000C", "prv": [1.34, 1.35, 1.45, 1.46],
         "prt": ["04-11-2025 16:27:45.123", "04-11-2025 16:27:45.125",
                  "04-11-2025 16:27:45.127", "04-11-2025 16:27:45.130"]}
      ]
    }

    Clause 5.10 — Event-based packet (sent after a Point Machine/ELB
    operation completes, samples taken every 20ms/configurable), prt is a
    SINGLE timestamp string for the first sample only — later sample
    timestamps are computed by adding the sampling interval:
    {
      "imei": "867409070579912",
      "stngw_id": "456523AB",
      "parameters": [
        {"para_id": "0001000C", "prv": [1.34, 1.35, 1.45, 1.46],
         "prt": "04-11-2025 16:27:45.123"}
      ]
    }

    A bare `raw` array with no para_id (as seen in some vendor samples) is
    NOT part of Annexure-B 5.9/5.10 — such entries are stored flagged with a
    warning rather than guessed at; see the vendor before relying on this.

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

    # Default sampling interval for event-based packets (Annexure-B 5.10).
    # Spec default is 20ms; treat as configurable per station/asset later if needed.
    EVENT_SAMPLE_INTERVAL_MS = 20

    # ── Idempotency check ──────────────────────────────────────────────────────
    # Gateways/ISP may redeliver the same packet (e.g. MQTT at-least-once
    # delivery with no ack received, or a network retry). A reading is
    # considered a duplicate if this gateway has already stored the exact
    # same (para_id, prt, prv) combination. This is an app-level check —
    # not airtight against concurrent duplicate requests landing at the same
    # instant, but sufficient for retry/redelivery duplicates, which is the
    # common case. A DB-level unique constraint + upsert is the hardening
    # step once ingestion volume/concurrency grows.
    candidate_para_ids = {
        p.para_id.upper() for p in payload.parameters if p.para_id is not None
    }
    existing_keys: set[tuple[str, str | None, float | None]] = set()
    if candidate_para_ids:
        existing_rows = (
            db.query(Telemetry.para_id, Telemetry.prt, Telemetry.prv)
            .filter(
                Telemetry.gateway_id == gateway.id,
                Telemetry.para_id.in_(candidate_para_ids),
            )
            .all()
        )
        existing_keys = {(r.para_id, r.prt, r.prv) for r in existing_rows}

    # ── Asset-parameter auto-discovery ──────────────────────────────────────────
    # On first sight of a para_id, create an unassigned AssetParameter row so
    # it shows up in the admin "Configure Slave" screen for an engineer to
    # link to an asset and set its prloc (location box). Per RDSO Annexure-A/B,
    # prloc is defined per-parameter, not per-asset, so this mapping has to
    # live at the para_id level rather than on Asset.location alone. Ingestion
    # is never blocked on this — the row is created unassigned and telemetry
    # keeps flowing regardless of whether anyone has assigned it yet.
    if candidate_para_ids:
        known_para_ids = {
            r.para_id for r in
            db.query(AssetParameter.para_id)
            .filter(AssetParameter.para_id.in_(candidate_para_ids))
            .all()
        }
        for pid in candidate_para_ids - known_para_ids:
            db.add(AssetParameter(para_id=pid, asset_id=None, prloc=None, is_assigned=False))
        if candidate_para_ids - known_para_ids:
            db.flush()

    # Store each parameter reading
    saved_count = 0
    duplicate_count = 0

    for param in payload.parameters:
        if param.raw_unattributed is not None:
            # Non-spec fallback: a bare `raw` array with no para_id was sent.
            # Annexure-B 5.10 does not define this shape — flag it rather
            # than guess which para_id it belongs to. Not deduplicated since
            # there is no para_id/prt to key on reliably.
            record = Telemetry(
                gateway_id=gateway.id,
                para_id=None,
                prv=None,
                prt=None,
                raw_payload=json.dumps({
                    "imei": payload.imei,
                    "stngw_id": stngw_id,
                    "warning": "raw array received with no para_id — not a recognized Annexure-B 5.9/5.10 shape",
                    "raw": param.raw_unattributed,
                }),
            )
            db.add(record)
            saved_count += 1
            continue

        para_id_upper = param.para_id.upper()
        is_event_based = isinstance(param.prt, str)  # 5.10: single timestamp string

        for i, value in enumerate(param.prv):
            if is_event_based:
                # Clause 5.10: prt is the timestamp of the FIRST sample only.
                # Later samples' timestamps = first_timestamp + (i * sampling interval).
                timestamp = _offset_event_timestamp(param.prt, i, EVENT_SAMPLE_INTERVAL_MS)
            else:
                # Clause 5.9: prt is an array aligned 1:1 with prv.
                timestamp = param.prt[i] if i < len(param.prt) else None

            dedup_key = (para_id_upper, timestamp, value)
            if dedup_key in existing_keys:
                duplicate_count += 1
                continue
            existing_keys.add(dedup_key)  # guard against duplicates within the same payload too

            record = Telemetry(
                gateway_id=gateway.id,
                para_id=para_id_upper,
                prv=value,
                prt=timestamp,
                raw_payload=json.dumps({
                    "imei": payload.imei,
                    "stngw_id": stngw_id,
                    "para_id": param.para_id,
                    "prv": value,
                    "prt": timestamp,
                    "packet_type": "event_based_5_10" if is_event_based else "fixed_interval_5_9",
                }),
            )
            db.add(record)
            saved_count += 1

    db.flush()
    try:
        db.commit()
    except IntegrityError:
        # Only reachable once the DB-level unique constraint
        # (uq_telemetry_gateway_para_prt_prv) is in place. Means a duplicate
        # slipped past the app-level check above — almost always a
        # concurrent retry landing at the same instant. Roll back this
        # request's writes; the original delivery already succeeded.
        db.rollback()
        return {
            "status": "accepted",
            "stngw_id": stngw_id,
            "station_id": gateway.station_id,
            "records_saved": 0,
            "duplicates_skipped": saved_count + duplicate_count,
            "note": "Entire batch rolled back — a concurrent duplicate delivery was detected at the database level.",
        }
    return {
        "status": "accepted",
        "stngw_id": stngw_id,
        "station_id": gateway.station_id,
        "records_saved": saved_count,
        "duplicates_skipped": duplicate_count,
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
