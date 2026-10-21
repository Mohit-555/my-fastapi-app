import json
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func, or_, distinct
from typing import List, Optional, Any, Union

from app.database import get_db
from app.services.websocket_manager import safe_notify_dashboard
from app.models.models import Gateway, Telemetry, Zone, Division, Station, AssetParameter, User, SlaveCard, Asset, RTU
from app.models.schemas import (
    GatewayDataPayload,
    TelemetryResponse,
    GatewayResponse,
    GatewayListResponse,
    GatewayCreate,
    GatewayUpdate,
    LinkStationRequest,
    GatewayHierarchyPreviewResponse,
    StandardResponse,
)
from app.auth_utils import get_current_user

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


def _decode_and_resolve_hierarchy(stngw_id: str, db: Session) -> dict:
    """
    Decodes an 8-char stngw_id (ZZ DD SS GG) and resolves the database hierarchy:
    Zone -> Division -> Station -> Gateway Sequence Number.
    """
    cleaned = (stngw_id or "").strip().upper()
    if len(cleaned) != 8 or not all(c in "0123456789ABCDEF" for c in cleaned):
        return {
            "stngw_id": cleaned,
            "zone_hex": "",
            "division_hex": "",
            "station_hex": "",
            "gateway_number_hex": "",
            "gateway_number": 0,
            "is_valid": False,
            "can_register": False,
            "resolved_station_id": None,
            "zone": None,
            "division": None,
            "station": None,
            "error": "Gateway ID must be exactly 8 hexadecimal characters (0-9, A-F)",
        }

    zone_hex = cleaned[0:2]
    div_hex = cleaned[2:4]
    station_hex = cleaned[4:6]
    gw_num_hex = cleaned[6:8]
    gw_num = int(gw_num_hex, 16)

    zone = db.query(Zone).filter(Zone.zone_id_hex == zone_hex).first()
    if not zone:
        return {
            "stngw_id": cleaned,
            "zone_hex": zone_hex,
            "division_hex": div_hex,
            "station_hex": station_hex,
            "gateway_number_hex": gw_num_hex,
            "gateway_number": gw_num,
            "is_valid": False,
            "can_register": False,
            "resolved_station_id": None,
            "zone": None,
            "division": None,
            "station": None,
            "error": f"Zone with hex code '{zone_hex}' does not exist in the database.",
        }

    zone_info = {
        "id": zone.id,
        "code": zone.zone_code,
        "name": zone.zone_name,
        "hex": zone_hex,
    }

    division = db.query(Division).filter(
        Division.zone_id == zone.id,
        Division.division_id_hex == div_hex,
    ).first()
    if not division:
        return {
            "stngw_id": cleaned,
            "zone_hex": zone_hex,
            "division_hex": div_hex,
            "station_hex": station_hex,
            "gateway_number_hex": gw_num_hex,
            "gateway_number": gw_num,
            "is_valid": False,
            "can_register": False,
            "resolved_station_id": None,
            "zone": zone_info,
            "division": None,
            "station": None,
            "error": f"Division with hex code '{div_hex}' does not exist under Zone '{zone.zone_code}'.",
        }

    div_info = {
        "id": division.id,
        "code": division.division_code,
        "name": division.division_name,
        "hex": div_hex,
    }

    station = db.query(Station).filter(
        Station.division_id == division.id,
        Station.station_id_hex == station_hex,
    ).first()
    if not station:
        return {
            "stngw_id": cleaned,
            "zone_hex": zone_hex,
            "division_hex": div_hex,
            "station_hex": station_hex,
            "gateway_number_hex": gw_num_hex,
            "gateway_number": gw_num,
            "is_valid": False,
            "can_register": False,
            "resolved_station_id": None,
            "zone": zone_info,
            "division": div_info,
            "station": None,
            "error": f"Station with hex code '{station_hex}' does not exist under Division '{division.division_code}'.",
        }

    station_info = {
        "id": station.id,
        "code": station.station_code,
        "name": station.station_name,
        "hex": station_hex,
    }

    return {
        "stngw_id": cleaned,
        "zone_hex": zone_hex,
        "division_hex": div_hex,
        "station_hex": station_hex,
        "gateway_number_hex": gw_num_hex,
        "gateway_number": gw_num,
        "is_valid": True,
        "can_register": True,
        "resolved_station_id": station.id,
        "zone": zone_info,
        "division": div_info,
        "station": station_info,
        "error": None,
    }


def _resolve_station_from_stngw_id(stngw_id: str, db: Session) -> int | None:
    """
    Decode the 8-char stngw_id and return the matching Station.id if found.
    stngw_id format: ZZ DD SS GG
      ZZ = zone_id_hex, DD = division_id_hex, SS = station_id_hex, GG = gateway number
    """
    try:
        res = _decode_and_resolve_hierarchy(stngw_id, db)
        return res.get("resolved_station_id")
    except Exception:
        return None


def _check_stngw_id_access(stngw_id: str, user: User, db: Session, action: str = "read") -> Gateway | None:
    """Verify user has access to a gateway/master card (by stngw_id) and check role levels."""
    if action == "write" and user.role and user.role.level >= 7:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Guest and Auditor roles are not permitted to perform this action."
        )

    gateway = db.query(Gateway).filter(Gateway.stngw_id == stngw_id.upper()).first()
    
    # Check division/zone access
    station_id = gateway.station_id if gateway else None
    if station_id is None:
        # Try to resolve station from stngw_id
        station_id = _resolve_station_from_stngw_id(stngw_id.upper(), db)
        
    if station_id is not None:
        station = db.query(Station).filter(Station.id == station_id).first()
        if not station:
            # If the resolved station isn't in DB, division/zone users shouldn't access it
            if user.division_id is not None or user.zone_id is not None:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Access denied: Station associated with this gateway not found."
                )
        else:
            if user.division_id is not None:
                if station.division_id != user.division_id:
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="Access denied: User division does not match the gateway station division."
                    )
            if user.zone_id is not None:
                division = db.query(Division).filter(Division.id == station.division_id).first()
                if not division or division.zone_id != user.zone_id:
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="Access denied: User zone does not match the gateway station zone."
                    )
    else:
        # Gateway has no station and could not resolve one
        if user.division_id is not None or user.zone_id is not None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied: Non-admin users cannot access unassigned gateways."
            )
            
    return gateway



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
        res_data = {
            "status": "accepted",
            "stngw_id": stngw_id,
            "station_id": gateway.station_id,
            "records_saved": 0,
            "duplicates_skipped": saved_count + duplicate_count,
            "note": "Entire batch rolled back — a concurrent duplicate delivery was detected at the database level.",
        }
        return {
            **res_data,
            "status": True,
            "message": "Success",
            "data": res_data,
        }
    if saved_count > 0:
        safe_notify_dashboard("telemetry_ingested")

    res_data = {
        "status": "accepted",
        "stngw_id": stngw_id,
        "station_id": gateway.station_id,
        "records_saved": saved_count,
        "duplicates_skipped": duplicate_count,
    }
    return {
        **res_data,
        "status": True,
        "message": "Success",
        "data": res_data,
    }


@router.get("/data/{stngw_id}", response_model=StandardResponse[List[TelemetryResponse]])
def get_gateway_telemetry(
    stngw_id: str,
    para_id: str = None,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Fetch stored telemetry readings for a gateway.
    Optionally filter by para_id.
    """
    gateway = _check_stngw_id_access(stngw_id, current_user, db, action="read")

    if not gateway:
        raise HTTPException(
            status_code=404,
            detail=f"No gateway found with stngw_id '{stngw_id}'"
        )

    query = db.query(Telemetry).filter(Telemetry.gateway_id == gateway.id)

    if para_id:
        query = query.filter(Telemetry.para_id == para_id.upper())

    rows = (
        query
        .order_by(Telemetry.received_at.desc())
        .limit(limit)
        .all()
    )
    return {
        "status": True,
        "message": "Success",
        "data": rows
    }


@router.get("/preview/{stngw_id}", response_model=StandardResponse[GatewayHierarchyPreviewResponse])
@router.get("/validate-hierarchy/{stngw_id}", response_model=StandardResponse[GatewayHierarchyPreviewResponse])
def preview_gateway_hierarchy(
    stngw_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Decodes and validates the 8-character stngw_id hierarchy in real-time.
    Returns decoded Zone, Division, Station, and Gateway sequence number.
    Does not write to the database.
    """
    res = _decode_and_resolve_hierarchy(stngw_id, db)
    return {
        "status": res["is_valid"],
        "message": "Hierarchy resolved successfully" if res["is_valid"] else (res["error"] or "Resolution failed"),
        "data": res
    }


@router.post("/", response_model=StandardResponse[GatewayResponse], status_code=status.HTTP_201_CREATED)
def create_gateway(
    payload: GatewayCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Manually provision/register a new Station Gateway.
    Strictly validates stngw_id (ZZ DD SS GG) or auto-derives it from (station_id, gateway_number)
    and resolves the station hierarchy (Zone -> Division -> Station) from the database.
    """
    raw_stngw_id = payload.stngw_id.upper().strip() if payload.stngw_id else None
    rtu_id_val = payload.rtu_id

    # If stngw_id is not directly provided, derive it from station and gateway_number
    if not raw_stngw_id:
        stn_id = payload.station_id
        if not stn_id and rtu_id_val:
            rtu_rec = db.query(RTU).filter(RTU.id == rtu_id_val).first()
            if rtu_rec:
                stn_id = rtu_rec.station_id

        if not stn_id:
            raise HTTPException(
                status_code=400,
                detail="Either 'stngw_id' or 'station_id' (or 'rtu_id') with 'gateway_number' must be provided."
            )

        station_rec = db.query(Station).options(
            joinedload(Station.division).joinedload(Division.zone)
        ).filter(Station.id == stn_id).first()
        if not station_rec or not station_rec.division or not station_rec.division.zone:
            raise HTTPException(
                status_code=400,
                detail=f"Station hierarchy (Zone/Division/Station) incomplete for station ID {stn_id}."
            )

        gw_num = payload.gateway_number
        if gw_num is None:
            # Auto-assign next sequence number for this station
            existing_gws = db.query(Gateway.stngw_id).filter(Gateway.station_id == stn_id).all()
            seqs = []
            for (g_id,) in existing_gws:
                if len(g_id) == 8:
                    try:
                        seqs.append(int(g_id[6:8], 16))
                    except ValueError:
                        pass
            next_seq = (max(seqs) + 1) if seqs else 1
            gw_hex = f"{next_seq:02X}"
        elif isinstance(gw_num, int):
            gw_hex = f"{gw_num:02X}"
        else:
            gw_str = str(gw_num).strip().upper()
            if len(gw_str) <= 2 and all(c in "0123456789ABCDEF" for c in gw_str):
                gw_hex = gw_str.zfill(2)
            elif gw_str.isdigit():
                gw_hex = f"{int(gw_str):02X}"
            else:
                raise HTTPException(status_code=400, detail="Invalid gateway_number format. Must be hex (01-FF) or integer.")

        zz = (station_rec.division.zone.zone_id_hex or "00").zfill(2).upper()
        dd = (station_rec.division.division_id_hex or "00").zfill(2).upper()
        ss = (station_rec.station_id_hex or "00").zfill(2).upper()
        stngw_id = f"{zz}{dd}{ss}{gw_hex}"
    else:
        stngw_id = raw_stngw_id

    # 1. Prevent duplicates (stngw_id is unique across Indian Railways)
    existing = db.query(Gateway).filter(Gateway.stngw_id == stngw_id).first()
    if existing:
        raise HTTPException(
            status_code=400,
            detail=f"Gateway with ID '{stngw_id}' already exists."
        )

    # 2. Prevent duplicate IMEI if provided
    imei_val = payload.imei.strip() if payload.imei else None
    if imei_val:
        existing_imei = db.query(Gateway).filter(Gateway.imei == imei_val).first()
        if existing_imei:
            raise HTTPException(
                status_code=400,
                detail=f"Gateway with IMEI '{imei_val}' already exists (Gateway ID '{existing_imei.stngw_id}')."
            )

    # 3. Hierarchy validation and station resolution
    hierarchy = _decode_and_resolve_hierarchy(stngw_id, db)
    if not hierarchy["can_register"] or not hierarchy["resolved_station_id"]:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot register gateway: {hierarchy['error']}"
        )

    resolved_station_id = hierarchy["resolved_station_id"]
    if payload.station_id and payload.station_id != resolved_station_id:
        raise HTTPException(
            status_code=400,
            detail=f"Provided station_id {payload.station_id} conflicts with the decoded station hierarchy {resolved_station_id} for '{stngw_id}'."
        )

    # Validate RTU belongs to this station if provided
    if rtu_id_val:
        rtu_check = db.query(RTU).filter(RTU.id == rtu_id_val).first()
        if rtu_check and rtu_check.station_id != resolved_station_id:
            raise HTTPException(
                status_code=400,
                detail=f"RTU #{rtu_id_val} does not belong to the resolved station #{resolved_station_id}."
            )

    # 4. Create Gateway row
    gateway = Gateway(
        stngw_id=stngw_id,
        imei=imei_val,
        station_id=resolved_station_id,
        rtu_id=rtu_id_val,
        mtls_cn=payload.mtls_cn.strip() if payload.mtls_cn else None,
    )
    db.add(gateway)
    db.commit()
    db.refresh(gateway)

    safe_notify_dashboard("gateway_created")

    return {
        "status": True,
        "message": "Gateway added successfully",
        "data": gateway
    }


@router.post("/{stngw_id}/link-station", response_model=StandardResponse[GatewayResponse])
def link_gateway_station(
    stngw_id: str,
    payload: Optional[LinkStationRequest] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Link or re-link a gateway to its authoritative station derived from stngw_id,
    and optionally update its IMEI.
    Validates that the target station matches the encoded hierarchy.
    """
    clean_stngw_id = stngw_id.upper().strip()
    gateway = _check_stngw_id_access(clean_stngw_id, current_user, db, action="write")
    if not gateway:
        raise HTTPException(status_code=404, detail=f"Gateway '{clean_stngw_id}' not found")

    hierarchy = _decode_and_resolve_hierarchy(clean_stngw_id, db)
    if hierarchy["can_register"] and hierarchy["resolved_station_id"]:
        resolved_station_id = hierarchy["resolved_station_id"]
    elif gateway.station_id is not None:
        resolved_station_id = (payload and payload.station_id) or gateway.station_id
    else:
        raise HTTPException(
            status_code=422,
            detail=f"Could not resolve station for '{clean_stngw_id}': {hierarchy['error']}"
        )

    if payload and payload.station_id and hierarchy.get("can_register") and resolved_station_id and payload.station_id != resolved_station_id:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot link gateway '{clean_stngw_id}' to station ID {payload.station_id}. It is encoded to station ID {resolved_station_id} ({hierarchy['station']['name']})."
        )

    # Check and update IMEI if provided
    if payload and payload.imei is not None:
        new_imei = payload.imei.strip() if payload.imei else None
        if new_imei:
            existing_imei = db.query(Gateway).filter(
                Gateway.imei == new_imei,
                Gateway.stngw_id != clean_stngw_id
            ).first()
            if existing_imei:
                raise HTTPException(
                    status_code=400,
                    detail=f"Gateway with IMEI '{new_imei}' already exists ({existing_imei.stngw_id})."
                )
            gateway.imei = new_imei
        else:
            gateway.imei = None

    gateway.station_id = resolved_station_id
    db.commit()
    db.refresh(gateway)
    safe_notify_dashboard("gateway_updated")
    return {
        "status": True,
        "message": "Gateway updated successfully" if (payload and payload.imei is not None) else "Station linked successfully",
        "data": gateway
    }


@router.put("/{stngw_id}", response_model=StandardResponse[GatewayResponse])
def update_gateway(
    stngw_id: str,
    payload: GatewayUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Update gateway configuration (IMEI and/or station link).
    """
    clean_stngw_id = stngw_id.upper().strip()
    gateway = _check_stngw_id_access(clean_stngw_id, current_user, db, action="write")
    if not gateway:
        raise HTTPException(status_code=404, detail=f"Gateway '{clean_stngw_id}' not found")

    target_stngw_id = payload.stngw_id.upper().strip() if payload.stngw_id else clean_stngw_id

    # If updating stngw_id to a new value, verify uniqueness
    if target_stngw_id != gateway.stngw_id:
        existing_gw = db.query(Gateway).filter(Gateway.stngw_id == target_stngw_id).first()
        if existing_gw:
            raise HTTPException(
                status_code=400,
                detail=f"Gateway with ID '{target_stngw_id}' already exists."
            )

    hierarchy = _decode_and_resolve_hierarchy(target_stngw_id, db)
    if hierarchy["can_register"] and hierarchy["resolved_station_id"]:
        resolved_station_id = hierarchy["resolved_station_id"]
    elif gateway.station_id is not None:
        resolved_station_id = payload.station_id or gateway.station_id
    else:
        raise HTTPException(
            status_code=422,
            detail=f"Could not resolve station for '{target_stngw_id}': {hierarchy['error']}"
        )

    if payload.station_id and hierarchy.get("can_register") and resolved_station_id and payload.station_id != resolved_station_id:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot link gateway '{target_stngw_id}' to station ID {payload.station_id}. It is encoded to station ID {resolved_station_id} ({hierarchy['station']['name']})."
        )

    if payload.imei is not None:
        new_imei = payload.imei.strip() if payload.imei else None
        if new_imei:
            existing_imei = db.query(Gateway).filter(
                Gateway.imei == new_imei,
                Gateway.stngw_id != gateway.stngw_id
            ).first()
            if existing_imei:
                raise HTTPException(
                    status_code=400,
                    detail=f"Gateway with IMEI '{new_imei}' already exists ({existing_imei.stngw_id})."
                )
            gateway.imei = new_imei
        else:
            gateway.imei = None

    # Update stngw_id if changed (cascades to assets via foreign key ON UPDATE CASCADE)
    if target_stngw_id != gateway.stngw_id:
        gateway.stngw_id = target_stngw_id

    if payload.station_id or gateway.station_id is None:
        gateway.station_id = resolved_station_id

    if payload.rtu_id is not None:
        gateway.rtu_id = payload.rtu_id if payload.rtu_id > 0 else None

    db.commit()
    db.refresh(gateway)
    safe_notify_dashboard("gateway_updated")
    return {
        "status": True,
        "message": "Gateway updated successfully",
        "data": gateway
    }


@router.delete("/{stngw_id}", response_model=StandardResponse[Optional[dict]])
def delete_gateway(
    stngw_id: str,
    force: bool = Query(False, description="Force delete gateway and remove associated dependencies"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Safely delete a registered gateway if it has no dependent slave cards, assets, or telemetry.
    If force=True, cascade-deletes or unlinks associated dependencies before deleting.
    """
    clean_stngw_id = stngw_id.upper().strip()
    gateway = _check_stngw_id_access(clean_stngw_id, current_user, db, action="write")
    if not gateway:
        raise HTTPException(status_code=404, detail=f"Gateway '{clean_stngw_id}' not found")

    # Dependency check: Slave Cards
    slave_cards_count = db.query(SlaveCard).filter(SlaveCard.gateway_id == gateway.id).count()

    # Dependency check: Assets
    assets_count = db.query(Asset).filter(Asset.station_gateway_id == gateway.stngw_id).count()

    # Dependency check: Telemetry
    telemetry_count = db.query(Telemetry).filter(Telemetry.gateway_id == gateway.id).count()

    reasons = []
    if slave_cards_count > 0:
        reasons.append(f"{slave_cards_count} slave card(s)")
    if assets_count > 0:
        reasons.append(f"{assets_count} assigned asset(s)")
    if telemetry_count > 0:
        reasons.append(f"{telemetry_count} telemetry record(s)")

    if reasons and not force:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot delete gateway '{clean_stngw_id}': It has associated {', '.join(reasons)}. Please remove these dependencies before deleting the gateway."
        )

    if force:
        from app.models.models import AlertEvent, MaintenanceMode
        dep_assets = db.query(Asset).filter(Asset.station_gateway_id == gateway.stngw_id).all()
        for ast in dep_assets:
            db.query(AlertEvent).filter(AlertEvent.asset_id == ast.id).update({"asset_id": None}, synchronize_session=False)
            db.query(MaintenanceMode).filter(MaintenanceMode.asset_id == ast.id).update({"asset_id": None}, synchronize_session=False)
            db.query(AssetParameter).filter(AssetParameter.asset_id == ast.id).delete(synchronize_session=False)
            db.delete(ast)

        dep_slave_cards = db.query(SlaveCard).filter(SlaveCard.gateway_id == gateway.id).all()
        for sc in dep_slave_cards:
            db.query(AssetParameter).filter(AssetParameter.slave_card_id == sc.id).delete(synchronize_session=False)
            db.delete(sc)

        db.query(Telemetry).filter(Telemetry.gateway_id == gateway.id).delete(synchronize_session=False)
        db.flush()

    db.delete(gateway)
    db.commit()
    safe_notify_dashboard("gateway_deleted")
    return {
        "status": True,
        "message": f"Gateway '{clean_stngw_id}' deleted successfully",
        "data": None
    }


@router.get("/list", response_model=StandardResponse[GatewayListResponse])
def list_gateways(
    zone_id: Optional[int] = Query(None, description="Filter by Zone ID"),
    division_id: Optional[int] = Query(None, description="Filter by Division ID"),
    station_id: Optional[int] = Query(None, description="Filter by Station ID"),
    rtu_id: Optional[int] = Query(None, description="Filter by RTU ID"),
    zone: Optional[str] = Query(None, description="Filter by Zone Code or Name"),
    division: Optional[str] = Query(None, description="Filter by Division Code or Name"),
    station: Optional[str] = Query(None, description="Filter by Station Code or Name"),
    rtu: Optional[str] = Query(None, description="Filter by RTU Name"),
    stngw_id: Optional[str] = Query(None, description="Filter by Gateway ID (stngw_id)"),
    status: Optional[str] = Query(None, description="Filter by status: Linked / Unlinked"),
    search: Optional[str] = Query(None, description="Search across Gateway ID, IMEI, or Station Code"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List all registered gateways with comprehensive filtering and pagination."""
    cur_page = int(page) if isinstance(page, int) or (isinstance(page, str) and page.isdigit()) else 1
    cur_page_size = int(page_size) if isinstance(page_size, int) or (isinstance(page_size, str) and page_size.isdigit()) else 50

    q = db.query(Gateway).options(
        joinedload(Gateway.station).joinedload(Station.division).joinedload(Division.zone),
        joinedload(Gateway.slave_cards),
        joinedload(Gateway.rtu)
    )

    joined_station = False
    joined_division = False
    joined_zone = False

    def join_station():
        nonlocal q, joined_station
        if not joined_station:
            q = q.join(Station, Gateway.station_id == Station.id)
            joined_station = True

    def join_division():
        nonlocal q, joined_division
        join_station()
        if not joined_division:
            q = q.join(Division, Station.division_id == Division.id)
            joined_division = True

    def join_zone():
        nonlocal q, joined_zone
        join_division()
        if not joined_zone:
            q = q.join(Zone, Division.zone_id == Zone.id)
            joined_zone = True

    # Role-based scoping
    if current_user.division_id is not None:
        join_station()
        q = q.filter(Station.division_id == current_user.division_id)
    elif current_user.zone_id is not None:
        join_division()
        q = q.filter(Division.zone_id == current_user.zone_id)

    # Filter by IDs
    if isinstance(station_id, int) and station_id != 0:
        q = q.filter(Gateway.station_id == station_id)

    if isinstance(division_id, int) and division_id != 0:
        join_station()
        q = q.filter(Station.division_id == division_id)

    if isinstance(zone_id, int) and zone_id != 0:
        join_division()
        q = q.filter(Division.zone_id == zone_id)

    if isinstance(rtu_id, int) and rtu_id != 0:
        q = q.filter(Gateway.rtu_id == rtu_id)

    if isinstance(rtu, str) and rtu.strip() and rtu.strip().upper() != "ALL":
        q = q.join(RTU, Gateway.rtu_id == RTU.id)
        rtu_term = rtu.strip().upper()
        q = q.filter(or_(func.upper(RTU.rtu_name) == rtu_term, func.upper(RTU.rtu_code) == rtu_term))

    # Filter by codes / names
    if isinstance(station, str) and station.strip() and station.strip().upper() != "ALL":
        join_station()
        stn_term = station.strip().upper()
        q = q.filter(or_(func.upper(Station.station_code) == stn_term, func.upper(Station.station_name) == stn_term))

    if isinstance(division, str) and division.strip() and division.strip().upper() != "ALL":
        join_division()
        div_term = division.strip().upper()
        q = q.filter(or_(func.upper(Division.division_code) == div_term, func.upper(Division.division_name) == div_term))

    if isinstance(zone, str) and zone.strip() and zone.strip().upper() != "ALL":
        join_zone()
        zn_term = zone.strip().upper()
        q = q.filter(or_(func.upper(Zone.zone_code) == zn_term, func.upper(Zone.zone_name) == zn_term))

    if isinstance(stngw_id, str) and stngw_id.strip() and stngw_id.strip().upper() != "ALL":
        q = q.filter(Gateway.stngw_id.ilike(f"%{stngw_id.strip()}%"))

    if isinstance(status, str) and status.strip() and status.strip().upper() != "ALL":
        st_val = status.strip().lower()
        if st_val == "linked":
            q = q.filter(Gateway.station_id.isnot(None))
        elif st_val == "unlinked":
            q = q.filter(Gateway.station_id.is_(None))

    if isinstance(search, str) and search.strip():
        join_station()
        term = f"%{search.strip()}%"
        q = q.filter(or_(
            Gateway.stngw_id.ilike(term),
            Gateway.imei.ilike(term),
            Station.station_code.ilike(term),
            Station.station_name.ilike(term),
        ))

    total = q.count()
    total_pages = (total + cur_page_size - 1) // cur_page_size if total else 0
    offset = (cur_page - 1) * cur_page_size
    rows = q.order_by(Gateway.stngw_id).offset(offset).limit(cur_page_size).all()
    
    row_ids = [r.id for r in rows if r.id is not None]
    active_gw_ids = set()
    if row_ids:
        active_gw_ids = set(
            x[0] for x in db.query(distinct(Telemetry.gateway_id))
            .filter(Telemetry.gateway_id.in_(row_ids))
            .all()
        )
    for r in rows:
        r.has_telemetry = r.id in active_gw_ids

    return {
        "status": True,
        "message": "Success",
        "data": {
            "total": total,
            "page": cur_page,
            "page_size": cur_page_size,
            "total_pages": total_pages,
            "rows": rows
        }
    }


@router.get("/{stngw_id}/info", response_model=StandardResponse[GatewayResponse])
def get_gateway_info(
    stngw_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get gateway registration info"""
    gateway = _check_stngw_id_access(stngw_id, current_user, db, action="read")
    if not gateway:
        raise HTTPException(status_code=404, detail=f"Gateway '{stngw_id}' not found")
    return {
        "status": True,
        "message": "Success",
        "data": gateway
    }
