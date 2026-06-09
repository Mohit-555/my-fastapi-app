from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from typing import List, Optional
import random

from app.database import get_db
from app.models.models import EquipmentRoom, Station, Division, Zone
from app.models.schemas import EquipmentRoomResponse
from app.auth_utils import get_current_user

router = APIRouter(prefix="/equipment-room", tags=["Equipment Room"])


@router.get("/live", response_model=List[EquipmentRoomResponse])
def get_live_equipment_rooms(
    zone_id: Optional[int] = Query(None),
    division_id: Optional[int] = Query(None),
    station_id: Optional[int] = Query(None),
    room_type: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user),
):
    query = (
        db.query(EquipmentRoom)
        .join(Station, EquipmentRoom.station_id == Station.id)
        .join(Division, Station.division_id == Division.id)
        .join(Zone, Division.zone_id == Zone.id)
    )

    if zone_id is not None:
        query = query.filter(Division.zone_id == zone_id)
    if division_id is not None:
        query = query.filter(Station.division_id == division_id)
    if station_id is not None:
        query = query.filter(EquipmentRoom.station_id == station_id)
    if room_type is not None:
        query = query.filter(EquipmentRoom.room_type == room_type)

    rooms = query.all()

    response_data = []
    for r in rooms:
        # Generate random live values if temperature or humidity is not set in DB
        temp = r.temperature
        hum = r.humidity
        if temp is None:
            # Generate temperature between 28.0 and 42.0
            temp = round(random.uniform(28.0, 42.0), 1)
        if hum is None:
            # Generate humidity between 50 and 75
            hum = round(random.uniform(50.0, 75.0), 1)

        # Get parent details
        station = r.station
        division = station.division
        zone = division.zone

        response_data.append({
            "id": r.id,
            "station_id": r.station_id,
            "zone_id": zone.id,
            "zone_code": zone.zone_code,
            "zone_name": zone.zone_name,
            "division_id": division.id,
            "division_code": division.division_code,
            "division_name": division.division_name,
            "station_code": station.station_code,
            "station_name": station.station_name,
            "room_type": r.room_type,
            "temperature": temp,
            "humidity": hum,
            "updated_at": r.updated_at,
        })

    return response_data
