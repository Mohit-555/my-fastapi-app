from typing import Optional, List, Any
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.auth_utils import get_current_user
from app.models.models import User, Zone, Division, Station, Gateway, SlaveCard, Asset, AssetParameter
from app.models.schemas import (
    StandardResponse,
    ChannelAssignmentCreate,
    ChannelAssignmentUpdate,
    ChannelAssignmentResponse,
    ChannelAssignmentListResponse,
    AvailableChannelsResponse,
    AssetMappingAssignRequest,
    AssetMappingUnassignRequest,
    AssetMappingItemResponse,
)
from app.services.channel_assignment_service import ChannelAssignmentService, _get_or_create_asset_by_code

router = APIRouter(prefix="/channel-assignments", tags=["Channel Assignment"])


def _build_asset_mapping_item(ap: AssetParameter) -> AssetMappingItemResponse:
    asset = ap.asset
    sc = ap.slave_card
    gw = sc.gateway if sc else (asset.gateway if asset else None)

    asset_type_name = None
    if asset and asset.asset_type_hex:
        from app.constants import ASSET_TYPE_MAP
        info = ASSET_TYPE_MAP.get(asset.asset_type_hex)
        asset_type_name = info[1] if info else None

    return AssetMappingItemResponse(
        id=ap.id,
        para_id=ap.para_id,
        slave_card_id=ap.slave_card_id,
        channel_number=ap.channel_number,
        card_address=sc.card_address if sc else None,
        card_type=sc.card_type if sc else None,
        stngw_id=gw.stngw_id if gw else None,
        is_assigned=bool(ap.is_assigned and ap.asset_id),
        asset_id=ap.asset_id,
        asset_number_code=asset.asset_number_code if asset else None,
        asset_name=asset.smms_asset_name if asset else None,
        asset_type_name=asset_type_name,
        prloc=ap.prloc,
        updated_at=ap.updated_at,
    )


@router.post("/map-asset", response_model=StandardResponse[AssetMappingItemResponse])
def map_asset_parameter(
    payload: AssetMappingAssignRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Phase 2: Signalling Asset Mapping.
    Binds an 8-char hex para_id to an operational Asset and Location Box (prloc).
    Sets is_assigned = True to enable live alerts and operational tracking.
    """
    clean_pid = payload.para_id.strip().upper()
    asset = None
    if payload.asset_id:
        asset = db.query(Asset).filter(Asset.id == payload.asset_id).first()
        if not asset:
            raise HTTPException(status_code=404, detail=f"Asset with ID {payload.asset_id} not found.")
    elif payload.asset_number_code:
        gw = db.query(Gateway).first()
        if not gw:
            raise HTTPException(status_code=400, detail="No Gateway configured to associate asset with.")
        asset = _get_or_create_asset_by_code(db, gw, payload.asset_number_code)
    else:
        raise HTTPException(status_code=400, detail="Either asset_id or asset_number_code is required.")

    ap = db.query(AssetParameter).filter(AssetParameter.para_id == clean_pid).first()
    if not ap:
        ap = AssetParameter(
            para_id=clean_pid,
            asset_id=asset.id,
            prloc=payload.prloc.strip() if payload.prloc else None,
            is_assigned=True,
        )
        db.add(ap)
    else:
        ap.asset_id = asset.id
        ap.prloc = payload.prloc.strip() if payload.prloc else None
        ap.is_assigned = True

    db.commit()
    db.refresh(ap)
    return {
        "status": True,
        "message": f"Parameter '{clean_pid}' mapped to asset '{asset.asset_number_code}' successfully.",
        "data": _build_asset_mapping_item(ap),
    }


@router.post("/unmap-asset", response_model=StandardResponse[AssetMappingItemResponse])
def unmap_asset_parameter(
    payload: AssetMappingUnassignRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Phase 2: Signalling Asset Mapping.
    Unmaps a para_id from its asset and location box, setting is_assigned = False.
    Preserves hardware wiring on the channel without triggering false alerts.
    """
    clean_pid = payload.para_id.strip().upper()
    ap = db.query(AssetParameter).filter(AssetParameter.para_id == clean_pid).first()
    if not ap:
        raise HTTPException(status_code=404, detail=f"Parameter '{clean_pid}' not found.")

    ap.asset_id = None
    ap.prloc = None
    ap.is_assigned = False
    db.commit()
    db.refresh(ap)
    return {
        "status": True,
        "message": f"Parameter '{clean_pid}' unmapped successfully.",
        "data": _build_asset_mapping_item(ap),
    }


@router.get("/available-channels", response_model=StandardResponse[AvailableChannelsResponse])
def get_available_channels(
    slave_card_id: int = Query(..., description="Slave card ID"),
    exclude_assignment_id: Optional[int] = Query(None, description="Optional assignment ID to exclude from active check"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Return all channels (CH1..CHn) for a slave card with active assignment status.
    Registered BEFORE dynamic /{assignment_id} routes to prevent routing collisions.
    """
    data = ChannelAssignmentService.get_available_channels(
        db=db,
        slave_card_id=slave_card_id,
        user=current_user,
        exclude_assignment_id=exclude_assignment_id,
    )
    return {
        "status": True,
        "message": "Success",
        "data": data,
    }


@router.get("/filter-options", response_model=StandardResponse[Any])
def get_channel_filter_options(
    zone_id: Optional[int] = Query(None),
    division_id: Optional[int] = Query(None),
    station_id: Optional[int] = Query(None),
    gateway_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Return cascading filter options (zones, divisions, stations, gateways, cards)
    scoped to the user's role and selected parent filters.
    """
    # Zones query
    zq = db.query(Zone)
    if current_user.zone_id:
        zq = zq.filter(Zone.id == current_user.zone_id)
    zones = [{"id": z.id, "name": z.zone_name, "code": z.zone_code} for z in zq.all()]

    # Divisions query
    dq = db.query(Division)
    if current_user.division_id:
        dq = dq.filter(Division.id == current_user.division_id)
    elif zone_id:
        dq = dq.filter(Division.zone_id == zone_id)
    elif current_user.zone_id:
        dq = dq.filter(Division.zone_id == current_user.zone_id)
    divisions = [{"id": d.id, "name": d.division_name, "code": d.division_code, "zone_id": d.zone_id} for d in dq.all()]

    # Stations query
    sq = db.query(Station)
    if station_id:
        sq = sq.filter(Station.id == station_id)
    elif division_id:
        sq = sq.filter(Station.division_id == division_id)
    elif current_user.division_id:
        sq = sq.filter(Station.division_id == current_user.division_id)
    elif zone_id:
        div_ids = [d["id"] for d in divisions]
        sq = sq.filter(Station.division_id.in_(div_ids))
    stations = [{"id": s.id, "name": s.station_name, "code": s.station_code, "division_id": s.division_id} for s in sq.all()]

    # Gateways query
    gq = db.query(Gateway)
    if gateway_id:
        gq = gq.filter(Gateway.id == gateway_id)
    elif station_id:
        gq = gq.filter(Gateway.station_id == station_id)
    else:
        stn_ids = [s["id"] for s in stations]
        gq = gq.filter(Gateway.station_id.in_(stn_ids))
    gateways = [{"id": g.id, "stngw_id": g.stngw_id, "label": g.stngw_id, "station_id": g.station_id} for g in gq.all()]

    # Slave cards query
    scq = db.query(SlaveCard)
    if gateway_id:
        scq = scq.filter(SlaveCard.gateway_id == gateway_id)
    else:
        gw_ids = [g["id"] for g in gateways]
        scq = scq.filter(SlaveCard.gateway_id.in_(gw_ids))
    slave_cards = [
        {
            "id": sc.id,
            "gateway_id": sc.gateway_id,
            "card_address": sc.card_address,
            "card_type": sc.card_type,
            "label": f"Addr {sc.card_address} ({sc.card_type or 'Card'})",
        }
        for sc in scq.all()
    ]

    return {
        "status": True,
        "message": "Success",
        "data": {
            "zones": zones,
            "divisions": divisions,
            "stations": stations,
            "gateways": gateways,
            "slave_cards": slave_cards,
        },
    }


@router.get("/", response_model=StandardResponse[ChannelAssignmentListResponse])
def list_channel_assignments(
    zone_id: Optional[int] = Query(None, description="Filter by Zone ID"),
    division_id: Optional[int] = Query(None, description="Filter by Division ID"),
    station_id: Optional[int] = Query(None, description="Filter by Station ID"),
    gateway_id: Optional[int] = Query(None, description="Filter by Gateway ID"),
    stngw_id: Optional[str] = Query(None, description="Filter by Gateway stngw_id"),
    slave_card_id: Optional[int] = Query(None, description="Filter by Slave Card ID"),
    card_address: Optional[str] = Query(None, description="Filter by Card Address (hex)"),
    card_type: Optional[str] = Query(None, description="Filter by Card Type"),
    channel_number: Optional[str] = Query(None, description="Filter by Channel number (e.g. CH1)"),
    is_assigned: Optional[bool] = Query(None, description="Filter by assignment status"),
    search: Optional[str] = Query(None, description="Search across gateway, asset, para_id, location"),
    page: int = Query(1, ge=1, description="Page number (1-based)"),
    page_size: int = Query(50, ge=1, le=500, description="Page size"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List channel assignments with hierarchical filtering and pagination."""
    data = ChannelAssignmentService.list_assignments(
        db=db,
        user=current_user,
        zone_id=zone_id,
        division_id=division_id,
        station_id=station_id,
        gateway_id=gateway_id,
        stngw_id=stngw_id,
        slave_card_id=slave_card_id,
        card_address=card_address,
        card_type=card_type,
        channel_number=channel_number,
        is_assigned=is_assigned,
        search=search,
        page=page,
        page_size=page_size,
    )
    return {
        "status": True,
        "message": "Success",
        "data": data,
    }


@router.post("/", response_model=StandardResponse[ChannelAssignmentResponse], status_code=status.HTTP_201_CREATED)
def create_channel_assignment(
    payload: ChannelAssignmentCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Create a new channel assignment or reuse an existing unassigned channel row.
    Validates card, channel, asset, and prevents duplicate active assignments.
    """
    data = ChannelAssignmentService.create_assignment(
        db=db,
        payload=payload,
        user=current_user,
    )
    return {
        "status": True,
        "message": "Channel assignment created successfully",
        "data": data,
    }


@router.get("/{assignment_id}", response_model=StandardResponse[ChannelAssignmentResponse])
def get_channel_assignment(
    assignment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Retrieve full details of a specific channel assignment."""
    data = ChannelAssignmentService.get_assignment(
        db=db,
        assignment_id=assignment_id,
        user=current_user,
    )
    return {
        "status": True,
        "message": "Success",
        "data": data,
    }


@router.put("/{assignment_id}", response_model=StandardResponse[ChannelAssignmentResponse])
def update_channel_assignment(
    assignment_id: int,
    payload: ChannelAssignmentUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update an existing channel assignment (asset mapping, location box, etc.)."""
    data = ChannelAssignmentService.update_assignment(
        db=db,
        assignment_id=assignment_id,
        payload=payload,
        user=current_user,
    )
    return {
        "status": True,
        "message": "Channel assignment updated successfully",
        "data": data,
    }


@router.delete("/{assignment_id}", status_code=status.HTTP_200_OK)
def delete_channel_assignment(
    assignment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Unassign an assignment, setting asset_id and location to null so the channel
    becomes available again for assignment.
    """
    ChannelAssignmentService.delete_assignment(
        db=db,
        assignment_id=assignment_id,
        user=current_user,
    )
    return {
        "status": True,
        "message": "Channel assignment removed successfully",
        "data": {"id": assignment_id, "is_assigned": False},
    }
