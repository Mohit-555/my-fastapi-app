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
from app.models.models import AssetInventory, Division, Threshold, Station, Zone, AssetTypeMaster
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
)
from app.constants import (
    ASSET_TYPE_MAP,
    ASSET_TYPE_DISPLAY_GROUPS,
    PARAMETER_TYPE_MAP,
    PARAMETER_REPR_MAP,
)

router = APIRouter(prefix="/assets", tags=["Assets & Thresholds"])


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
    asset_type_hex: Optional[str] = Query(
        None,
        description="Filter by asset_type_hex to get only relevant parameters"
    )
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
        q = q.filter(AssetInventory.asset_type_hex == asset_type_hex.upper())
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
    asset_type_hex: Optional[str] = Query(None),
    asset_make: Optional[str] = Query(None),
    view: str = Query("table", description="Frontend view mode. Currently supports table data."),
    db: Session = Depends(get_db),
):
    """
    Return Asset Detail report rows for the frontend table.

    Filters map to the UI controls: Zone, Division, Station, Asset Type,
    View, and Asset Make.
    """
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
    asset_type_hex: Optional[str] = Query(None),
    asset_make: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """Download the Asset Detail report as CSV."""
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
    asset_type_hex: Optional[str] = Query(None),
    station_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
):
    """Return distinct asset makes for the Asset Make dropdown."""
    q = db.query(AssetInventory.asset_make).distinct()
    if asset_type_hex:
        q = q.filter(AssetInventory.asset_type_hex == asset_type_hex.upper())
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

    db_types_map = {t.asset_type_id: t for t in db.query(AssetTypeMaster).all()}

    # Grouped asset types
    asset_groups = []
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
        asset_groups.append(AssetTypeGroupOption(
            id=group_id,
            group_label=group_label,
            asset_type_hexes=hexes,
            members=members,
        ))
        group_id += 1

    return AssetFiltersResponse(
        zones=[DropdownOption(id=z.id, label=z.zone_name, code=z.zone_code, hex_id=z.zone_id_hex) for z in zones],
        divisions=[DropdownOption(id=d.id, label=d.division_name, code=d.division_code, hex_id=d.division_id_hex) for d in divisions],
        stations=[DropdownOption(id=s.id, label=s.station_name, code=s.station_code, hex_id=s.station_id_hex) for s in stations],
        asset_types=asset_groups,
        asset_makes=asset_makes_list,
    )


@router.get("/inventory", response_model=List[AssetInventoryResponse])
def list_asset_inventory(
    station_id: Optional[int] = Query(None),
    asset_type_hex: Optional[str] = Query(None),
    asset_make: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """List raw asset inventory records used by the Asset Detail report."""
    q = db.query(AssetInventory)
    if station_id is not None:
        q = q.filter(AssetInventory.station_id == station_id)
    if asset_type_hex:
        q = q.filter(AssetInventory.asset_type_hex == asset_type_hex.upper())
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
    asset_type_hex: Optional[str] = Query(None),
    station_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
):
    """
    List thresholds. Filter by asset_type_hex and/or station_id.
    Results with station_id=NULL are global defaults.
    """
    q = db.query(Threshold)
    if asset_type_hex:
        q = q.filter(Threshold.asset_type_hex == asset_type_hex.upper())
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
