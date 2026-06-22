from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List

from app.database import get_db
from app.models.models import Station, Division
from app.models.schemas import StationCreate, StationUpdate, StationResponse, DropdownOption

router = APIRouter(prefix="/stations", tags=["Stations"])


@router.get("/", response_model=List[StationResponse])
def get_all_stations(db: Session = Depends(get_db)):
    """Get all stations"""
    return db.query(Station).order_by(Station.station_name).all()


@router.get("/by-division/{division_id}", response_model=List[StationResponse])
def get_stations_by_division(division_id: int, db: Session = Depends(get_db)):
    """Get all stations under a specific division — use this for the Station dropdown after selecting a Division"""
    division = db.query(Division).filter(Division.id == division_id).first()
    if not division:
        raise HTTPException(status_code=404, detail=f"Division with id {division_id} not found")

    return db.query(Station).filter(Station.division_id == division_id).order_by(Station.station_name).all()


@router.get("/by-division/{division_id}/dropdown", response_model=List[DropdownOption])
def get_stations_dropdown(division_id: int, db: Session = Depends(get_db)):
    """Get stations for a division, formatted for frontend dropdown"""
    division = db.query(Division).filter(Division.id == division_id).first()
    if not division:
        raise HTTPException(status_code=404, detail=f"Division with id {division_id} not found")

    stations = db.query(Station).filter(Station.division_id == division_id).order_by(Station.station_name).all()
    return [
        DropdownOption(id=s.id, label=s.station_name, code=s.station_code, hex_id=s.station_id_hex)
        for s in stations
    ]


@router.get("/{station_id}", response_model=StationResponse)
def get_station(station_id: int, db: Session = Depends(get_db)):
    """Get a single station"""
    station = db.query(Station).filter(Station.id == station_id).first()
    if not station:
        raise HTTPException(status_code=404, detail=f"Station with id {station_id} not found")
    return station


@router.post("/", response_model=StationResponse, status_code=status.HTTP_201_CREATED)
def create_station(payload: StationCreate, db: Session = Depends(get_db)):
    """Create a new station"""
    division_id = payload.division_id
    if not division_id and payload.division:
        div_obj = db.query(Division).filter(Division.division_code == payload.division).first()
        if div_obj:
            division_id = div_obj.id

    if not division_id:
        raise HTTPException(status_code=400, detail="Either division_id or division (code) must be provided")

    division = db.query(Division).filter(Division.id == division_id).first()
    if not division:
        raise HTTPException(status_code=404, detail=f"Division with id {division_id} not found")

    station_data = payload.model_dump()
    station_data["division_id"] = division_id
    for k in ("division", "zone"):
        if k in station_data:
            del station_data[k]

    if not station_data.get("station_id_hex"):
        all_stats = db.query(Station).filter(Station.division_id == division_id).all()
        existing_hex_vals = []
        for s in all_stats:
            try:
                existing_hex_vals.append(int(s.station_id_hex, 16))
            except ValueError:
                pass
        next_val = max(existing_hex_vals) + 1 if existing_hex_vals else 0
        station_data["station_id_hex"] = f"{next_val:02X}"

    station = Station(**station_data)
    db.add(station)
    db.commit()
    db.refresh(station)
    return station


@router.put("/{station_id}", response_model=StationResponse)
def update_station(station_id: int, payload: StationUpdate, db: Session = Depends(get_db)):
    """Update a station"""
    station = db.query(Station).filter(Station.id == station_id).first()
    if not station:
        raise HTTPException(status_code=404, detail=f"Station with id {station_id} not found")

    division_id = payload.division_id
    if not division_id and payload.division:
        div_obj = db.query(Division).filter(Division.division_code == payload.division).first()
        if div_obj:
            division_id = div_obj.id

    if division_id:
        division = db.query(Division).filter(Division.id == division_id).first()
        if not division:
            raise HTTPException(status_code=404, detail=f"Division with id {division_id} not found")
        station.division_id = division_id

    for field, value in payload.model_dump(exclude_unset=True).items():
        if field in ("division_id", "division", "zone"):
            continue
        setattr(station, field, value)

    db.commit()
    db.refresh(station)
    return station


@router.delete("/{station_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_station(station_id: int, db: Session = Depends(get_db)):
    """Delete a station"""
    station = db.query(Station).filter(Station.id == station_id).first()
    if not station:
        raise HTTPException(status_code=404, detail=f"Station with id {station_id} not found")

    from app.models.models import Threshold, AlertEvent, MaintenanceMode
    db.query(AlertEvent).filter(AlertEvent.station_id == station_id).update({"asset_id": None})
    db.query(MaintenanceMode).filter(MaintenanceMode.station_id == station_id).update({"asset_id": None})
    db.query(Threshold).filter(Threshold.station_id == station_id).delete()

    db.delete(station)
    db.commit()
