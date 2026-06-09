from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List

from app.database import get_db
from app.models.models import Division, Zone
from app.models.schemas import DivisionCreate, DivisionUpdate, DivisionResponse, DivisionWithStations, DropdownOption

router = APIRouter(prefix="/divisions", tags=["Divisions"])


@router.get("/", response_model=List[DivisionResponse])
def get_all_divisions(db: Session = Depends(get_db)):
    """Get all divisions"""
    return db.query(Division).order_by(Division.division_name).all()


@router.get("/by-zone/{zone_id}", response_model=List[DivisionResponse])
def get_divisions_by_zone(zone_id: int, db: Session = Depends(get_db)):
    """Get all divisions under a specific zone — use this for the Division dropdown after selecting a Zone"""
    zone = db.query(Zone).filter(Zone.id == zone_id).first()
    if not zone:
        raise HTTPException(status_code=404, detail=f"Zone with id {zone_id} not found")

    return db.query(Division).filter(Division.zone_id == zone_id).order_by(Division.division_name).all()


@router.get("/by-zone/{zone_id}/dropdown", response_model=List[DropdownOption])
def get_divisions_dropdown(zone_id: int, db: Session = Depends(get_db)):
    """Get divisions for a zone, formatted for frontend dropdown"""
    zone = db.query(Zone).filter(Zone.id == zone_id).first()
    if not zone:
        raise HTTPException(status_code=404, detail=f"Zone with id {zone_id} not found")

    divisions = db.query(Division).filter(Division.zone_id == zone_id).order_by(Division.division_name).all()
    return [
        DropdownOption(id=d.id, label=d.division_name, code=d.division_code, hex_id=d.division_id_hex)
        for d in divisions
    ]


@router.get("/{division_id}", response_model=DivisionWithStations)
def get_division(division_id: int, db: Session = Depends(get_db)):
    """Get a single division with all its stations"""
    division = db.query(Division).filter(Division.id == division_id).first()
    if not division:
        raise HTTPException(status_code=404, detail=f"Division with id {division_id} not found")
    return division


@router.post("/", response_model=DivisionResponse, status_code=status.HTTP_201_CREATED)
def create_division(payload: DivisionCreate, db: Session = Depends(get_db)):
    """Create a new division"""
    zone_id = payload.zone_id
    if not zone_id and payload.zone:
        zone_obj = db.query(Zone).filter(Zone.zone_code == payload.zone).first()
        if zone_obj:
            zone_id = zone_obj.id

    if not zone_id:
        raise HTTPException(status_code=400, detail="Either zone_id or zone (code) must be provided")

    zone = db.query(Zone).filter(Zone.id == zone_id).first()
    if not zone:
        raise HTTPException(status_code=404, detail=f"Zone with id {zone_id} not found")

    division_data = payload.model_dump()
    division_data["zone_id"] = zone_id
    if "zone" in division_data:
        del division_data["zone"]

    if not division_data.get("division_id_hex"):
        all_divs = db.query(Division).filter(Division.zone_id == zone_id).all()
        existing_hex_vals = []
        for d in all_divs:
            try:
                existing_hex_vals.append(int(d.division_id_hex, 16))
            except ValueError:
                pass
        next_val = max(existing_hex_vals) + 1 if existing_hex_vals else 0
        division_data["division_id_hex"] = f"{next_val:02X}"

    division = Division(**division_data)
    db.add(division)
    db.commit()
    db.refresh(division)
    return division


@router.put("/{division_id}", response_model=DivisionResponse)
def update_division(division_id: int, payload: DivisionUpdate, db: Session = Depends(get_db)):
    """Update a division"""
    division = db.query(Division).filter(Division.id == division_id).first()
    if not division:
        raise HTTPException(status_code=404, detail=f"Division with id {division_id} not found")

    zone_id = payload.zone_id
    if not zone_id and payload.zone:
        zone_obj = db.query(Zone).filter(Zone.zone_code == payload.zone).first()
        if zone_obj:
            zone_id = zone_obj.id

    if zone_id:
        zone = db.query(Zone).filter(Zone.id == zone_id).first()
        if not zone:
            raise HTTPException(status_code=404, detail=f"Zone with id {zone_id} not found")
        division.zone_id = zone_id

    for field, value in payload.model_dump(exclude_unset=True).items():
        if field in ("zone_id", "zone"):
            continue
        setattr(division, field, value)

    db.commit()
    db.refresh(division)
    return division


@router.delete("/{division_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_division(division_id: int, db: Session = Depends(get_db)):
    """Delete a division (also deletes related stations)"""
    division = db.query(Division).filter(Division.id == division_id).first()
    if not division:
        raise HTTPException(status_code=404, detail=f"Division with id {division_id} not found")

    db.delete(division)
    db.commit()
