from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime, timedelta
import random
import hashlib
import csv
import io

from app.database import get_db
from app.models.models import EquipmentRoom, Station, Division, Zone
from app.models.schemas import EquipmentRoomResponse, EquipmentRoomHistoryResponse, EquipmentRoomHistoryRow
from app.auth_utils import get_current_user

router = APIRouter(prefix="/equipment-room", tags=["Equipment Room"])


def _generate_history_data(
    db: Session,
    zone_id: Optional[int],
    division_id: Optional[int],
    station_id: Optional[int],
    room_type: Optional[str],
    from_time: Optional[datetime],
    to_time: Optional[datetime],
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

    # Default to last 24 hours if from_time/to_time not specified
    if not to_time:
        to_time = datetime.utcnow()
    if not from_time:
        from_time = to_time - timedelta(hours=24)

    # Round down to nearest 30-minute mark
    start_dt = from_time.replace(minute=(from_time.minute // 30) * 30, second=0, microsecond=0)
    end_dt = to_time

    timestamps = []
    current_dt = start_dt
    while current_dt <= end_dt:
        timestamps.append(current_dt)
        current_dt += timedelta(minutes=30)

    # Reverse to list latest first
    timestamps.reverse()

    rows = []
    for ts in timestamps:
        for r in rooms:
            # Stable seed based on room id, type and timestamp
            seed_str = f"{r.id}-{r.room_type}-{ts.isoformat()}"
            seed_val = int(hashlib.md5(seed_str.encode('utf-8')).hexdigest(), 16) % 1000000
            local_rand = random.Random(seed_val)

            # Different realistic ranges based on room type
            if r.room_type == "RR":
                temp = round(local_rand.uniform(38.0, 42.0), 1)
                hum = round(local_rand.uniform(50.0, 60.0), 1)
            elif r.room_type == "IPS":
                temp = round(local_rand.uniform(30.0, 36.0), 1)
                hum = round(local_rand.uniform(55.0, 65.0), 1)
            else:  # BATT
                temp = round(local_rand.uniform(25.0, 31.0), 1)
                hum = round(local_rand.uniform(60.0, 70.0), 1)

            station = r.station
            division = station.division
            zone = division.zone

            rows.append({
                "id": f"{r.id}-{r.room_type}-{ts.strftime('%Y%m%d%H%M')}",
                "zone_code": zone.zone_code,
                "division_code": division.division_code,
                "station_code": station.station_code,
                "station_name": station.station_name,
                "timestamp": ts,
                "room_type": r.room_type,
                "temperature": temp,
                "humidity": hum,
            })
    return rows


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


@router.get("/history", response_model=EquipmentRoomHistoryResponse)
def get_equipment_room_history(
    zone_id: Optional[int] = Query(None),
    division_id: Optional[int] = Query(None),
    station_id: Optional[int] = Query(None),
    room_type: Optional[str] = Query(None),
    from_time: Optional[datetime] = Query(None),
    to_time: Optional[datetime] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1),
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user),
):
    rows = _generate_history_data(db, zone_id, division_id, station_id, room_type, from_time, to_time)
    total = len(rows)
    start_idx = (page - 1) * page_size
    end_idx = start_idx + page_size
    paginated_rows = rows[start_idx:end_idx]

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "rows": paginated_rows,
    }


@router.get("/history/download")
def download_equipment_room_history(
    zone_id: Optional[int] = Query(None),
    division_id: Optional[int] = Query(None),
    station_id: Optional[int] = Query(None),
    room_type: Optional[str] = Query(None),
    from_time: Optional[datetime] = Query(None),
    to_time: Optional[datetime] = Query(None),
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user),
):
    rows = _generate_history_data(db, zone_id, division_id, station_id, room_type, from_time, to_time)

    # Create CSV in-memory
    output = io.StringIO()
    writer = csv.writer(output)

    # Header matching the columns in the frontend
    writer.writerow([
        "SR",
        "ZONE",
        "DIVISION",
        "STATION",
        "DATE & TIME",
        "ROOM TYPE",
        "TEMP (°C)",
        "HUMIDITY (%)"
    ])

    for idx, r in enumerate(rows, start=1):
        formatted_time = r["timestamp"].strftime("%d %b, %H:%M")
        writer.writerow([
            idx,
            r["zone_code"],
            r["division_code"],
            r["station_code"],
            formatted_time,
            r["room_type"],
            r["temperature"],
            r["humidity"]
        ])

    output.seek(0)

    filename = f"equipment_room_history_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv"

    return StreamingResponse(
        io.BytesIO(output.getvalue().encode("utf-8")),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )
