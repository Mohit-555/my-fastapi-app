from datetime import datetime
from typing import List, Optional, Any, Union
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from pydantic import BaseModel, Field
from app.database import get_db
from app.models.models import SlaveCard, Gateway, Station, Division, Zone, AssetParameter, User
from app.models.schemas import (
    SlaveCardCreate,
    SlaveCardUpdate,
    SlaveCardResponse,
    SlaveCardListResponse,
    SlaveCardBulkCreateRequest,
    SlaveCardBulkCreateResponse,
    AvailableChannelsResponse,
    StandardResponse,
)
from app.auth_utils import get_current_user
from app.services.channel_assignment_service import ChannelAssignmentService

router = APIRouter(prefix="/slave-cards", tags=["Slave Card Management"])

class ChannelConfigItem(BaseModel):
    channel_number: str = Field(..., max_length=10)
    para_id: Optional[str] = Field(None, max_length=8)
    asset_id: Optional[int] = None
    asset_number_code: Optional[str] = Field(None, max_length=50)
    prloc: Optional[str] = Field(None, max_length=50)

class BulkChannelsRequest(BaseModel):
    channels: List[ChannelConfigItem]


def _check_slave_card_ownership(slave_card_id: int, user: User, db: Session, action: str = "read") -> SlaveCard:
    """Fetch slave card and verify user has division/zone station access and write permission."""
    card = db.query(SlaveCard).filter(SlaveCard.id == slave_card_id).first()
    if not card:
        raise HTTPException(status_code=404, detail=f"Slave Card {slave_card_id} not found")

    # If action is write, block Guest / Auditor roles (level >= 7)
    if action == "write" and user.role and user.role.level >= 7:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Guest and Auditor roles are not permitted to perform this action."
        )

    # Check division/zone access
    gateway = db.query(Gateway).filter(Gateway.id == card.gateway_id).first()
    if not gateway:
        raise HTTPException(status_code=404, detail="Gateway associated with this slave card not found")

    station = db.query(Station).filter(Station.id == gateway.station_id).first()
    if not station:
        raise HTTPException(status_code=404, detail="Station associated with this slave card not found")

    if user.division_id is not None:
        if station.division_id != user.division_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied: User division does not match the slave card station division."
            )

    if user.zone_id is not None:
        division = db.query(Division).filter(Division.id == station.division_id).first()
        if not division or division.zone_id != user.zone_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied: User zone does not match the slave card station zone."
            )

    return card


def _check_gateway_ownership(gateway_id: int, user: User, db: Session, action: str = "read"):
    """Verify user is authorized to access/modify a gateway/master card."""
    # If action is write, block Guest / Auditor roles (level >= 7)
    if action == "write" and user.role and user.role.level >= 7:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Guest and Auditor roles are not permitted to perform this action."
        )

    gateway = db.query(Gateway).filter(Gateway.id == gateway_id).first()
    if not gateway:
        raise HTTPException(status_code=404, detail=f"Gateway with ID {gateway_id} not found")

    station = db.query(Station).filter(Station.id == gateway.station_id).first()
    if not station:
        raise HTTPException(status_code=404, detail="Station associated with this gateway not found")

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


def _populate_card_numbers(cards: List[SlaveCard], db: Session) -> None:
    """Populate card_no and card_number (e.g. Card 1, Card 2) sequentially per gateway."""
    if not cards:
        return
    gateway_ids = {c.gateway_id for c in cards if c.gateway_id}
    gateway_cards_map = {}
    for gid in gateway_ids:
        sibling_ids = [
            cid for (cid,) in
            db.query(SlaveCard.id)
            .filter(SlaveCard.gateway_id == gid)
            .order_by(SlaveCard.id.asc())
            .all()
        ]
        gateway_cards_map[gid] = sibling_ids

    for c in cards:
        s_ids = gateway_cards_map.get(c.gateway_id, [])
        if c.id in s_ids:
            idx = s_ids.index(c.id) + 1
            setattr(c, "card_no", idx)
            setattr(c, "card_number", f"Card {idx}")
        else:
            setattr(c, "card_no", 1)
            setattr(c, "card_number", "Card 1")


@router.get("", response_model=StandardResponse[SlaveCardListResponse])
def list_slave_cards(
    gateway_id: Optional[int] = Query(None, description="Filter by Gateway ID"),
    stngw_id: Optional[str] = Query(None, description="Filter by Gateway Code (stngw_id)"),
    card_address: Optional[str] = Query(None, description="Filter by Card Address (e.g. '81')"),
    card_type: Optional[str] = Query(None, description="Filter by Card Type (e.g. 'Voltage', 'Analog', 'DI')"),
    station_id: Optional[int] = Query(None, description="Filter by Station ID"),
    division_id: Optional[int] = Query(None, description="Filter by Division ID"),
    zone_id: Optional[int] = Query(None, description="Filter by Zone ID"),
    search: Optional[str] = Query(None, description="Search term across card address, card type, gateway code, or station name"),
    q: Optional[str] = Query(None, description="Alias for search term"),
    page: int = Query(1, ge=1, description="Page number (1-based)"),
    page_size: int = Query(50, ge=1, le=500, description="Items per page"),
    limit: Optional[int] = Query(None, ge=1, le=500, description="Alias for page_size"),
    offset: Optional[int] = Query(None, ge=0, description="Row offset for pagination"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List all configured Slave Cards with comprehensive filtering and pagination."""
    q_db = db.query(SlaveCard)

    search_term = search or q

    joined_gateway = False
    joined_station = False
    joined_division = False

    def join_gateway():
        nonlocal q_db, joined_gateway
        if not joined_gateway:
            q_db = q_db.join(Gateway, SlaveCard.gateway_id == Gateway.id)
            joined_gateway = True

    def join_station():
        nonlocal q_db, joined_station
        join_gateway()
        if not joined_station:
            q_db = q_db.join(Station, Gateway.station_id == Station.id)
            joined_station = True

    def join_division():
        nonlocal q_db, joined_division
        join_station()
        if not joined_division:
            q_db = q_db.join(Division, Station.division_id == Division.id)
            joined_division = True

    # First restrict list to user division/zone
    if current_user.division_id is not None:
        join_station()
        q_db = q_db.filter(Station.division_id == current_user.division_id)
    elif current_user.zone_id is not None:
        join_division()
        q_db = q_db.filter(Division.zone_id == current_user.zone_id)

    if gateway_id is not None:
        q_db = q_db.filter(SlaveCard.gateway_id == gateway_id)

    if stngw_id:
        join_gateway()
        q_db = q_db.filter(Gateway.stngw_id.ilike(f"%{stngw_id.strip()}%"))

    if card_address:
        q_db = q_db.filter(SlaveCard.card_address.ilike(f"%{card_address.strip()}%"))

    if card_type:
        q_db = q_db.filter(SlaveCard.card_type.ilike(f"%{card_type.strip()}%"))

    if station_id is not None:
        join_gateway()
        q_db = q_db.filter(Gateway.station_id == station_id)

    if division_id is not None:
        join_station()
        q_db = q_db.filter(Station.division_id == division_id)

    if zone_id is not None:
        join_division()
        q_db = q_db.filter(Division.zone_id == zone_id)

    if search_term:
        join_gateway()
        term = f"%{search_term.strip()}%"
        q_db = q_db.filter(
            or_(
                SlaveCard.card_address.ilike(term),
                SlaveCard.card_type.ilike(term),
                Gateway.stngw_id.ilike(term),
            )
        )

    total = q_db.count()

    effective_page_size = limit if limit is not None else page_size
    if offset is not None:
        calc_offset = offset
        calc_page = (offset // effective_page_size) + 1
    else:
        calc_page = page
        calc_offset = (page - 1) * effective_page_size

    total_pages = (total + effective_page_size - 1) // effective_page_size if total else 0

    rows = q_db.order_by(SlaveCard.id).offset(calc_offset).limit(effective_page_size).all()
    _populate_card_numbers(rows, db)

    return {
        "status": True,
        "message": "Success",
        "data": SlaveCardListResponse(
            total=total,
            page=calc_page,
            page_size=effective_page_size,
            total_pages=total_pages,
            rows=rows,
        )
    }


@router.get("/parameter-catalog", response_model=StandardResponse[List[dict]])
def get_parameter_catalog(
    card_type: Optional[str] = Query(None, description="Filter parameters by Card Type: Voltage, Current, Analog, DI, Digital"),
    current_user: User = Depends(get_current_user),
):
    """
    Get standard parameter definitions from Annexure A, optionally filtered by card type.
    Returns code, name, unit, and default 8-hex para_id (e.g. 00012020 for VPT 110 DC LOC N).
    """
    from app.services.parameter_config_service import param_config_service

    norm_type = (card_type or "").strip().upper()
    results = []
    seen = set()

    for config in param_config_service.config_cache.values():
        p_code = config.parameter_representation_code or ""
        p_name = config.parameter_representation_name or ""
        p_unit = config.unit or ""
        p_type = config.parameter_type_id or "20"
        p_repr = config.parameter_representation_id or "00"
        a_type = config.asset_type_id or "00"

        # Filter by Card Type if specified
        if norm_type:
            if "VOLT" in norm_type:
                # Voltage: parameter_type_id in ["20", "30"] or unit=="V" or code starts with "V"
                if p_type not in ["20", "30"] and p_unit != "V" and not p_code.startswith("V"):
                    continue
            elif "ANALOG" in norm_type or "CURR" in norm_type:
                # Current/Analog: parameter_type_id in ["00", "01"] or unit in ["A", "mA"] or code starts with "I"
                if p_type not in ["00", "01"] and p_unit not in ["A", "mA"] and not p_code.startswith("I"):
                    continue
            elif "DI" in norm_type or "DIGITAL" in norm_type:
                # Digital/DI: parameter_type_id == "40"
                if p_type != "40":
                    continue

        para_id_example = f"{a_type}01{p_type}{p_repr}".upper()
        unique_key = (p_code, para_id_example)
        if unique_key in seen:
            continue
        seen.add(unique_key)

        results.append({
            "code": p_code,
            "name": p_name,
            "unit": p_unit,
            "asset_type_id": a_type,
            "parameter_type_id": p_type,
            "parameter_representation_id": p_repr,
            "default_para_id": para_id_example,
            "display_label": f"{p_code} - {p_name} ({p_unit})" if p_unit else f"{p_code} - {p_name}",
        })

    results.sort(key=lambda x: x["code"])

    return {
        "status": True,
        "message": "Success",
        "data": results,
    }


@router.get("/{slave_card_id}", response_model=StandardResponse[SlaveCardResponse])
def get_slave_card(
    slave_card_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Retrieve details of a single Slave Card."""
    card = _check_slave_card_ownership(slave_card_id, current_user, db, action="read")
    _populate_card_numbers([card], db)
    return {
        "status": True,
        "message": "Success",
        "data": card
    }


@router.post("", response_model=StandardResponse[SlaveCardResponse], status_code=status.HTTP_201_CREATED)
def create_slave_card(
    payload: SlaveCardCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Add/configure a new Slave Card under a Master Card/Gateway."""
    # 1. Validate Gateway exists and check user's ownership
    _check_gateway_ownership(payload.gateway_id, current_user, db, action="write")
    
    # 2. Uppercase card address (e.g. "81" or "8A")
    card_addr = payload.card_address.strip().upper()
    
    # 3. Check for unique constraint violation: card_address must be unique under this gateway
    existing = db.query(SlaveCard).filter(
        SlaveCard.gateway_id == payload.gateway_id,
        SlaveCard.card_address == card_addr,
    ).first()
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"Slave Card with address '{card_addr}' already exists on Gateway #{payload.gateway_id}."
        )
        
    card = SlaveCard(
        gateway_id=payload.gateway_id,
        card_address=card_addr,
        card_type=payload.card_type,
    )
    db.add(card)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Slave Card unique constraint violation."
        )
    db.refresh(card)
    _populate_card_numbers([card], db)
    return {
        "status": True,
        "message": "Success",
        "data": card
    }


@router.post("/bulk-create", response_model=StandardResponse[SlaveCardBulkCreateResponse], status_code=status.HTTP_201_CREATED)
def bulk_create_slave_cards(
    payload: SlaveCardBulkCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Bulk auto-create N Slave Cards under a Master Card/Gateway.
    Generates sequential hex card addresses (e.g. 81, 82, 83...) or accepts custom card definitions.
    """
    # 1. Validate Gateway exists and check user's ownership
    gateway = _check_gateway_ownership(payload.gateway_id, current_user, db, action="write")

    existing_cards = db.query(SlaveCard).filter(SlaveCard.gateway_id == payload.gateway_id).all()
    existing_addrs = {c.card_address.strip().upper() for c in existing_cards}

    cards_to_create = []

    if payload.custom_cards and len(payload.custom_cards) > 0:
        for item in payload.custom_cards:
            addr = item.card_address.strip().upper()
            ctype = item.card_type or payload.default_type or "Voltage"
            if addr in existing_addrs:
                raise HTTPException(
                    status_code=409,
                    detail=f"Slave Card with address '{addr}' already exists for Gateway {gateway.stngw_id}."
                )
            existing_addrs.add(addr)
            cards_to_create.append(SlaveCard(
                gateway_id=payload.gateway_id,
                card_address=addr,
                card_type=ctype
            ))
    else:
        # Determine starting hex address
        if payload.start_address:
            clean_start = payload.start_address.strip().upper()
            if clean_start.startswith("0X"):
                clean_start = clean_start[2:]
            if clean_start in existing_addrs:
                raise HTTPException(
                    status_code=409,
                    detail=f"Address '{clean_start}' is already in use on Gateway '{gateway.stngw_id}'."
                )
            try:
                start_val = int(clean_start, 16)
            except ValueError:
                start_val = 0x81
        else:
            # Auto-detect next available hex address
            existing_hex = []
            for c in existing_cards:
                try:
                    existing_hex.append(int(c.card_address.strip(), 16))
                except (ValueError, TypeError):
                    pass
            if existing_hex:
                start_val = max(existing_hex) + 1
            else:
                start_val = 0x81

        created_count = 0
        curr_val = start_val
        default_type = payload.default_type or "Voltage"

        while created_count < payload.count and curr_val <= 0xFF:
            addr_hex = f"{curr_val:02X}"
            if addr_hex not in existing_addrs:
                cards_to_create.append(SlaveCard(
                    gateway_id=payload.gateway_id,
                    card_address=addr_hex,
                    card_type=default_type
                ))
                existing_addrs.add(addr_hex)
                created_count += 1
            curr_val += 1

    for sc in cards_to_create:
        db.add(sc)

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Slave Card unique constraint violation during bulk creation."
        )

    for sc in cards_to_create:
        db.refresh(sc)
    _populate_card_numbers(cards_to_create, db)

    return {
        "status": True,
        "message": f"Successfully created {len(cards_to_create)} slave card(s)",
        "data": {
            "created_count": len(cards_to_create),
            "gateway_id": payload.gateway_id,
            "cards": cards_to_create
        }
    }


@router.put("/{slave_card_id}", response_model=StandardResponse[SlaveCardResponse])
def update_slave_card(
    slave_card_id: int,
    payload: SlaveCardUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update configurations of a Slave Card."""
    card = _check_slave_card_ownership(slave_card_id, current_user, db, action="write")
        
    data = payload.model_dump(exclude_unset=True)
    
    if "gateway_id" in data:
        _check_gateway_ownership(data["gateway_id"], current_user, db, action="write")
            
    if "card_address" in data:
        data["card_address"] = data["card_address"].strip().upper()
        
    # Check uniqueness if modifying card_address or gateway
    new_gw = data.get("gateway_id", card.gateway_id)
    new_addr = data.get("card_address", card.card_address)
    
    if new_gw != card.gateway_id or new_addr != card.card_address:
        existing = db.query(SlaveCard).filter(
            SlaveCard.gateway_id == new_gw,
            SlaveCard.card_address == new_addr,
            SlaveCard.id != slave_card_id,
        ).first()
        if existing:
            raise HTTPException(
                status_code=409,
                detail=f"Another Slave Card with address '{new_addr}' already exists under Gateway #{new_gw}."
            )
            
    for field, value in data.items():
        setattr(card, field, value)
        
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Slave Card unique constraint violation."
        )
    db.refresh(card)
    _populate_card_numbers([card], db)
    return {
        "status": True,
        "message": "Success",
        "data": card
    }


@router.delete("/{slave_card_id}", status_code=status.HTTP_200_OK, response_model=StandardResponse[None])
def delete_slave_card(
    slave_card_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Permanently delete a Slave Card. Referenced Channels will have their slave_card_id set to NULL."""
    card = _check_slave_card_ownership(slave_card_id, current_user, db, action="write")

    stngw_id = card.gateway.stngw_id if card.gateway else str(slave_card_id)
    card_address = card.card_address

    # Unlink Channels referencing this slave card
    db.query(AssetParameter).filter(AssetParameter.slave_card_id == slave_card_id).update(
        {"slave_card_id": None}
    )

    db.delete(card)
    db.commit()

    return {
        "status": True,
        "message": f"Slave card '{stngw_id}/{card_address}' deleted successfully",
        "data": None,
    }


@router.get("/{slave_card_id}/channels", response_model=StandardResponse[AvailableChannelsResponse])
def get_slave_card_channels(
    slave_card_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Retrieve all configured channels and available capacity for a slave card."""
    card = _check_slave_card_ownership(slave_card_id, current_user, db, action="read")
    available_data = ChannelAssignmentService.get_available_channels(
        db=db,
        slave_card_id=card.id,
        user=current_user,
    )
    return {
        "status": True,
        "message": "Success",
        "data": available_data,
    }


@router.post("/{slave_card_id}/channels", response_model=StandardResponse[Any])
@router.put("/{slave_card_id}/channels", response_model=StandardResponse[Any])
def configure_slave_card_channels(
    slave_card_id: int,
    payload: BulkChannelsRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Configure all channels (CH1..CH12) directly for a slave card.
    Allows setting para_id (and optional asset/prloc) per channel in one request.
    """
    card = _check_slave_card_ownership(slave_card_id, current_user, db, action="write")

    for ch_item in payload.channels:
        ch_num = ch_item.channel_number.strip().upper()
        clean_pid = ch_item.para_id.strip().upper() if ch_item.para_id and ch_item.para_id.strip() else None

        # Cleanly detach any previous parameter assigned to this (card.id, ch_num)
        old_params = db.query(AssetParameter).filter(
            AssetParameter.slave_card_id == card.id,
            AssetParameter.channel_number == ch_num,
        ).all()
        for op in old_params:
            if not clean_pid or op.para_id != clean_pid:
                op.slave_card_id = None
                op.channel_number = None

        target_asset_id = ch_item.asset_id
        if ch_item.asset_number_code and ch_item.asset_number_code.strip():
            clean_code = ch_item.asset_number_code.strip()
            gw = card.gateway or db.query(Gateway).filter(Gateway.id == card.gateway_id).first()
            if gw:
                from app.services.channel_assignment_service import _get_or_create_asset_by_code
                asset_obj = _get_or_create_asset_by_code(db, gw, clean_code)
                target_asset_id = asset_obj.id

        if clean_pid:
            param = db.query(AssetParameter).filter(AssetParameter.para_id == clean_pid).first()
            if not param:
                param = AssetParameter(
                    para_id=clean_pid,
                    slave_card_id=card.id,
                    channel_number=ch_num,
                    asset_id=target_asset_id,
                    prloc=ch_item.prloc.strip() if ch_item.prloc else None,
                    is_assigned=(target_asset_id is not None),
                )
                db.add(param)
            else:
                param.slave_card_id = card.id
                param.channel_number = ch_num
                if target_asset_id is not None:
                    param.asset_id = target_asset_id
                    param.is_assigned = True
                if ch_item.prloc is not None:
                    param.prloc = ch_item.prloc.strip() if ch_item.prloc else None
        else:
            # Unlink if previously assigned to this channel
            existing = db.query(AssetParameter).filter(
                AssetParameter.slave_card_id == card.id,
                AssetParameter.channel_number == ch_num,
            ).all()
            for p in existing:
                p.slave_card_id = None
                p.channel_number = None

    db.commit()

    available_data = ChannelAssignmentService.get_available_channels(
        db=db,
        slave_card_id=card.id,
        user=current_user,
    )
    return {
        "status": True,
        "message": f"Channels for card '{card.card_address}' configured successfully",
        "data": available_data,
    }

