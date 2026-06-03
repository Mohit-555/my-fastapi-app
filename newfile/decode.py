from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.models import Zone, Division, Station
from app.models.schemas import GatewayDecodeResponse, ParaDecodeResponse
from app.constants import ASSET_TYPE_MAP, PARAMETER_TYPE_MAP, PARAMETER_REPR_MAP

router = APIRouter(prefix="/decode", tags=["Decode IDs"])


def _validate_hex_length(value: str, expected_len: int, label: str):
    """Ensure hex string is correct length and valid hex"""
    if len(value) != expected_len:
        raise HTTPException(
            status_code=400,
            detail=f"{label} must be exactly {expected_len} hex characters. Got '{value}' ({len(value)} chars)."
        )
    try:
        int(value, 16)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"{label} '{value}' is not valid hexadecimal."
        )


@router.get("/stngw/{stngw_id}", response_model=GatewayDecodeResponse)
def decode_gateway_id(stngw_id: str, db: Session = Depends(get_db)):
    """
    Decode an 8-character hex stngw_id into zone, division, station, and gateway number.

    Example: 05011200
      → zone_id_hex      = 05  → North Eastern Railway (NER)
      → division_id_hex  = 01  → Lucknow (LJN)
      → station_id_hex   = 12  → Lucknow Station
      → gateway_number   = 00  → Gateway #0
    """
    stngw_id = stngw_id.upper().strip()
    _validate_hex_length(stngw_id, 8, "stngw_id")

    zone_hex     = stngw_id[0:2]
    div_hex      = stngw_id[2:4]
    station_hex  = stngw_id[4:6]
    gw_num_hex   = stngw_id[6:8]

    # Lookup zone
    zone = db.query(Zone).filter(Zone.zone_id_hex == zone_hex).first()

    # Lookup division (within zone if found)
    division = None
    if zone:
        division = db.query(Division).filter(
            Division.zone_id == zone.id,
            Division.division_id_hex == div_hex
        ).first()

    # Lookup station (within division if found)
    station = None
    if division:
        station = db.query(Station).filter(
            Station.division_id == division.id,
            Station.station_id_hex == station_hex
        ).first()

    return GatewayDecodeResponse(
        stngw_id=stngw_id,
        zone_id_hex=zone_hex,
        division_id_hex=div_hex,
        station_id_hex=station_hex,
        gateway_number_hex=gw_num_hex,
        zone_name=zone.zone_name if zone else None,
        zone_code=zone.zone_code if zone else None,
        division_name=division.division_name if division else None,
        division_code=division.division_code if division else None,
        station_name=station.station_name if station else None,
        station_code=station.station_code if station else None,
    )


@router.get("/para/{para_id}", response_model=ParaDecodeResponse)
def decode_para_id(para_id: str):
    """
    Decode an 8-character hex para_id into asset type, asset number,
    parameter type, representation — and resolve human-readable names
    for all four fields.

    Example: 50010A02
      → asset_type_id_hex             = 50  → IPS (Integrated Power Supply)
      → asset_number_id_hex           = 01  → Asset #1
      → parameter_type_id_hex         = 0A  → Track Circuit Voltage
      → parameter_representation_hex  = 02  → Maximum
    """
    para_id = para_id.upper().strip()
    _validate_hex_length(para_id, 8, "para_id")

    asset_type_hex  = para_id[0:2]
    asset_num_hex   = para_id[2:4]
    param_type_hex  = para_id[4:6]
    param_repr_hex  = para_id[6:8]

    asset_info  = ASSET_TYPE_MAP.get(asset_type_hex)
    param_info  = PARAMETER_TYPE_MAP.get(param_type_hex)
    repr_info   = PARAMETER_REPR_MAP.get(param_repr_hex)

    return ParaDecodeResponse(
        para_id=para_id,
        asset_type_id_hex=asset_type_hex,
        asset_number_id_hex=asset_num_hex,
        parameter_type_id_hex=param_type_hex,
        parameter_representation_id_hex=param_repr_hex,
        asset_type_name=asset_info[1] if asset_info else None,
        asset_type_code=asset_info[0] if asset_info else None,
        parameter_name=param_info[1] if param_info else None,
        parameter_unit=param_info[2] if param_info else None,
        representation=repr_info[1] if repr_info else None,
    )


@router.get("/full/{stngw_id}/{para_id}")
def decode_full(stngw_id: str, para_id: str, db: Session = Depends(get_db)):
    """
    Decode both stngw_id and para_id together — returns complete context
    for any data packet.

    Example: /decode/full/05011200/50010A02
    """
    gateway_info = decode_gateway_id(stngw_id, db)
    para_info = decode_para_id(para_id)

    return {
        "gateway": gateway_info,
        "parameter": para_info,
    }
