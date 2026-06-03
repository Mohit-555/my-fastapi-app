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
    division = db.query(Division).filter(Division.id == payload.division_id).first()
    if not division:
        raise HTTPException(status_code=404, detail=f"Division with id {payload.division_id} not found")

    station = Station(**payload.model_dump())
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

    if payload.division_id:
        division = db.query(Division).filter(Division.id == payload.division_id).first()
        if not division:
            raise HTTPException(status_code=404, detail=f"Division with id {payload.division_id} not found")

    for field, value in payload.model_dump(exclude_unset=True).items():
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

    db.delete(station)
    db.commit()
