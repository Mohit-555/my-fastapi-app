from datetime import datetime, UTC
import re
from typing import List, Optional, Any
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func, or_

from app.database import get_db
from app.models.models import RTU, Gateway, Station, Division, Zone, User, SlaveCard, AssetParameter, Telemetry
from app.models.schemas import (
    RTUCreate,
    RTUUpdate,
    RTUAddMasterCard,
    RTUBulkCreateRequest,
    RTUBulkCreateResponse,
    RTUResponse,
    RTUListResponse,
    RTUMasterCardResponse,
    RTUPreviewStngwIdResponse,
    RTUFullHierarchyResponse,
    RTUMasterCardHierarchyItem,
    RTUSlaveCardHierarchyItem,
    RTUChannelHierarchyItem,
    StandardResponse,
)
from app.auth_utils import get_current_user

router = APIRouter(prefix="/rtu", tags=["RTU Management"])


def _build_rtu_response(rtu: RTU, db: Session) -> RTUResponse:
    stn = rtu.station
    div = stn.division if stn else None
    zn = div.zone if div else None

    # Load master cards with slave card and channel counts
    mc_responses = []
    mc_ids = []
    for mc in rtu.master_cards:
        mc_ids.append(mc.id)
        slave_count = db.query(SlaveCard).filter(SlaveCard.gateway_id == mc.id).count()
        channels_count = (
            db.query(AssetParameter)
            .join(SlaveCard, SlaveCard.id == AssetParameter.slave_card_id)
            .filter(SlaveCard.gateway_id == mc.id)
            .count()
        )
        gw_num_hex = mc.stngw_id[6:8] if len(mc.stngw_id or "") == 8 else None
        mc_responses.append(
            RTUMasterCardResponse(
                id=mc.id,
                stngw_id=mc.stngw_id,
                imei=mc.imei,
                gateway_number_hex=gw_num_hex,
                slave_cards_count=slave_count,
                channels_count=channels_count,
                status="Active" if mc.station_id else "Unassigned",
            )
        )

    return RTUResponse(
        id=rtu.id,
        rtu_name=rtu.rtu_name,
        rtu_code=rtu.rtu_code,
        location=rtu.location,
        description=rtu.description,
        latitude=rtu.latitude,
        longitude=rtu.longitude,
        is_active=rtu.is_active,
        station_id=rtu.station_id,
        station_code=stn.station_code if stn else None,
        station_name=stn.station_name if stn else None,
        station_id_hex=stn.station_id_hex if stn else None,
        division_id=div.id if div else None,
        division_code=div.division_code if div else None,
        division_name=div.division_name if div else None,
        zone_id=zn.id if zn else None,
        zone_code=zn.zone_code if zn else None,
        zone_name=zn.zone_name if zn else None,
        master_cards_count=len(mc_responses),
        master_card_ids=mc_ids,
        master_cards=mc_responses,
        created_at=rtu.created_at,
    )


@router.get("/preview-stngw-id", response_model=StandardResponse[RTUPreviewStngwIdResponse])
def preview_rtu_stngw_id(
    station_id: int = Query(..., description="Station ID"),
    gateway_number_hex: str = Query(..., description="2-char hex GG (e.g. 01, 02)"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Preview the generated stngw_id (ZZ + DD + SS + GG) for a Station and Gateway sequence.
    Validates hierarchy codes and checks if the gateway ID is already taken.
    """
    clean_gg = gateway_number_hex.strip().upper().zfill(2)
    if len(clean_gg) != 2 or not all(c in "0123456789ABCDEF" for c in clean_gg):
        raise HTTPException(status_code=400, detail="Gateway number hex must be exactly 2 hexadecimal characters.")

    station = db.query(Station).filter(Station.id == station_id).first()
    if not station:
        raise HTTPException(status_code=404, detail=f"Station with ID {station_id} not found.")

    division = station.division
    zone = division.zone if division else None

    if not zone or not zone.zone_id_hex:
        return {
            "status": False,
            "message": "Zone hierarchy hex code is missing for this station.",
            "data": RTUPreviewStngwIdResponse(
                stngw_id="",
                zone_hex="",
                division_hex="",
                station_hex="",
                gateway_number_hex=clean_gg,
                is_valid=False,
                can_provision=False,
                error="Zone hex code missing",
            ),
        }

    zz = zone.zone_id_hex.upper().zfill(2)
    dd = division.division_id_hex.upper().zfill(2) if division and division.division_id_hex else "00"
    ss = station.station_id_hex.upper().zfill(2) if station.station_id_hex else "00"
    stngw_id = f"{zz}{dd}{ss}{clean_gg}".upper()

    existing = db.query(Gateway).filter(Gateway.stngw_id == stngw_id).first()
    can_provision = existing is None
    err = f"Gateway ID '{stngw_id}' is already registered." if existing else None

    return {
        "status": True,
        "message": "Gateway ID preview generated successfully",
        "data": RTUPreviewStngwIdResponse(
            stngw_id=stngw_id,
            zone_hex=zz,
            division_hex=dd,
            station_hex=ss,
            gateway_number_hex=clean_gg,
            is_valid=True,
            station_code=station.station_code,
            station_name=station.station_name,
            can_provision=can_provision,
            error=err,
        ),
    }


@router.get("/", response_model=StandardResponse[RTUListResponse])
def list_rtus(
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(50, ge=1, le=500, description="Items per page"),
    zone_id: Optional[int] = Query(None, description="Filter by Zone ID"),
    division_id: Optional[int] = Query(None, description="Filter by Division ID"),
    station_id: Optional[int] = Query(None, description="Filter by Station ID"),
    zone: Optional[str] = Query(None, description="Filter by Zone Code or Name"),
    division: Optional[str] = Query(None, description="Filter by Division Code or Name"),
    station: Optional[str] = Query(None, description="Filter by Station Code or Name"),
    status: Optional[str] = Query(None, description="Filter by status: Active / Inactive"),
    search: Optional[str] = Query(None, description="Search across RTU name, location, station, or Gateway ID"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    List all Remote Terminal Units (RTUs) with filtering, search, and pagination.
    """
    query = (
        db.query(RTU)
        .join(Station, Station.id == RTU.station_id)
        .outerjoin(Division, Division.id == Station.division_id)
        .outerjoin(Zone, Zone.id == Division.zone_id)
    )

    if zone_id:
        query = query.filter(Zone.id == zone_id)
    if division_id:
        query = query.filter(Division.id == division_id)
    if station_id:
        query = query.filter(Station.id == station_id)

    if zone:
        query = query.filter(or_(Zone.zone_code.ilike(f"%{zone}%"), Zone.zone_name.ilike(f"%{zone}%")))
    if division:
        query = query.filter(or_(Division.division_code.ilike(f"%{division}%"), Division.division_name.ilike(f"%{division}%")))
    if station:
        query = query.filter(or_(Station.station_code.ilike(f"%{station}%"), Station.station_name.ilike(f"%{station}%")))

    if status:
        if status.lower() == "active":
            query = query.filter(RTU.is_active.is_(True))
        elif status.lower() == "inactive":
            query = query.filter(RTU.is_active.is_(False))

    if search:
        s = f"%{search.strip()}%"
        # Also allow searching by gateway stngw_id inside RTU
        gw_match_rtu_ids = (
            db.query(Gateway.rtu_id)
            .filter(Gateway.stngw_id.ilike(s), Gateway.rtu_id.isnot(None))
            .subquery()
        )
        query = query.filter(
            or_(
                RTU.rtu_name.ilike(s),
                RTU.rtu_code.ilike(s),
                RTU.location.ilike(s),
                Station.station_code.ilike(s),
                Station.station_name.ilike(s),
                RTU.id.in_(gw_match_rtu_ids),
            )
        )

    total = query.count()
    total_pages = (total + page_size - 1) // page_size if total > 0 else 1
    offset = (page - 1) * page_size

    rtus = query.order_by(Station.station_code.asc(), RTU.rtu_name.asc()).offset(offset).limit(page_size).all()

    rows = [_build_rtu_response(r, db) for r in rtus]

    return {
        "status": True,
        "message": "Success",
        "data": {
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages,
            "rows": rows,
        },
    }


@router.post("/bulk-create", response_model=StandardResponse[RTUBulkCreateResponse], status_code=status.HTTP_201_CREATED)
def bulk_create_rtus(
    payload: RTUBulkCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Bulk auto-create N RTUs for a station (e.g. 35 -> RTU-01 to RTU-35).
    Safe: Checks existing RTU names for this station and continues numbering sequence.
    """
    station = db.query(Station).filter(Station.id == payload.station_id).first()
    if not station:
        raise HTTPException(status_code=404, detail=f"Station with ID {payload.station_id} not found.")

    # Find existing RTU names for this station
    existing_rtus = db.query(RTU).filter(RTU.station_id == payload.station_id).all()
    existing_names = {r.rtu_name.strip().upper() for r in existing_rtus}

    prefix = payload.prefix.strip() if payload.prefix else "RTU-"

    # Auto-detect starting index if not provided
    if payload.start_index is not None:
        start_idx = payload.start_index
    else:
        max_idx = 0
        for r in existing_rtus:
            m = re.search(r"(\d+)$", r.rtu_name.strip())
            if m:
                try:
                    num = int(m.group(1))
                    if num > max_idx:
                        max_idx = num
                except ValueError:
                    pass
        start_idx = max_idx + 1

    created_rtus = []
    current_idx = start_idx
    created_count = 0

    while created_count < payload.count:
        rtu_name = f"{prefix}{current_idx:02d}"
        if rtu_name.upper() not in existing_names:
            rtu_code = f"RTU-{station.station_code}-{current_idx:02d}".upper()
            code_suffix = 1
            cand_code = rtu_code
            while db.query(RTU).filter(RTU.rtu_code == cand_code).first():
                cand_code = f"{rtu_code}-{code_suffix}"
                code_suffix += 1

            new_rtu = RTU(
                station_id=station.id,
                rtu_name=rtu_name,
                rtu_code=cand_code,
                location=payload.location.strip() if payload.location else "Relay Room",
                description=f"Auto-generated RTU unit {current_idx}",
                is_active=True,
            )
            db.add(new_rtu)
            existing_names.add(rtu_name.upper())
            created_rtus.append(new_rtu)
            created_count += 1
        current_idx += 1

    db.commit()
    for r in created_rtus:
        db.refresh(r)

    rtu_responses = [_build_rtu_response(r, db) for r in created_rtus]

    return {
        "status": True,
        "message": f"Successfully auto-generated {len(created_rtus)} RTUs for station '{station.station_name}'.",
        "data": {
            "station_id": station.id,
            "station_code": station.station_code,
            "station_name": station.station_name,
            "created_count": len(created_rtus),
            "rtus": rtu_responses,
        },
    }


@router.get("/{rtu_id}", response_model=StandardResponse[RTUResponse])
def get_rtu(
    rtu_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Get full details of a single RTU, its Master Cards, Slave Cards count, and Channels count.
    """
    rtu = db.query(RTU).filter(RTU.id == rtu_id).first()
    if not rtu:
        raise HTTPException(status_code=404, detail=f"RTU with ID {rtu_id} not found.")

    return {
        "status": True,
        "message": "Success",
        "data": _build_rtu_response(rtu, db),
    }


@router.get("/{rtu_id}/hierarchy", response_model=StandardResponse[RTUFullHierarchyResponse])
def get_rtu_hierarchy(
    rtu_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Get deep drill-down hardware hierarchy for an RTU:
    RTU -> Master Cards (Gateways) -> Slave Cards -> Channels (12 per card) -> para_id.
    Single unified entry point for hardware configuration.
    """
    rtu = db.query(RTU).filter(RTU.id == rtu_id).first()
    if not rtu:
        raise HTTPException(status_code=404, detail=f"RTU with ID {rtu_id} not found.")

    rtu_resp = _build_rtu_response(rtu, db)

    mc_items = []
    for mc in rtu.master_cards:
        slave_cards = db.query(SlaveCard).filter(SlaveCard.gateway_id == mc.id).order_by(SlaveCard.card_address).all()
        sc_items = []
        for sc in slave_cards:
            ap_rows = (
                db.query(AssetParameter)
                .options(joinedload(AssetParameter.asset))
                .filter(AssetParameter.slave_card_id == sc.id)
                .all()
            )
            ap_by_ch = {}
            for ap in ap_rows:
                if ap.channel_number:
                    norm_ch = ap.channel_number.strip().upper()
                    if not norm_ch.startswith("CH"):
                        norm_ch = f"CH{norm_ch}"
                    ap_by_ch[norm_ch] = ap

            total_chs = 16 if (sc.card_type or "").upper() == "DI" else 12
            ch_items = []
            for i in range(1, total_chs + 1):
                ch_key = f"CH{i}"
                ap = ap_by_ch.get(ch_key)
                if ap:
                    asset = ap.asset
                    asset_type_name = None
                    if asset and asset.asset_type_hex:
                        from app.constants import ASSET_TYPE_MAP
                        info = ASSET_TYPE_MAP.get(asset.asset_type_hex)
                        asset_type_name = info[1] if info else None
                    ch_items.append(
                        RTUChannelHierarchyItem(
                            id=ap.id,
                            channel_number=ch_key,
                            para_id=ap.para_id,
                            is_assigned=bool(ap.is_assigned and ap.asset_id),
                            asset_id=ap.asset_id,
                            asset_number_code=asset.asset_number_code if asset else None,
                            asset_type_name=asset_type_name,
                            prloc=ap.prloc,
                        )
                    )
                else:
                    ch_items.append(
                        RTUChannelHierarchyItem(
                            id=None,
                            channel_number=ch_key,
                            para_id=None,
                            is_assigned=False,
                            asset_id=None,
                            asset_number_code=None,
                            asset_type_name=None,
                            prloc=None,
                        )
                    )

            sc_items.append(
                RTUSlaveCardHierarchyItem(
                    id=sc.id,
                    card_address=sc.card_address,
                    card_type=sc.card_type,
                    total_channels=total_chs,
                    channels=ch_items,
                )
            )

        mc_items.append(
            RTUMasterCardHierarchyItem(
                id=mc.id,
                stngw_id=mc.stngw_id,
                imei=mc.imei,
                status="Active" if mc.station_id else "Unassigned",
                slave_cards=sc_items,
            )
        )

    return {
        "status": True,
        "message": "Success",
        "data": {
            "rtu": rtu_resp,
            "master_cards": mc_items,
        },
    }


@router.post("/", response_model=StandardResponse[RTUResponse], status_code=status.HTTP_201_CREATED)
def create_rtu(
    payload: RTUCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Atomically provision a new Remote Terminal Unit (RTU) and its Master Cards.
    Calculates stngw_id = ZZ + DD + SS + GG and registers each Master Card in the database.
    """
    station = db.query(Station).filter(Station.id == payload.station_id).first()
    if not station:
        raise HTTPException(status_code=404, detail=f"Station with ID {payload.station_id} not found.")

    division = station.division
    zone = division.zone if division else None

    if not zone or not zone.zone_id_hex:
        raise HTTPException(status_code=400, detail="Cannot provision RTU: Station zone hierarchy is incomplete.")

    zz = zone.zone_id_hex.upper().zfill(2)
    dd = division.division_id_hex.upper().zfill(2) if division and division.division_id_hex else "00"
    ss = station.station_id_hex.upper().zfill(2) if station.station_id_hex else "00"

    # Check for duplicate RTU name at this station
    existing_rtu = db.query(RTU).filter(RTU.station_id == payload.station_id, RTU.rtu_name == payload.rtu_name.strip()).first()
    if existing_rtu:
        raise HTTPException(
            status_code=400,
            detail=f"An RTU named '{payload.rtu_name}' already exists at station '{station.station_code}'.",
        )

    # 1. Existing Master Cards linked via IDs (e.g. master_card_ids: [3, 5, 6])
    gateways_to_link = []
    if payload.master_card_ids:
        seen_gw_ids = set()
        for gw_id in payload.master_card_ids:
            if gw_id in seen_gw_ids:
                continue
            seen_gw_ids.add(gw_id)
            gw = db.query(Gateway).filter(Gateway.id == gw_id).first()
            if not gw:
                raise HTTPException(status_code=404, detail=f"Master Card with ID {gw_id} not found.")
            if gw.station_id and gw.station_id != station.id:
                raise HTTPException(
                    status_code=400,
                    detail=f"Master Card '{gw.stngw_id}' (ID: {gw.id}) belongs to another station.",
                )
            gateways_to_link.append(gw)

    # 2. New Master Cards to provision (if provided)
    seen_gg = set()
    cards_to_create = []
    for mc in payload.master_cards:
        clean_gg = mc.gateway_number_hex.upper().strip().zfill(2)
        if clean_gg in seen_gg:
            raise HTTPException(status_code=400, detail=f"Duplicate gateway number hex '{clean_gg}' in request.")
        seen_gg.add(clean_gg)

        computed_stngw_id = f"{zz}{dd}{ss}{clean_gg}".upper()
        existing_gw = db.query(Gateway).filter(Gateway.stngw_id == computed_stngw_id).first()
        if existing_gw:
            raise HTTPException(
                status_code=400,
                detail=f"Gateway ID '{computed_stngw_id}' is already registered (ID: {existing_gw.id}).",
            )

        imei_val = mc.imei.strip() if mc.imei else None
        if imei_val:
            existing_imei = db.query(Gateway).filter(Gateway.imei == imei_val).first()
            if existing_imei:
                raise HTTPException(
                    status_code=400,
                    detail=f"Modem IMEI '{imei_val}' is already used by Gateway '{existing_imei.stngw_id}'.",
                )

        cards_to_create.append({"stngw_id": computed_stngw_id, "imei": imei_val})

    # Auto-generate rtu_code
    seq = db.query(RTU).filter(RTU.station_id == payload.station_id).count() + 1
    rtu_code = f"RTU-{station.station_code}-{seq:02d}".upper()

    # Create RTU
    rtu = RTU(
        station_id=station.id,
        rtu_name=payload.rtu_name.strip(),
        rtu_code=rtu_code,
        location=payload.location.strip(),
        description=payload.description.strip() if payload.description else None,
        latitude=payload.latitude,
        longitude=payload.longitude,
        is_active=True,
    )
    db.add(rtu)
    db.flush()

    # Link existing Master Cards
    for gw in gateways_to_link:
        gw.rtu_id = rtu.id
        if not gw.station_id:
            gw.station_id = station.id

    # Create newly provisioned Master Cards
    for card_info in cards_to_create:
        gw = Gateway(
            stngw_id=card_info["stngw_id"],
            imei=card_info["imei"],
            station_id=station.id,
            rtu_id=rtu.id,
        )
        db.add(gw)

    db.commit()
    db.refresh(rtu)

    total_cards = len(gateways_to_link) + len(cards_to_create)
    return {
        "status": True,
        "message": f"RTU '{rtu.rtu_name}' with {total_cards} Master Cards provisioned successfully.",
        "data": _build_rtu_response(rtu, db),
    }


@router.put("/{rtu_id}", response_model=StandardResponse[RTUResponse])
def update_rtu(
    rtu_id: int,
    payload: RTUUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Update metadata of an RTU (name, location, description, latitude, longitude, is_active) and its linked Master Cards.
    """
    rtu = db.query(RTU).filter(RTU.id == rtu_id).first()
    if not rtu:
        raise HTTPException(status_code=404, detail=f"RTU with ID {rtu_id} not found.")

    if payload.rtu_name is not None and payload.rtu_name.strip():
        new_name = payload.rtu_name.strip()
        # Check uniqueness at station
        existing = (
            db.query(RTU)
            .filter(RTU.station_id == rtu.station_id, RTU.rtu_name == new_name, RTU.id != rtu.id)
            .first()
        )
        if existing:
            raise HTTPException(status_code=400, detail=f"An RTU named '{new_name}' already exists at this station.")
        rtu.rtu_name = new_name

    if payload.location is not None:
        rtu.location = payload.location.strip()
    if payload.description is not None:
        rtu.description = payload.description.strip() if payload.description else None
    if payload.latitude is not None:
        rtu.latitude = payload.latitude
    if payload.longitude is not None:
        rtu.longitude = payload.longitude
    if payload.is_active is not None:
        rtu.is_active = payload.is_active

    # Update Master Cards association if provided
    if payload.master_card_ids is not None:
        target_ids = set(payload.master_card_ids)
        # 1. Unlink cards currently in rtu that are not in target_ids
        for existing_mc in list(rtu.master_cards):
            if existing_mc.id not in target_ids:
                existing_mc.rtu_id = None
        # 2. Link target cards
        for gw_id in target_ids:
            gw = db.query(Gateway).filter(Gateway.id == gw_id).first()
            if not gw:
                raise HTTPException(status_code=404, detail=f"Master Card with ID {gw_id} not found.")
            if gw.station_id and gw.station_id != rtu.station_id:
                raise HTTPException(
                    status_code=400,
                    detail=f"Master Card '{gw.stngw_id}' (ID: {gw.id}) belongs to another station.",
                )
            gw.rtu_id = rtu.id
            if not gw.station_id:
                gw.station_id = rtu.station_id

    rtu.updated_at = datetime.now(UTC)
    db.commit()
    db.refresh(rtu)

    return {
        "status": True,
        "message": f"RTU '{rtu.rtu_name}' updated successfully.",
        "data": _build_rtu_response(rtu, db),
    }


@router.delete("/{rtu_id}", response_model=StandardResponse[None])
def delete_rtu(
    rtu_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Safe delete an RTU.
    Blocks deletion if any of its Master Cards have active telemetry or assigned slave cards.
    """
    rtu = db.query(RTU).filter(RTU.id == rtu_id).first()
    if not rtu:
        raise HTTPException(status_code=404, detail=f"RTU with ID {rtu_id} not found.")

    # Guard: check if any master card has slave cards or telemetry
    for mc in rtu.master_cards:
        has_slaves = db.query(SlaveCard).filter(SlaveCard.gateway_id == mc.id).first()
        if has_slaves:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot delete RTU: Master Card '{mc.stngw_id}' has configured Slave Cards. Remove them first.",
            )
        has_telemetry = db.query(Telemetry).filter(Telemetry.gateway_id == mc.id).first()
        if has_telemetry:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot delete RTU: Master Card '{mc.stngw_id}' has historical telemetry data.",
            )

    # Safe to delete RTU and unlink master cards
    for mc in rtu.master_cards:
        db.delete(mc)

    rtu_name = rtu.rtu_name
    db.delete(rtu)
    db.commit()

    return {
        "status": True,
        "message": f"RTU '{rtu_name}' and its unconfigured Master Cards deleted successfully.",
        "data": None,
    }


@router.post("/{rtu_id}/master-cards", response_model=StandardResponse[RTUResponse])
def add_master_card_to_rtu(
    rtu_id: int,
    payload: RTUAddMasterCard,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Add an additional Master Card (Gateway) to an existing RTU.
    """
    rtu = db.query(RTU).filter(RTU.id == rtu_id).first()
    if not rtu:
        raise HTTPException(status_code=404, detail=f"RTU with ID {rtu_id} not found.")

    stn = rtu.station
    div = stn.division if stn else None
    zn = div.zone if div else None

    if not zn or not zn.zone_id_hex:
        raise HTTPException(status_code=400, detail="Zone hierarchy code is missing for this station.")

    zz = zn.zone_id_hex.upper().zfill(2)
    dd = div.division_id_hex.upper().zfill(2) if div and div.division_id_hex else "00"
    ss = stn.station_id_hex.upper().zfill(2) if stn and stn.station_id_hex else "00"
    clean_gg = payload.gateway_number_hex.upper().strip().zfill(2)

    computed_stngw_id = f"{zz}{dd}{ss}{clean_gg}".upper()

    existing = db.query(Gateway).filter(Gateway.stngw_id == computed_stngw_id).first()
    if existing:
        raise HTTPException(status_code=400, detail=f"Gateway ID '{computed_stngw_id}' already exists.")

    imei_val = payload.imei.strip() if payload.imei else None
    if imei_val:
        existing_imei = db.query(Gateway).filter(Gateway.imei == imei_val).first()
        if existing_imei:
            raise HTTPException(status_code=400, detail=f"IMEI '{imei_val}' is already used by Gateway '{existing_imei.stngw_id}'.")

    new_mc = Gateway(
        stngw_id=computed_stngw_id,
        imei=imei_val,
        station_id=stn.id,
        rtu_id=rtu.id,
    )
    db.add(new_mc)
    db.commit()
    db.refresh(rtu)

    return {
        "status": True,
        "message": f"Master Card '{computed_stngw_id}' added to RTU '{rtu.rtu_name}' successfully.",
        "data": _build_rtu_response(rtu, db),
    }


@router.delete("/{rtu_id}/master-cards/{gateway_id}", response_model=StandardResponse[RTUResponse])
def remove_master_card_from_rtu(
    rtu_id: int,
    gateway_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Remove a Master Card from an RTU.
    Blocks deletion if the card has active slave cards or telemetry.
    """
    rtu = db.query(RTU).filter(RTU.id == rtu_id).first()
    if not rtu:
        raise HTTPException(status_code=404, detail=f"RTU with ID {rtu_id} not found.")

    mc = db.query(Gateway).filter(Gateway.id == gateway_id, Gateway.rtu_id == rtu_id).first()
    if not mc:
        raise HTTPException(status_code=404, detail=f"Master Card with ID {gateway_id} not found in this RTU.")

    has_slaves = db.query(SlaveCard).filter(SlaveCard.gateway_id == mc.id).first()
    if has_slaves:
        raise HTTPException(status_code=400, detail=f"Cannot remove Master Card '{mc.stngw_id}': It has configured Slave Cards.")

    has_telemetry = db.query(Telemetry).filter(Telemetry.gateway_id == mc.id).first()
    if has_telemetry:
        raise HTTPException(status_code=400, detail=f"Cannot remove Master Card '{mc.stngw_id}': It has historical telemetry data.")

    card_id = mc.stngw_id
    db.delete(mc)
    db.commit()
    db.refresh(rtu)

    return {
        "status": True,
        "message": f"Master Card '{card_id}' removed from RTU successfully.",
        "data": _build_rtu_response(rtu, db),
    }
