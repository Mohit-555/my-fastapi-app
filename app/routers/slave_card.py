from datetime import datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.database import get_db
from app.models.models import SlaveCard, Gateway, AssetParameter
from app.models.schemas import SlaveCardCreate, SlaveCardUpdate, SlaveCardResponse, SlaveCardListResponse

router = APIRouter(prefix="/slave-cards", tags=["Slave Card Management"])

@router.get("", response_model=SlaveCardListResponse)
def list_slave_cards(
    gateway_id: Optional[int] = Query(None, description="Filter by Gateway ID"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
):
    """List all configured Slave Cards with optional Gateway filtering."""
    q = db.query(SlaveCard)
    if gateway_id is not None:
        q = q.filter(SlaveCard.gateway_id == gateway_id)
        
    total = q.count()
    total_pages = (total + page_size - 1) // page_size if total else 0
    offset = (page - 1) * page_size
    rows = q.order_by(SlaveCard.id).offset(offset).limit(page_size).all()
    
    return SlaveCardListResponse(
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
        rows=rows,
    )

@router.get("/{slave_card_id}", response_model=SlaveCardResponse)
def get_slave_card(slave_card_id: int, db: Session = Depends(get_db)):
    """Retrieve details of a single Slave Card."""
    card = db.query(SlaveCard).filter(SlaveCard.id == slave_card_id).first()
    if not card:
        raise HTTPException(status_code=404, detail=f"Slave Card {slave_card_id} not found")
    return card

@router.post("", response_model=SlaveCardResponse, status_code=status.HTTP_201_CREATED)
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
    return card

@router.put("/{slave_card_id}", response_model=SlaveCardResponse)
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
    return card

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
