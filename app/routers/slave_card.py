from datetime import datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.database import get_db
from app.models.models import SlaveCard, Gateway, Station, Division, Zone, AssetParameter
from app.models.schemas import SlaveCardCreate, SlaveCardUpdate, SlaveCardResponse, SlaveCardListResponse, StandardResponse

router = APIRouter(prefix="/slave-cards", tags=["Slave Card Management"])

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
):
    """List all configured Slave Cards with comprehensive filtering and pagination."""
    q_db = db.query(SlaveCard)

    search_term = search or q

    # Determine if joins are needed
    need_gateway_join = (
        stngw_id is not None or
        station_id is not None or
        division_id is not None or
        zone_id is not None or
        search_term is not None
    )

    if need_gateway_join:
        q_db = q_db.join(Gateway, SlaveCard.gateway_id == Gateway.id)

    if gateway_id is not None:
        q_db = q_db.filter(SlaveCard.gateway_id == gateway_id)

    if stngw_id:
        q_db = q_db.filter(Gateway.stngw_id.ilike(f"%{stngw_id.strip()}%"))

    if card_address:
        q_db = q_db.filter(SlaveCard.card_address.ilike(f"%{card_address.strip()}%"))

    if card_type:
        q_db = q_db.filter(SlaveCard.card_type.ilike(f"%{card_type.strip()}%"))

    if station_id is not None:
        q_db = q_db.filter(Gateway.station_id == station_id)

    if division_id is not None or zone_id is not None:
        q_db = q_db.join(Station, Gateway.station_id == Station.id)
        if division_id is not None:
            q_db = q_db.filter(Station.division_id == division_id)
        if zone_id is not None:
            q_db = q_db.join(Division, Station.division_id == Division.id)
            q_db = q_db.filter(Division.zone_id == zone_id)

    if search_term:
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


@router.get("/{slave_card_id}", response_model=StandardResponse[SlaveCardResponse])
def get_slave_card(slave_card_id: int, db: Session = Depends(get_db)):
    """Retrieve details of a single Slave Card."""
    card = db.query(SlaveCard).filter(SlaveCard.id == slave_card_id).first()
    if not card:
        raise HTTPException(status_code=404, detail=f"Slave Card {slave_card_id} not found")
    return {
        "status": True,
        "message": "Success",
        "data": card
    }

@router.post("", response_model=StandardResponse[SlaveCardResponse], status_code=status.HTTP_201_CREATED)
def create_slave_card(payload: SlaveCardCreate, db: Session = Depends(get_db)):
    """Add/configure a new Slave Card under a Master Card/Gateway."""
    # 1. Validate Gateway exists
    gw = db.query(Gateway).filter(Gateway.id == payload.gateway_id).first()
    if not gw:
        raise HTTPException(
            status_code=404,
            detail=f"Gateway with ID {payload.gateway_id} not found"
        )
    
    # 2. Uppercase card address (e.g. "81" or "8A")
    card_addr = payload.card_address.strip().upper()
    
    # 3. Check for unique constraint violation: (gateway_id, card_address, card_type)
    existing = db.query(SlaveCard).filter(
        SlaveCard.gateway_id == payload.gateway_id,
        SlaveCard.card_address == card_addr,
        SlaveCard.card_type == payload.card_type,
    ).first()
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"Slave Card with address '{card_addr}' and type '{payload.card_type}' already configured under Gateway {payload.gateway_id}"
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
    return {
        "status": True,
        "message": "Success",
        "data": card
    }

@router.put("/{slave_card_id}", response_model=StandardResponse[SlaveCardResponse])
def update_slave_card(
    slave_card_id: int,
    payload: SlaveCardUpdate,
    db: Session = Depends(get_db),
):
    """Update configurations of a Slave Card."""
    card = db.query(SlaveCard).filter(SlaveCard.id == slave_card_id).first()
    if not card:
        raise HTTPException(status_code=404, detail=f"Slave Card {slave_card_id} not found")
        
    data = payload.model_dump(exclude_unset=True)
    
    if "gateway_id" in data:
        gw = db.query(Gateway).filter(Gateway.id == data["gateway_id"]).first()
        if not gw:
            raise HTTPException(status_code=404, detail=f"Gateway {data['gateway_id']} not found")
            
    if "card_address" in data:
        data["card_address"] = data["card_address"].strip().upper()
        
    # Check uniqueness if modifying unique keys
    new_gw = data.get("gateway_id", card.gateway_id)
    new_addr = data.get("card_address", card.card_address)
    new_type = data.get("card_type", card.card_type)
    
    if new_gw != card.gateway_id or new_addr != card.card_address or new_type != card.card_type:
        existing = db.query(SlaveCard).filter(
            SlaveCard.gateway_id == new_gw,
            SlaveCard.card_address == new_addr,
            SlaveCard.card_type == new_type,
            SlaveCard.id != slave_card_id,
        ).first()
        if existing:
            raise HTTPException(
                status_code=409,
                detail=f"Another Slave Card with address '{new_addr}' and type '{new_type}' exists under Gateway {new_gw}"
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
    return {
        "status": True,
        "message": "Success",
        "data": card
    }

@router.delete("/{slave_card_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_slave_card(slave_card_id: int, db: Session = Depends(get_db)):
    """Permanently delete a Slave Card. Referenced Channels will have their slave_card_id set to NULL."""
    card = db.query(SlaveCard).filter(SlaveCard.id == slave_card_id).first()
    if not card:
        raise HTTPException(status_code=404, detail=f"Slave Card {slave_card_id} not found")
        
    # Unlink Channels referencing this slave card
    db.query(AssetParameter).filter(AssetParameter.slave_card_id == slave_card_id).update(
        {"slave_card_id": None}
    )
    
    db.delete(card)
    db.commit()
