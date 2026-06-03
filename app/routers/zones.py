from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List

from app.database import get_db
from app.models.models import Zone
from app.models.schemas import ZoneCreate, ZoneUpdate, ZoneResponse, ZoneWithDivisions, DropdownOption

router = APIRouter(prefix="/zones", tags=["Zones"])


@router.get("/", response_model=List[ZoneResponse])
def get_all_zones(db: Session = Depends(get_db)):
    """Get all zones"""
    return db.query(Zone).order_by(Zone.zone_name).all()


@router.get("/dropdown", response_model=List[DropdownOption])
def get_zones_dropdown(db: Session = Depends(get_db)):
    """Get zones formatted for frontend dropdown"""
    zones = db.query(Zone).order_by(Zone.zone_name).all()
    return [
        DropdownOption(id=z.id, label=z.zone_name, code=z.zone_code, hex_id=z.zone_id_hex)
        for z in zones
    ]


@router.get("/{zone_id}", response_model=ZoneWithDivisions)
def get_zone(zone_id: int, db: Session = Depends(get_db)):
    """Get a single zone with all its divisions"""
    zone = db.query(Zone).filter(Zone.id == zone_id).first()
    if not zone:
        raise HTTPException(status_code=404, detail=f"Zone with id {zone_id} not found")
    return zone


@router.post("/", response_model=ZoneResponse, status_code=status.HTTP_201_CREATED)
def create_zone(payload: ZoneCreate, db: Session = Depends(get_db)):
    """Create a new zone"""
    existing = db.query(Zone).filter(Zone.zone_code == payload.zone_code).first()
    if existing:
        raise HTTPException(status_code=400, detail=f"Zone with code '{payload.zone_code}' already exists")

    zone = Zone(**payload.model_dump())
    db.add(zone)
    db.commit()
    db.refresh(zone)
    return zone


@router.put("/{zone_id}", response_model=ZoneResponse)
def update_zone(zone_id: int, payload: ZoneUpdate, db: Session = Depends(get_db)):
    """Update a zone"""
    zone = db.query(Zone).filter(Zone.id == zone_id).first()
    if not zone:
        raise HTTPException(status_code=404, detail=f"Zone with id {zone_id} not found")

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(zone, field, value)

    db.commit()
    db.refresh(zone)
    return zone


@router.delete("/{zone_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_zone(zone_id: int, db: Session = Depends(get_db)):
    """Delete a zone (also deletes related divisions and stations)"""
    zone = db.query(Zone).filter(Zone.id == zone_id).first()
    if not zone:
        raise HTTPException(status_code=404, detail=f"Zone with id {zone_id} not found")

    db.delete(zone)
    db.commit()
