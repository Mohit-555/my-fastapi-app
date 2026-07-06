"""
Assets router — serves:
  1. Asset type dropdown (with display groups matching the dashboard UI)
  2. Parameter type and representation listings
  3. Threshold CRUD (create / read / update / delete)
"""
import csv
import io
from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.models import AssetInventory, Division, Threshold, Station, Zone, AssetTypeMaster, Asset, Gateway, AssetParameter, Role
from app.models.schemas import (
    AssetDetailResponse,
    AssetDetailRow,
    AssetInventoryCreate,
    AssetInventoryResponse,
    AssetInventoryUpdate,
    AssetMakeOption,
    AssetTypeOption,
    AssetTypeGroupOption,
    ParameterTypeOption,
    ParameterReprOption,
    ThresholdCreate,
    ThresholdUpdate,
    ThresholdResponse,
    ZoneMinimalResponse,
    DivisionMinimalResponse,
    StationMinimalResponse,
    AssetFiltersResponse,
    DropdownOption,
    AlertFilterOption,
    AssetCreate,
    AssetListResponse,
    AssetResponse,
    AssetUpdate,
    AssetParameterUpdate,
    AssetParameterResponse,
    AssetParameterListResponse,
)
from app.constants import (
    ASSET_TYPE_MAP,
    ASSET_TYPE_DISPLAY_GROUPS,
    PARAMETER_TYPE_MAP,
    PARAMETER_REPR_MAP,
)

router = APIRouter(prefix="/assets", tags=["Assets & Thresholds"])


def _blank_to_none(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    val = value.strip()
    return None if val == "" else val


def _resolve_asset_types_to_hex(db: Session, asset_type: Optional[str]) -> Optional[str]:
    asset_type = _blank_to_none(asset_type)
    if not asset_type:
        return None

    parts = [p.strip() for p in asset_type.split(",") if p.strip()]
    if all(p.isdigit() for p in parts):
        ids = [int(p) for p in parts]
        db_types = db.query(AssetTypeMaster).filter(AssetTypeMaster.id.in_(ids)).all()
        hexes = [t.asset_type_id for t in db_types if t.asset_type_id]
        if not hexes:
            return "IMPOSSIBLE_HEX"
        return ",".join(hexes)

    hex_list = []
    for part in parts:
        if part.upper() in ASSET_TYPE_MAP:
            hex_list.append(part.upper())
        else:
            group_hexes = ASSET_TYPE_DISPLAY_GROUPS.get(part)
            if group_hexes:
                hex_list.extend(group_hexes)
    if hex_list:
        return ",".join(hex_list)
    return None


# ── Asset Type Endpoints ──────────────────────────────────────────────────────

@router.get("/types", response_model=List[AssetTypeOption])
def list_asset_types(db: Session = Depends(get_db)):
    """
    Return a flat list of all asset types.
    Each entry includes the display group label so the frontend can group them.
    """
    # Build reverse map: hex → group_label
    hex_to_group: dict[str, str] = {}
    for group_label, hexes in ASSET_TYPE_DISPLAY_GROUPS.items():
        for h in hexes:
            hex_to_group[h] = group_label

    db_types = db.query(AssetTypeMaster).order_by(AssetTypeMaster.asset_type_id).all()
    result = []
    for idx, t in enumerate(db_types, start=1):
        result.append(AssetTypeOption(
            id=idx,
            hex_id=t.asset_type_id,
            code=t.asset_type_code,
            label=t.asset_type_name,
            group_label=hex_to_group.get(t.asset_type_id, t.asset_type_name),
        ))
    return result


@router.get("/types/grouped", response_model=List[AssetTypeGroupOption])
def list_asset_types_grouped(db: Session = Depends(get_db)):
    """
    Return asset types grouped by dashboard display group.
    This directly mirrors the Asset Type dropdown in the Telemetry Live screen:
    All / Point Machine / DC Track Circuit / AC Track Circuit /
    Main Signal / Axle Counter / LC Gate / BPAC / IPS / Battery
    """
    db_types_map = {t.asset_type_id: t for t in db.query(AssetTypeMaster).all()}

    groups = []
    group_id = 1
    member_id = 1
    for group_label, hexes in ASSET_TYPE_DISPLAY_GROUPS.items():
        members = []
        for h in hexes:
            t = db_types_map.get(h)
            if t:
                members.append(AssetTypeOption(
                    id=member_id,
                    hex_id=h,
                    code=t.asset_type_code,
                    label=t.asset_type_name,
                    group_label=group_label,
                ))
                member_id += 1
        groups.append(AssetTypeGroupOption(
            id=group_id,
            group_label=group_label,
            asset_type_hexes=hexes,
            members=members,
        ))
        group_id += 1
    return groups


# ── Parameter Type Endpoints ──────────────────────────────────────────────────

@router.get("/parameters", response_model=List[ParameterTypeOption])
def list_parameter_types(
    asset_type: Optional[str] = Query(
        None,
        description="Filter by asset_type database ID to get only relevant parameters"
    ),
    db: Session = Depends(get_db),
):
    """
    Return all known parameter types (bytes 4–5 of para_id).
    These become the chart panel titles (e.g. 'Avg Current (A)', 'Peak Current (A)').

    Optionally filter by asset_type_hex to return only parameters relevant
    to a specific asset — useful for dynamically populating a parameter selector.
    """
    # For now the map is global; asset-specific filtering can be added
    # when a param-to-asset mapping table is defined.
    result = [
        ParameterTypeOption(
            hex_id=hex_id,
            code=info[0],
            label=info[1],
            unit=info[2],
        )
        for hex_id, info in PARAMETER_TYPE_MAP.items()
    ]
    return sorted(result, key=lambda x: x.hex_id)


@router.get("/representations", response_model=List[ParameterReprOption])
def list_representations():
    """
    Return all parameter representation types (byte 8 of para_id).
    E.g. Instantaneous, Average, Maximum, Minimum, RMS.
    """
    return [
        ParameterReprOption(hex_id=h, code=info[0], label=info[1])
        for h, info in PARAMETER_REPR_MAP.items()
    ]


# ── Asset Inventory / Asset Detail ────────────────────────────────────────────

def _asset_detail_query(
    db: Session,
    zone_id: Optional[int],
    division_id: Optional[int],
    station_id: Optional[int],
    asset_type_hex: Optional[str],
    asset_make: Optional[str],
):
    q = (
        db.query(
            AssetInventory.id.label("id"),
            Zone,
            Division,
            Station,
            AssetInventory.asset_type_hex.label("asset_type_hex"),
            AssetInventory.asset_make.label("asset_make"),
            func.sum(AssetInventory.count).label("count"),
        )
        .join(Station, Station.id == AssetInventory.station_id)
        .join(Division, Division.id == Station.division_id)
        .join(Zone, Zone.id == Division.zone_id)
    )

    if zone_id is not None:
        q = q.filter(Zone.id == zone_id)
    if division_id is not None:
        q = q.filter(Division.id == division_id)
    if station_id is not None:
        q = q.filter(Station.id == station_id)
    if asset_type_hex:
        hex_list = [h.strip().upper() for h in asset_type_hex.split(",") if h.strip()]
        if len(hex_list) == 1:
            q = q.filter(AssetInventory.asset_type_hex == hex_list[0])
        elif len(hex_list) > 1:
            q = q.filter(AssetInventory.asset_type_hex.in_(hex_list))
    if asset_make:
        q = q.filter(func.lower(AssetInventory.asset_make) == asset_make.lower())

    return (
        q.group_by(
            AssetInventory.id,
            Zone.id,
            Division.id,
            Station.id,
            AssetInventory.asset_type_hex,
            AssetInventory.asset_make,
        )
        .order_by(
            Zone.zone_code,
            Division.division_code,
            Station.station_code,
            AssetInventory.asset_type_hex,
            AssetInventory.asset_make,
        )
    )


def _asset_detail_rows(raw_rows) -> List[AssetDetailRow]:
    rows: List[AssetDetailRow] = []
    for idx, row in enumerate(raw_rows, start=1):
        asset_info = ASSET_TYPE_MAP.get(row.asset_type_hex)
        rows.append(AssetDetailRow(
            id=row.id,
            sr=idx,
            zone_id=row.Zone.id,
            zone=ZoneMinimalResponse.model_validate(row.Zone),
            division_id=row.Division.id,
            division=DivisionMinimalResponse.model_validate(row.Division),
            station_id=row.Station.id,
            station=StationMinimalResponse.model_validate(row.Station),
            asset_type_hex=row.asset_type_hex,
            asset_type=asset_info[1] if asset_info else row.asset_type_hex,
            asset_make=row.asset_make,
            count=int(row.count or 0),
        ))
    return rows


@router.get("/detail", response_model=AssetDetailResponse)
def get_asset_detail(
    zone_id: Optional[int] = Query(None),
    division_id: Optional[int] = Query(None),
    station_id: Optional[int] = Query(None),
    asset_type: Optional[str] = Query(None),
    asset_make: Optional[str] = Query(None),
    view: str = Query("table", description="Frontend view mode. Currently supports table data."),
    db: Session = Depends(get_db),
):
    """
    Return Asset Detail report rows for the frontend table.

    Filters map to the UI controls: Zone, Division, Station, Asset Type,
    View, and Asset Make.
    """
    asset_type_hex = _resolve_asset_types_to_hex(db, asset_type)
    raw_rows = _asset_detail_query(
        db=db,
        zone_id=zone_id,
        division_id=division_id,
        station_id=station_id,
        asset_type_hex=asset_type_hex,
        asset_make=asset_make,
    ).all()
    rows = _asset_detail_rows(raw_rows)
    return AssetDetailResponse(
        as_on=date.today().isoformat(),
        total=sum(row.count for row in rows),
        rows=rows,
    )


@router.get("/detail/download")
def download_asset_detail(
    zone_id: Optional[int] = Query(None),
    division_id: Optional[int] = Query(None),
    station_id: Optional[int] = Query(None),
    asset_type: Optional[str] = Query(None),
    asset_make: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """Download the Asset Detail report as CSV."""
    asset_type_hex = _resolve_asset_types_to_hex(db, asset_type)
    raw_rows = _asset_detail_query(
        db=db,
        zone_id=zone_id,
        division_id=division_id,
        station_id=station_id,
        asset_type_hex=asset_type_hex,
        asset_make=asset_make,
    ).all()
    rows = _asset_detail_rows(raw_rows)

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["SR", "ZONE", "DIVISION", "STATION", "ASSET TYPE", "ASSET MAKE", "COUNT"])
    for row in rows:
        writer.writerow([
            row.sr,
            row.zone.zone_code if row.zone else "",
            row.division.division_code if row.division else "",
            row.station.station_code if row.station else "",
            row.asset_type,
            row.asset_make,
            row.count,
        ])
    writer.writerow(["", "", "", "", "", "Total", sum(row.count for row in rows)])
    output.seek(0)

    filename = f"asset_detail_{date.today().isoformat()}.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/makes", response_model=List[AssetMakeOption])
def list_asset_makes(
    asset_type: Optional[str] = Query(None),
    station_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
):
    """Return distinct asset makes for the Asset Make dropdown."""
    asset_type_hex = _resolve_asset_types_to_hex(db, asset_type)
    q = db.query(AssetInventory.asset_make).distinct()
    if asset_type_hex:
        hex_list = [h.strip().upper() for h in asset_type_hex.split(",") if h.strip()]
        if len(hex_list) == 1:
            q = q.filter(AssetInventory.asset_type_hex == hex_list[0])
        elif len(hex_list) > 1:
            q = q.filter(AssetInventory.asset_type_hex.in_(hex_list))
    if station_id is not None:
        q = q.filter(AssetInventory.station_id == station_id)

    makes = [row.asset_make for row in q.order_by(AssetInventory.asset_make).all()]
    return [
        AssetMakeOption(id=idx, label=make, value=make)
        for idx, make in enumerate(makes, start=1)
    ]


@router.get("/filters", response_model=AssetFiltersResponse)
def get_asset_filters(db: Session = Depends(get_db)):
    """Return dropdown data for the Asset Detail / Inventory filter bar."""
    zones = db.query(Zone).order_by(Zone.zone_name).all()
    divisions = db.query(Division).order_by(Division.division_name).all()
    stations = db.query(Station).order_by(Station.station_name).all()

    makes_rows = db.query(AssetInventory.asset_make).distinct().order_by(AssetInventory.asset_make).all()
    makes = [row.asset_make for row in makes_rows if row.asset_make]
    asset_makes_list = [
        AssetMakeOption(id=idx, label=make, value=make)
        for idx, make in enumerate(makes, start=1)
    ]

    # Fetch all assets to build the interconnected list for asset types
    asset_locations = (
        db.query(
            Asset.asset_type_hex,
            Asset.station_id,
            Station.station_code,
            Station.station_name,
            Station.division_id,
            Division.division_code,
            Division.division_name,
            Division.zone_id,
            Zone.zone_code,
            Zone.zone_name
        )
        .join(Station, Station.id == Asset.station_id)
        .join(Division, Division.id == Station.division_id)
        .join(Zone, Zone.id == Division.zone_id)
        .distinct()
        .all()
    )

    db_types_map = {t.asset_type_id: t for t in db.query(AssetTypeMaster).all()}

    flat_asset_types = []
    member_id = 1
    for group_label, hexes in ASSET_TYPE_DISPLAY_GROUPS.items():
        for h in hexes:
            t = db_types_map.get(h)
            if t:
                for row in asset_locations:
                    if row.asset_type_hex.upper() == h.upper():
                        flat_asset_types.append(AssetTypeOption(
                            id=member_id,
                            hex_id=h,
                            code=t.asset_type_code,
                            label=t.asset_type_name,
                            group_label=group_label,
                            zone_id=row.zone_id,
                            zone_code=row.zone_code,
                            zone_name=row.zone_name,
                            division_id=row.division_id,
                            division_code=row.division_code,
                            division_name=row.division_name,
                            station_id=row.station_id,
                            station_code=row.station_code,
                            station_name=row.station_name,
                        ))
                        member_id += 1

    zones_by_id = {z.id: z for z in zones}
    divisions_by_id = {d.id: d for d in divisions}

    zones_list = [
        DropdownOption(id=z.id, label=z.zone_name, code=z.zone_code, hex_id=z.zone_id_hex, value=z.zone_code, zone_name=z.zone_name)
        for z in zones
    ]

    divisions_list = []
    for d in divisions:
        z = zones_by_id.get(d.zone_id)
        divisions_list.append(DropdownOption(
            id=d.id,
            label=d.division_name,
            code=d.division_code,
            hex_id=d.division_id_hex,
            value=d.division_code,
            zone_id=d.zone_id,
            zone_code=z.zone_code if z else None,
            zone_name=z.zone_name if z else None,
            division_name=d.division_name
        ))

    stations_list = []
    for s in stations:
        d = divisions_by_id.get(s.division_id)
        z = zones_by_id.get(d.zone_id) if d else None
        stations_list.append(DropdownOption(
            id=s.id,
            label=s.station_name,
            code=s.station_code,
            hex_id=s.station_id_hex,
            value=s.station_code,
            division_id=s.division_id,
            division_code=d.division_code if d else None,
            division_name=d.division_name if d else None,
            zone_id=d.zone_id if d else None,
            zone_code=z.zone_code if z else None,
            zone_name=z.zone_name if z else None,
            station_name=s.station_name
        ))

    roles = db.query(Role).order_by(Role.id).all()
    roles_list = [
        AlertFilterOption(id=r.id, label=r.display_name or r.name, value=str(r.id))
        for r in roles
    ]

    return AssetFiltersResponse(
        zones=zones_list,
        divisions=divisions_list,
        stations=stations_list,
        asset_types=flat_asset_types,
        asset_makes=asset_makes_list,
        roles=roles_list,
    )


@router.get("/inventory", response_model=List[AssetInventoryResponse])
def list_asset_inventory(
    station_id: Optional[int] = Query(None),
    asset_type: Optional[str] = Query(None),
    asset_make: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """List raw asset inventory records used by the Asset Detail report."""
    asset_type_hex = _resolve_asset_types_to_hex(db, asset_type)
    q = db.query(AssetInventory)
    if station_id is not None:
        q = q.filter(AssetInventory.station_id == station_id)
    if asset_type_hex:
        hex_list = [h.strip().upper() for h in asset_type_hex.split(",") if h.strip()]
        if len(hex_list) == 1:
            q = q.filter(AssetInventory.asset_type_hex == hex_list[0])
        elif len(hex_list) > 1:
            q = q.filter(AssetInventory.asset_type_hex.in_(hex_list))
    if asset_make:
        q = q.filter(func.lower(AssetInventory.asset_make) == asset_make.lower())
    return q.order_by(AssetInventory.station_id, AssetInventory.asset_type_hex, AssetInventory.asset_make).all()


@router.post("/inventory", response_model=AssetInventoryResponse, status_code=status.HTTP_201_CREATED)
def create_asset_inventory(payload: AssetInventoryCreate, db: Session = Depends(get_db)):
    """Create a raw asset inventory record."""
    if payload.asset_type_hex.upper() not in ASSET_TYPE_MAP:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown asset_type_hex '{payload.asset_type_hex}'. See GET /assets/types."
        )
    station = db.query(Station).filter(Station.id == payload.station_id).first()
    if not station:
        raise HTTPException(status_code=404, detail=f"Station {payload.station_id} not found")
    if payload.count < 0:
        raise HTTPException(status_code=400, detail="count must be greater than or equal to 0")

    record = AssetInventory(
        station_id=payload.station_id,
        asset_type_hex=payload.asset_type_hex.upper(),
        asset_make=payload.asset_make.strip(),
        count=payload.count,
    )
    db.add(record)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Asset inventory for this station_id + asset_type_hex + asset_make already exists. Use PUT to update it."
        )
    db.refresh(record)
    return record


@router.put("/inventory/{inventory_id}", response_model=AssetInventoryResponse)
def update_asset_inventory(
    inventory_id: int,
    payload: AssetInventoryUpdate,
    db: Session = Depends(get_db),
):
    """Update a raw asset inventory record."""
    record = db.query(AssetInventory).filter(AssetInventory.id == inventory_id).first()
    if not record:
        raise HTTPException(status_code=404, detail=f"Asset inventory {inventory_id} not found")

    data = payload.model_dump(exclude_unset=True)
    if "station_id" in data:
        station = db.query(Station).filter(Station.id == data["station_id"]).first()
        if not station:
            raise HTTPException(status_code=404, detail=f"Station {data['station_id']} not found")
    if "asset_type_hex" in data:
        data["asset_type_hex"] = data["asset_type_hex"].upper()
        if data["asset_type_hex"] not in ASSET_TYPE_MAP:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown asset_type_hex '{data['asset_type_hex']}'. See GET /assets/types."
            )
    if "asset_make" in data:
        data["asset_make"] = data["asset_make"].strip()
    if "count" in data and data["count"] < 0:
        raise HTTPException(status_code=400, detail="count must be greater than or equal to 0")

    for field, value in data.items():
        setattr(record, field, value)

    try:
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Asset inventory for this station_id + asset_type_hex + asset_make already exists."
        )
    db.refresh(record)
    return record


@router.delete("/inventory/{inventory_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_asset_inventory(inventory_id: int, db: Session = Depends(get_db)):
    """Delete a raw asset inventory record."""
    record = db.query(AssetInventory).filter(AssetInventory.id == inventory_id).first()
    if not record:
        raise HTTPException(status_code=404, detail=f"Asset inventory {inventory_id} not found")
    db.delete(record)
    db.commit()


# ── Threshold CRUD ────────────────────────────────────────────────────────────

@router.get("/thresholds", response_model=List[ThresholdResponse])
def list_thresholds(
    asset_type: Optional[str] = Query(None),
    station_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
):
    """
    List thresholds. Filter by asset_type_hex and/or station_id.
    Results with station_id=NULL are global defaults.
    """
    asset_type_hex = _resolve_asset_types_to_hex(db, asset_type)
    q = db.query(Threshold)
    if asset_type_hex:
        hex_list = [h.strip().upper() for h in asset_type_hex.split(",") if h.strip()]
        if len(hex_list) == 1:
            q = q.filter(Threshold.asset_type_hex == hex_list[0])
        elif len(hex_list) > 1:
            q = q.filter(Threshold.asset_type_hex.in_(hex_list))
    if station_id is not None:
        q = q.filter(Threshold.station_id == station_id)
    return q.order_by(Threshold.asset_type_hex, Threshold.parameter_type_hex).all()


@router.get("/thresholds/{threshold_id}", response_model=ThresholdResponse)
def get_threshold(threshold_id: int, db: Session = Depends(get_db)):
    t = db.query(Threshold).filter(Threshold.id == threshold_id).first()
    if not t:
        raise HTTPException(status_code=404, detail=f"Threshold {threshold_id} not found")
    return t


@router.post("/thresholds", response_model=ThresholdResponse, status_code=status.HTTP_201_CREATED)
def create_threshold(payload: ThresholdCreate, db: Session = Depends(get_db)):
    """
    Create a new threshold.

    Set station_id=null for a global default, or supply a station_id for a
    station-specific override. The lookup always tries station-specific first.

    Example — global default for Point Machine Peak Current:
      {
        "asset_type_hex": "00",
        "parameter_type_hex": "02",
        "warning_high": 9.0,
        "critical_high": 11.0,
        "unit": "A"
      }
    """
    if payload.asset_type_hex.upper() not in ASSET_TYPE_MAP:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown asset_type_hex '{payload.asset_type_hex}'. See GET /assets/types."
        )
    if payload.parameter_type_hex.upper() not in PARAMETER_TYPE_MAP:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown parameter_type_hex '{payload.parameter_type_hex}'. See GET /assets/parameters."
        )
    if payload.station_id:
        stn = db.query(Station).filter(Station.id == payload.station_id).first()
        if not stn:
            raise HTTPException(status_code=404, detail=f"Station {payload.station_id} not found")

    t = Threshold(
        asset_type_hex=payload.asset_type_hex.upper(),
        parameter_type_hex=payload.parameter_type_hex.upper(),
        station_id=payload.station_id,
        warning_low=payload.warning_low,
        warning_high=payload.warning_high,
        critical_low=payload.critical_low,
        critical_high=payload.critical_high,
        unit=payload.unit,
        description=payload.description,
    )
    db.add(t)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="A threshold for this asset_type_hex + parameter_type_hex + station_id already exists. Use PUT to update it."
        )
    db.refresh(t)
    return t


@router.put("/thresholds/{threshold_id}", response_model=ThresholdResponse)
def update_threshold(threshold_id: int, payload: ThresholdUpdate, db: Session = Depends(get_db)):
    """Update threshold values."""
    t = db.query(Threshold).filter(Threshold.id == threshold_id).first()
    if not t:
        raise HTTPException(status_code=404, detail=f"Threshold {threshold_id} not found")

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(t, field, value)

    db.commit()
    db.refresh(t)
    return t


@router.delete("/thresholds/{threshold_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_threshold(threshold_id: int, db: Session = Depends(get_db)):
    """Delete a threshold."""
    t = db.query(Threshold).filter(Threshold.id == threshold_id).first()
    if not t:
        raise HTTPException(status_code=404, detail=f"Threshold {threshold_id} not found")
    db.delete(t)
    db.commit()


@router.get("/thresholds/resolve/{asset_type_hex}/{parameter_type_hex}",
            response_model=Optional[ThresholdResponse])
def resolve_threshold(
    asset_type_hex: str,
    parameter_type_hex: str,
    station_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
):
    """
    Resolve the effective threshold for a given asset + parameter combination,
    respecting station-specific override priority.

    Returns the station-specific threshold if one exists, otherwise the global default.
    Returns null if no threshold is configured.
    """
    if station_id:
        t = db.query(Threshold).filter(
            Threshold.asset_type_hex == asset_type_hex.upper(),
            Threshold.parameter_type_hex == parameter_type_hex.upper(),
            Threshold.station_id == station_id,
        ).first()
        if t:
            return t

    return db.query(Threshold).filter(
        Threshold.asset_type_hex == asset_type_hex.upper(),
        Threshold.parameter_type_hex == parameter_type_hex.upper(),
        Threshold.station_id.is_(None),
    ).first()


# ── Physical Asset CRUD ───────────────────────────────────────────────────────

def _build_response(record: Asset) -> AssetResponse:
    """Resolve joined fields into the response schema."""
    asset_type_name = None
    asset_type_code = None
    if record.asset_type:
        asset_type_name = record.asset_type.asset_type_name
        asset_type_code = record.asset_type.asset_type_code
    else:
        info = ASSET_TYPE_MAP.get(record.asset_type_hex)
        if info:
            asset_type_code, asset_type_name = info[0], info[1]

    return AssetResponse(
        id=record.id,
        smms_asset_code=record.smms_asset_code,
        smms_asset_name=record.smms_asset_name,
        asset_number_code=record.asset_number_code,
        asset_number_id=record.asset_number_id,
        asset_type_hex=record.asset_type_hex,
        asset_type_name=asset_type_name,
        asset_type_code=asset_type_code,
        station_gateway_id=record.station_gateway_id,
        station_id=record.station_id,
        station_code=record.station.station_code if record.station else None,
        station_name=record.station.station_name if record.station else None,
        make=record.make,
        model=record.model,
        attr1=record.attr1,
        attr2=record.attr2,
        location=record.location,
        is_active=record.is_active,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


@router.get("", response_model=AssetListResponse)
def list_assets(
    station_id:     Optional[int]  = Query(None, description="Filter by station"),
    asset_type:     Optional[str]  = Query(None, description="Filter by asset type (ID or hex)"),
    is_active:      Optional[bool] = Query(None, description="Filter by active status"),
    search:         Optional[str]  = Query(
        None,
        description="Search by asset_number_code, smms_asset_code, or smms_asset_name"
    ),
    page:      int = Query(1,  ge=1),
    page_size: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
):
    """
    List all physical asset instances with optional filters and pagination.

    - `station_id` — filter to one station
    - `asset_type` — e.g. database ID, name, or hex (Point Machine, etc.)
    - `is_active` — `true` / `false`
    - `search` — partial match on asset_number_code, smms_asset_code, or smms_asset_name
    """
    asset_type_hex = _resolve_asset_types_to_hex(db, asset_type)
    q = db.query(Asset)

    if station_id is not None:
        q = q.filter(Asset.station_id == station_id)
    if asset_type_hex:
        hex_list = [h.strip().upper() for h in asset_type_hex.split(",") if h.strip()]
        if len(hex_list) == 1:
            q = q.filter(Asset.asset_type_hex == hex_list[0])
        elif len(hex_list) > 1:
            q = q.filter(Asset.asset_type_hex.in_(hex_list))
    if is_active is not None:
        q = q.filter(Asset.is_active == is_active)
    if search:
        term = f"%{search.strip()}%"
        q = q.filter(
            Asset.asset_number_code.ilike(term)
            | Asset.smms_asset_code.ilike(term)
            | Asset.smms_asset_name.ilike(term)
        )

    total = q.count()
    total_pages = (total + page_size - 1) // page_size if total else 0
    offset = (page - 1) * page_size
    records = (
        q.order_by(Asset.station_id, Asset.asset_type_hex, Asset.asset_number_id)
        .offset(offset)
        .limit(page_size)
        .all()
    )

    return AssetListResponse(
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
        rows=[_build_response(r) for r in records],
    )


@router.get("/{asset_id}", response_model=AssetResponse)
def get_asset(asset_id: int, db: Session = Depends(get_db)):
    """Retrieve a single physical asset by its internal ID."""
    record = db.query(Asset).filter(Asset.id == asset_id).first()
    if not record:
        raise HTTPException(status_code=404, detail=f"Asset {asset_id} not found")
    return _build_response(record)


@router.post("", response_model=AssetResponse, status_code=status.HTTP_201_CREATED)
def create_asset(payload: AssetCreate, db: Session = Depends(get_db)):
    """
    Register a new physical asset instance.

    - `smms_asset_code` must be globally unique (comes from SMMS).
    - `asset_number_id` (00–FF) is the byte used inside `para_id` for telemetry routing.
    - `station_gateway_id` is the 8-char hex `stngw_id` of the connected gateway.
    """
    # Validate asset type
    if payload.asset_type_hex.upper() not in ASSET_TYPE_MAP:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown asset_type_hex '{payload.asset_type_hex}'. See GET /assets/types."
        )

    # Validate station
    station = db.query(Station).filter(Station.id == payload.station_id).first()
    if not station:
        raise HTTPException(status_code=404, detail=f"Station {payload.station_id} not found")

    # Validate gateway
    gateway = db.query(Gateway).filter(
        Gateway.stngw_id == payload.station_gateway_id
    ).first()
    if not gateway:
        raise HTTPException(
            status_code=404,
            detail=f"Gateway with stngw_id '{payload.station_gateway_id}' not found"
        )

    record = Asset(
        smms_asset_code=payload.smms_asset_code.strip(),
        smms_asset_name=payload.smms_asset_name.strip(),
        asset_number_code=payload.asset_number_code.strip(),
        asset_number_id=payload.asset_number_id.upper(),
        asset_type_hex=payload.asset_type_hex.upper(),
        station_gateway_id=payload.station_gateway_id,
        station_id=payload.station_id,
        make=payload.make,
        model=payload.model,
        attr1=payload.attr1,
        attr2=payload.attr2,
        location=payload.location,
        is_active=payload.is_active,
    )
    db.add(record)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="smms_asset_code must be unique — an asset with this code already exists."
        )
    db.refresh(record)
    return _build_response(record)


@router.post("/bulk", response_model=List[AssetResponse], status_code=status.HTTP_201_CREATED)
def create_assets_bulk(payload: List[AssetCreate], db: Session = Depends(get_db)):
    """
    Register multiple physical asset instances in a single request.

    If any single asset validation fails or duplicate exists, the entire transaction is rolled back.
    """
    if not payload:
        raise HTTPException(status_code=400, detail="Asset list cannot be empty")

    # 1. Pre-validate internal list duplicate codes
    smms_codes = [a.smms_asset_code.strip() for a in payload]
    if len(smms_codes) != len(set(smms_codes)):
        raise HTTPException(status_code=400, detail="Duplicate smms_asset_code present in the request list")

    # 2. Bulk check database for existing smms_asset_codes
    existing_codes = {
        a[0] for a in db.query(Asset.smms_asset_code)
        .filter(Asset.smms_asset_code.in_(smms_codes)).all()
    }
    if existing_codes:
        raise HTTPException(
            status_code=409,
            detail=f"Some smms_asset_codes already exist in the database: {list(existing_codes)}"
        )

    # 3. Bulk fetch referenced stations and gateways to validate existence
    station_ids = {a.station_id for a in payload}
    existing_stations = {
        s[0] for s in db.query(Station.id)
        .filter(Station.id.in_(station_ids)).all()
    }
    missing_stations = station_ids - existing_stations
    if missing_stations:
        raise HTTPException(
            status_code=404,
            detail=f"Referenced stations not found: {list(missing_stations)}"
        )

    gateway_ids = {a.station_gateway_id for a in payload}
    existing_gateways = {
        g[0] for g in db.query(Gateway.stngw_id)
        .filter(Gateway.stngw_id.in_(gateway_ids)).all()
    }
    missing_gateways = gateway_ids - existing_gateways
    if missing_gateways:
        raise HTTPException(
            status_code=404,
            detail=f"Referenced gateways not found: {list(missing_gateways)}"
        )

    # 4. Insert assets
    created_assets = []
    for item in payload:
        # Validate asset type
        if item.asset_type_hex.upper() not in ASSET_TYPE_MAP:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown asset_type_hex '{item.asset_type_hex}' for asset '{item.smms_asset_code}'"
            )

        asset = Asset(
            smms_asset_code=item.smms_asset_code.strip(),
            smms_asset_name=item.smms_asset_name.strip(),
            asset_number_code=item.asset_number_code.strip(),
            asset_number_id=item.asset_number_id.upper(),
            asset_type_hex=item.asset_type_hex.upper(),
            station_gateway_id=item.station_gateway_id,
            station_id=item.station_id,
            make=item.make,
            model=item.model,
            attr1=item.attr1,
            attr2=item.attr2,
            location=item.location,
            is_active=item.is_active,
        )
        db.add(asset)
        created_assets.append(asset)

    try:
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Database error during bulk insert: {str(e)}")

    for asset in created_assets:
        db.refresh(asset)

    return [_build_response(a) for a in created_assets]


@router.put("/{asset_id}", response_model=AssetResponse)
def update_asset(
    asset_id: int,
    payload: AssetUpdate,
    db: Session = Depends(get_db),
):
    """Partially update an existing physical asset."""
    record = db.query(Asset).filter(Asset.id == asset_id).first()
    if not record:
        raise HTTPException(status_code=404, detail=f"Asset {asset_id} not found")

    data = payload.model_dump(exclude_unset=True)

    if "asset_type_hex" in data:
        data["asset_type_hex"] = data["asset_type_hex"].upper()
        if data["asset_type_hex"] not in ASSET_TYPE_MAP:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown asset_type_hex '{data['asset_type_hex']}'. See GET /assets/types."
            )
    if "asset_number_id" in data:
        data["asset_number_id"] = data["asset_number_id"].upper()
    if "asset_number_code" in data:
        data["asset_number_code"] = data["asset_number_code"].strip()
    if "smms_asset_code" in data and data["smms_asset_code"]:
        data["smms_asset_code"] = data["smms_asset_code"].strip()
    if "station_id" in data:
        stn = db.query(Station).filter(Station.id == data["station_id"]).first()
        if not stn:
            raise HTTPException(status_code=404, detail=f"Station {data['station_id']} not found")
    if "station_gateway_id" in data:
        gw = db.query(Gateway).filter(
            Gateway.stngw_id == data["station_gateway_id"]
        ).first()
        if not gw:
            raise HTTPException(
                status_code=404,
                detail=f"Gateway with stngw_id '{data['station_gateway_id']}' not found"
            )

    for field, value in data.items():
        setattr(record, field, value)

    try:
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="smms_asset_code must be unique — that code is already taken."
        )
    db.refresh(record)
    return _build_response(record)


@router.delete("/{asset_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_asset(asset_id: int, db: Session = Depends(get_db)):
    """Permanently delete a physical asset record."""
    record = db.query(Asset).filter(Asset.id == asset_id).first()
    if not record:
        raise HTTPException(status_code=404, detail=f"Asset {asset_id} not found")

    from app.models.models import AlertEvent, MaintenanceMode
    db.query(AlertEvent).filter(AlertEvent.asset_id == asset_id).update({"asset_id": None})
    db.query(MaintenanceMode).filter(MaintenanceMode.asset_id == asset_id).update({"asset_id": None})

    db.delete(record)
    db.commit()


# ── Asset Parameters (para_id → asset + prloc assignment) ────────────────────
#
# Backs the vendor's "Configure Slave" admin flow: gateway.py auto-creates an
# unassigned AssetParameter row the first time a para_id is seen in incoming
# telemetry. This screen lets an engineer link that para_id to a real Asset
# and record the prloc (location box) the sensor is physically wired into.
#
# prloc is intentionally stored per-para_id rather than on Asset.location,
# since RDSO Annexure-A/B allows one asset's different sensors to be
# terminated in different location boxes (e.g. current sensor in LB-01,
# voltage sensor in LB-02) — confirmed against the vendor's setup sheet.

def _build_asset_parameter_response(ap: AssetParameter) -> AssetParameterResponse:
    asset_type_hex = ap.para_id[0:2] if ap.para_id and len(ap.para_id) == 8 else None
    parameter_type_hex = ap.para_id[4:6] if ap.para_id and len(ap.para_id) == 8 else None
    param_info = PARAMETER_TYPE_MAP.get(parameter_type_hex) if parameter_type_hex else None

    asset = ap.asset
    return AssetParameterResponse(
        id=ap.id,
        para_id=ap.para_id,
        asset_id=ap.asset_id,
        asset_number_code=asset.asset_number_code if asset else None,
        asset_type_hex=asset_type_hex,
        parameter_type_hex=parameter_type_hex,
        parameter_name=param_info[1] if param_info else None,
        prloc=ap.prloc,
        is_assigned=ap.is_assigned,
        station_id=asset.station_id if asset else None,
        station_code=asset.station.station_code if asset and asset.station else None,
        created_at=ap.created_at,
        updated_at=ap.updated_at,
    )


@router.get("/parameters/configure", response_model=AssetParameterListResponse)
def list_asset_parameters(
    is_assigned: Optional[bool] = Query(None, description="Filter to only assigned or only unassigned rows"),
    station_id: Optional[int] = Query(None, description="Filter to parameters whose assigned asset belongs to this station"),
    search: Optional[str] = Query(None, description="Search by para_id or asset_number_code"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
):
    """
    List discovered para_id → asset/prloc mappings for the 'Configure Slave'
    admin screen. Rows are created automatically by gateway.py on first sight
    of a new para_id; use PUT /assets/parameters/configure/{id} to assign
    asset_id and prloc.
    """
    q = db.query(AssetParameter)
    if is_assigned is not None:
        q = q.filter(AssetParameter.is_assigned == is_assigned)
    if station_id is not None:
        q = q.join(Asset, Asset.id == AssetParameter.asset_id).filter(Asset.station_id == station_id)
    if search:
        term = f"%{search.strip()}%"
        q = q.outerjoin(Asset, Asset.id == AssetParameter.asset_id).filter(
            AssetParameter.para_id.ilike(term) | Asset.asset_number_code.ilike(term)
        )

    total = q.count()
    total_pages = (total + page_size - 1) // page_size if total else 0
    offset = (page - 1) * page_size
    rows = q.order_by(AssetParameter.created_at.desc()).offset(offset).limit(page_size).all()

    return AssetParameterListResponse(
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
        rows=[_build_asset_parameter_response(r) for r in rows],
    )


@router.get("/parameters/configure/{asset_parameter_id}", response_model=AssetParameterResponse)
def get_asset_parameter(asset_parameter_id: int, db: Session = Depends(get_db)):
    """Retrieve a single discovered para_id mapping by its internal ID."""
    ap = db.query(AssetParameter).filter(AssetParameter.id == asset_parameter_id).first()
    if not ap:
        raise HTTPException(status_code=404, detail=f"Asset parameter {asset_parameter_id} not found")
    return _build_asset_parameter_response(ap)


@router.put("/parameters/configure/{asset_parameter_id}", response_model=AssetParameterResponse)
def assign_asset_parameter(
    asset_parameter_id: int,
    payload: AssetParameterUpdate,
    db: Session = Depends(get_db),
):
    """
    Assign a discovered para_id to an asset and/or set its prloc.

    Matches the vendor's 'Configure Slave' flow: after wiring is confirmed,
    an engineer links the channel's para_id to the asset_number_code and
    records the location box (prloc) — e.g. {"asset_id": 5, "prloc": "LB-01"}.

    A row is considered fully assigned (is_assigned=True) once both asset_id
    and prloc are set. Either field can be set independently first if the
    engineer only has one piece of information at the time.
    """
    ap = db.query(AssetParameter).filter(AssetParameter.id == asset_parameter_id).first()
    if not ap:
        raise HTTPException(status_code=404, detail=f"Asset parameter {asset_parameter_id} not found")

    data = payload.model_dump(exclude_unset=True)

    if "asset_id" in data and data["asset_id"] is not None:
        asset = db.query(Asset).filter(Asset.id == data["asset_id"]).first()
        if not asset:
            raise HTTPException(status_code=404, detail=f"Asset {data['asset_id']} not found")

    for field, value in data.items():
        setattr(ap, field, value)

    ap.is_assigned = ap.asset_id is not None and bool(ap.prloc)

    db.commit()
    db.refresh(ap)
    return _build_asset_parameter_response(ap)


@router.delete("/parameters/configure/{asset_parameter_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_asset_parameter(asset_parameter_id: int, db: Session = Depends(get_db)):
    """
    Delete a discovered para_id mapping — e.g. to clean up a stale/incorrect
    auto-discovered row. Note: if telemetry for this para_id is still being
    ingested, gateway.py will simply re-create an unassigned row for it on
    the next packet.
    """
    ap = db.query(AssetParameter).filter(AssetParameter.id == asset_parameter_id).first()
    if not ap:
        raise HTTPException(status_code=404, detail=f"Asset parameter {asset_parameter_id} not found")
    db.delete(ap)
    db.commit()



