"""
Asset Instances router — CRUD for individual physical asset records.
Each row = one physical asset at a station (e.g. PT-101, TC-05).

Spec reference: RDSO/SPN/257/2025, Annexure A, Page 40 (points f, g, h, i).
"""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.constants import ASSET_TYPE_MAP
from app.database import get_db
from app.models.models import Asset, Gateway, Station, AssetTypeMaster
from app.models.schemas import (
    AssetCreate,
    AssetListResponse,
    AssetResponse,
    AssetUpdate,
)

router = APIRouter(prefix="/asset-instances", tags=["Asset Instances"])


# ── Helper ────────────────────────────────────────────────────────────────────

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


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("", response_model=AssetListResponse)
def list_assets(
    station_id:     Optional[int]  = Query(None, description="Filter by station"),
    asset_type_hex: Optional[str]  = Query(None, description="Filter by asset type hex (e.g. 00)"),
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
    - `asset_type_hex` — e.g. `00` (Point Machine), `20` (DC Track Circuit)
    - `is_active` — `true` / `false`
    - `search` — partial match on asset_number_code, smms_asset_code, or smms_asset_name
    """
    q = db.query(Asset)

    if station_id is not None:
        q = q.filter(Asset.station_id == station_id)
    if asset_type_hex:
        q = q.filter(Asset.asset_type_hex == asset_type_hex.upper())
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
    db.delete(record)
    db.commit()
