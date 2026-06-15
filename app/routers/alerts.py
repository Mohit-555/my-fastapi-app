import csv
import io
from datetime import date, datetime, time
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import case, func
from sqlalchemy.orm import Session

from app.constants import ASSET_TYPE_DISPLAY_GROUPS, ASSET_TYPE_MAP
from app.database import get_db
from app.models.models import AlertEvent, Asset, Division, Station, Zone, AssetTypeMaster, AlertCauseMaster
from app.models.schemas import (
    AlertEventCreate,
    AlertEventResponse,
    AlertEventsResponse,
    AlertEventUpdate,
    AlertFeedbackUpdate,
    AlertFilterOption,
    AlertFiltersResponse,
    AlertHistoryResponse,
    AlertHistoryRow,
    AlertLiveCard,
    AlertLiveResponse,
    AlertLiveSummary,
    AlertRectificationUpdate,
    AlertRemarkUpdate,
    AlertSummaryResponse,
    AlertSummaryRow,
    AssetTypeGroupOption,
    AssetTypeOption,
    DropdownOption,
)

router = APIRouter(prefix="/alerts", tags=["Alerts"])

ALERT_TYPE_OPTIONS = ["ALL", "PREDICTIVE", "FAILURE"]
FEEDBACK_OPTIONS = ["ALL", "T", "PT", "F", "M"]
CAUSE_OPTIONS = ["ALL", "PT-OBS", "TC-SHUNT", "BAT-LOW", "COMM-FAIL", "TEMP-HIGH", "MOTOR-OC"]
ALERT_TYPE_ALIASES = {
    "PREDICTIVE": "Predictive",
    "FAILURE": "Failure",
    "FAILUR": "Failure",
}


def _blank_to_none(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    value = value.strip()
    if not value or value.upper() == "ALL":
        return None
    return value


def _normalize_alert_type(value: Optional[str]) -> Optional[str]:
    value = _blank_to_none(value)
    if not value:
        return None
    return ALERT_TYPE_ALIASES.get(value.upper(), value)


def _combine_datetime(day: Optional[date], clock: Optional[time], is_end: bool) -> Optional[datetime]:
    if day is None and clock is None:
        return None
    if day is None:
        day = date.today()
    if clock is None:
        clock = time.max if is_end else time.min
    return datetime.combine(day, clock)


def _asset_type_name(asset_type_hex: str) -> str:
    asset_info = ASSET_TYPE_MAP.get(asset_type_hex)
    return asset_info[1] if asset_info else asset_type_hex


def _asset_group_hexes(asset_type: Optional[str]) -> Optional[List[str]]:
    asset_type = _blank_to_none(asset_type)
    if not asset_type:
        return None
    if asset_type.upper() in ASSET_TYPE_MAP:
        return [asset_type.upper()]
    return ASSET_TYPE_DISPLAY_GROUPS.get(asset_type)


def _page_meta(total_rows: int, page: int, page_size: int) -> tuple[int, int]:
    total_pages = (total_rows + page_size - 1) // page_size if total_rows else 0
    offset = (page - 1) * page_size
    return total_pages, offset


def _validate_event_payload(payload: AlertEventCreate | AlertEventUpdate, db: Session) -> None:
    if getattr(payload, "station_id", None) is not None:
        station = db.query(Station).filter(Station.id == payload.station_id).first()
        if not station:
            raise HTTPException(status_code=404, detail=f"Station {payload.station_id} not found")

    asset_type_hex = getattr(payload, "asset_type_hex", None)
    if asset_type_hex and asset_type_hex.upper() not in ASSET_TYPE_MAP:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown asset_type_hex '{asset_type_hex}'. See GET /assets/types.",
        )

    feedback = getattr(payload, "feedback", None)
    if feedback and feedback.upper() not in {"T", "PT", "F", "M"}:
        raise HTTPException(status_code=400, detail="feedback must be one of T, PT, F, M")


def _base_summary_query(
    db: Session,
    zone_id: Optional[int],
    division_id: Optional[int],
    station_id: Optional[int],
    zone: Optional[str],
    division: Optional[str],
    station: Optional[str],
    alert_type: Optional[str],
    asset_type_hex: Optional[str],
    asset_type: Optional[str],
    asset_no: Optional[str],
    cause: Optional[str],
    from_date: Optional[date],
    from_time: Optional[time],
    to_date: Optional[date],
    to_time: Optional[time],
):
    q = (
        db.query(
            Zone.id.label("zone_id"),
            Zone.zone_code.label("zone"),
            Division.id.label("division_id"),
            Division.division_code.label("division"),
            Station.id.label("station_id"),
            Station.station_code.label("station"),
            AlertEvent.alert_type.label("alert_type"),
            AlertEvent.asset_type_hex.label("asset_type_hex"),
            AlertEvent.asset_no.label("asset_no"),
            AlertEvent.cause.label("cause"),
            func.count(AlertEvent.id).label("total"),
            func.sum(case((func.upper(AlertEvent.feedback) == "T", 1), else_=0)).label("true_count"),
            func.sum(case((func.upper(AlertEvent.feedback) == "PT", 1), else_=0)).label("partial_count"),
        )
        .join(Station, Station.id == AlertEvent.station_id)
        .join(Division, Division.id == Station.division_id)
        .join(Zone, Zone.id == Division.zone_id)
    )

    zone = _blank_to_none(zone)
    division = _blank_to_none(division)
    station = _blank_to_none(station)
    alert_type = _normalize_alert_type(alert_type)
    asset_type_hex = _blank_to_none(asset_type_hex)
    asset_no = _blank_to_none(asset_no)
    cause = _blank_to_none(cause)

    if zone_id is not None:
        q = q.filter(Zone.id == zone_id)
    if division_id is not None:
        q = q.filter(Division.id == division_id)
    if station_id is not None:
        q = q.filter(Station.id == station_id)
    if zone:
        q = q.filter(func.upper(Zone.zone_code) == zone.upper())
    if division:
        q = q.filter(func.upper(Division.division_code) == division.upper())
    if station:
        q = q.filter(func.upper(Station.station_code) == station.upper())
    if alert_type:
        q = q.filter(func.lower(AlertEvent.alert_type) == alert_type.lower())

    asset_hexes = _asset_group_hexes(asset_type)
    if asset_type_hex:
        asset_hexes = [h.strip().upper() for h in asset_type_hex.split(",") if h.strip()]
    if asset_hexes:
        q = q.filter(AlertEvent.asset_type_hex.in_(asset_hexes))

    if asset_no:
        q = q.filter(func.lower(AlertEvent.asset_no).like(f"%{asset_no.lower()}%"))
    if cause:
        q = q.filter(func.lower(AlertEvent.cause) == cause.lower())

    start_dt = _combine_datetime(from_date, from_time, is_end=False)
    end_dt = _combine_datetime(to_date, to_time, is_end=True)
    if start_dt:
        q = q.filter(AlertEvent.alert_time >= start_dt)
    if end_dt:
        q = q.filter(AlertEvent.alert_time <= end_dt)

    return (
        q.group_by(
            Zone.id,
            Zone.zone_code,
            Division.id,
            Division.division_code,
            Station.id,
            Station.station_code,
            AlertEvent.alert_type,
            AlertEvent.asset_type_hex,
            AlertEvent.asset_no,
            AlertEvent.cause,
        )
        .order_by(
            Zone.zone_code,
            Division.division_code,
            Station.station_code,
            AlertEvent.alert_type,
            AlertEvent.asset_type_hex,
            AlertEvent.asset_no,
            AlertEvent.cause,
        )
    )


def _summary_rows(raw_rows, start: int = 1) -> List[AlertSummaryRow]:
    rows: List[AlertSummaryRow] = []
    for idx, row in enumerate(raw_rows, start=start):
        total = int(row.total or 0)
        true_count = int(row.true_count or 0)
        partial_count = int(row.partial_count or 0)
        percentage = round(((true_count + partial_count) / total) * 100, 1) if total else 0.0
        rows.append(AlertSummaryRow(
            sr=idx,
            zone_id=row.zone_id,
            zone=row.zone,
            division_id=row.division_id,
            division=row.division,
            station_id=row.station_id,
            station=row.station,
            alert_type=row.alert_type,
            asset_type_hex=row.asset_type_hex,
            asset_type=_asset_type_name(row.asset_type_hex),
            asset_no=row.asset_no,
            cause=row.cause,
            total=total,
            true=true_count,
            partially_true=partial_count,
            percentage=percentage,
        ))
    return rows


def _base_history_query(
    db: Session,
    zone_id: Optional[int],
    division_id: Optional[int],
    station_id: Optional[int],
    zone: Optional[str],
    division: Optional[str],
    station: Optional[str],
    alert_type: Optional[str],
    asset_type_hex: Optional[str],
    asset_type: Optional[str],
    asset_no: Optional[str],
    cause: Optional[str],
    feedback: Optional[str],
    alert_status: Optional[str],
    from_date: Optional[date],
    from_time: Optional[time],
    to_date: Optional[date],
    to_time: Optional[time],
):
    q = (
        db.query(
            AlertEvent.id.label("id"),
            Zone.id.label("zone_id"),
            Zone.zone_code.label("zone"),
            Division.id.label("division_id"),
            Division.division_code.label("division"),
            Station.id.label("station_id"),
            Station.station_code.label("station"),
            AlertEvent.alert_type.label("alert_type"),
            AlertEvent.asset_type_hex.label("asset_type_hex"),
            AlertEvent.asset_no.label("asset_no"),
            AlertEvent.alert_status.label("alert_status"),
            AlertEvent.cause.label("cause"),
            AlertEvent.feedback.label("feedback"),
            AlertEvent.alert_time.label("alert_time"),
            AlertEvent.rectification_time.label("rectification_time"),
            AlertEvent.feedback_time.label("feedback_time"),
            AlertEvent.maintainer_name.label("maintainer_name"),
            AlertEvent.designation.label("designation"),
            AlertEvent.mobile.label("mobile"),
            AlertEvent.remark.label("remark"),
        )
        .join(Station, Station.id == AlertEvent.station_id)
        .join(Division, Division.id == Station.division_id)
        .join(Zone, Zone.id == Division.zone_id)
    )

    zone = _blank_to_none(zone)
    division = _blank_to_none(division)
    station = _blank_to_none(station)
    alert_type = _normalize_alert_type(alert_type)
    asset_type_hex = _blank_to_none(asset_type_hex)
    asset_no = _blank_to_none(asset_no)
    cause = _blank_to_none(cause)
    feedback = _blank_to_none(feedback)
    alert_status = _blank_to_none(alert_status)

    if zone_id is not None:
        q = q.filter(Zone.id == zone_id)
    if division_id is not None:
        q = q.filter(Division.id == division_id)
    if station_id is not None:
        q = q.filter(Station.id == station_id)
    if zone:
        q = q.filter(func.upper(Zone.zone_code) == zone.upper())
    if division:
        q = q.filter(func.upper(Division.division_code) == division.upper())
    if station:
        q = q.filter(func.upper(Station.station_code) == station.upper())
    if alert_type:
        q = q.filter(func.lower(AlertEvent.alert_type) == alert_type.lower())

    asset_hexes = _asset_group_hexes(asset_type)
    if asset_type_hex:
        asset_hexes = [h.strip().upper() for h in asset_type_hex.split(",") if h.strip()]
    if asset_hexes:
        q = q.filter(AlertEvent.asset_type_hex.in_(asset_hexes))

    if asset_no:
        q = q.filter(func.lower(AlertEvent.asset_no).like(f"%{asset_no.lower()}%"))
    if cause:
        q = q.filter(func.lower(AlertEvent.cause) == cause.lower())
    if feedback:
        q = q.filter(func.upper(AlertEvent.feedback) == feedback.upper())
    if alert_status:
        q = q.filter(func.lower(AlertEvent.alert_status) == alert_status.lower())

    start_dt = _combine_datetime(from_date, from_time, is_end=False)
    end_dt = _combine_datetime(to_date, to_time, is_end=True)
    if start_dt:
        q = q.filter(AlertEvent.alert_time >= start_dt)
    if end_dt:
        q = q.filter(AlertEvent.alert_time <= end_dt)

    return q.order_by(AlertEvent.alert_time.desc(), AlertEvent.id.desc())


def _history_rows(raw_rows, start: int = 1) -> List[AlertHistoryRow]:
    rows: List[AlertHistoryRow] = []
    for idx, row in enumerate(raw_rows, start=start):
        duration_min = None
        if row.rectification_time and row.alert_time:
            duration_min = round((row.rectification_time - row.alert_time).total_seconds() / 60, 2)

        rows.append(AlertHistoryRow(
            sr=idx,
            id=row.id,
            zone_id=row.zone_id,
            zone=row.zone,
            division_id=row.division_id,
            division=row.division,
            station_id=row.station_id,
            station=row.station,
            alert_type=row.alert_type,
            asset_type_hex=row.asset_type_hex,
            asset_type=_asset_type_name(row.asset_type_hex),
            asset_no=row.asset_no,
            alert_status=row.alert_status,
            cause=row.cause,
            feedback=row.feedback,
            incidence_date_time=row.alert_time.isoformat(),
            rectification_date_time=row.rectification_time.isoformat() if row.rectification_time else None,
            duration_min=duration_min,
            feedback_date_time=row.feedback_time.isoformat() if row.feedback_time else None,
            maintainer_name=row.maintainer_name,
            designation=row.designation,
            mobile=row.mobile,
            remarks=row.remark,
        ))
    return rows


def _base_live_query(
    db: Session,
    zone_id: Optional[int],
    division_id: Optional[int],
    station_id: Optional[int],
    zone: Optional[str],
    division: Optional[str],
    station: Optional[str],
    alert_type: Optional[str],
    asset_type_hex: Optional[str],
    asset_type: Optional[str],
):
    q = (
        db.query(
            AlertEvent.id.label("id"),
            Zone.id.label("zone_id"),
            Zone.zone_code.label("zone"),
            Division.id.label("division_id"),
            Division.division_code.label("division"),
            Station.id.label("station_id"),
            Station.station_code.label("station"),
            AlertEvent.alert_type.label("alert_type"),
            AlertEvent.asset_type_hex.label("asset_type_hex"),
            AlertEvent.asset_no.label("asset_no"),
            AlertEvent.alert_status.label("alert_status"),
            AlertEvent.cause.label("cause"),
            AlertEvent.feedback.label("feedback"),
            AlertEvent.acknowledged.label("acknowledged"),
            AlertEvent.alert_time.label("alert_time"),
            AlertEvent.remark.label("remark"),
        )
        .join(Station, Station.id == AlertEvent.station_id)
        .join(Division, Division.id == Station.division_id)
        .join(Zone, Zone.id == Division.zone_id)
        .filter(AlertEvent.rectification_time.is_(None))
        .filter(func.lower(AlertEvent.alert_status) != "cleared")
    )

    zone = _blank_to_none(zone)
    division = _blank_to_none(division)
    station = _blank_to_none(station)
    alert_type = _normalize_alert_type(alert_type)
    asset_type_hex = _blank_to_none(asset_type_hex)

    if zone_id is not None:
        q = q.filter(Zone.id == zone_id)
    if division_id is not None:
        q = q.filter(Division.id == division_id)
    if station_id is not None:
        q = q.filter(Station.id == station_id)
    if zone:
        q = q.filter(func.upper(Zone.zone_code) == zone.upper())
    if division:
        q = q.filter(func.upper(Division.division_code) == division.upper())
    if station:
        q = q.filter(func.upper(Station.station_code) == station.upper())
    if alert_type:
        q = q.filter(func.lower(AlertEvent.alert_type) == alert_type.lower())

    asset_hexes = _asset_group_hexes(asset_type)
    if asset_type_hex:
        asset_hexes = [h.strip().upper() for h in asset_type_hex.split(",") if h.strip()]
    if asset_hexes:
        q = q.filter(AlertEvent.asset_type_hex.in_(asset_hexes))

    return q.order_by(AlertEvent.alert_time.desc(), AlertEvent.id.desc())


def _live_cards(raw_rows) -> List[AlertLiveCard]:
    cards: List[AlertLiveCard] = []
    for row in raw_rows:
        asset_type = _asset_type_name(row.asset_type_hex)
        cards.append(AlertLiveCard(
            id=row.id,
            zone_id=row.zone_id,
            zone=row.zone,
            division_id=row.division_id,
            division=row.division,
            station_id=row.station_id,
            station=row.station,
            title=f"{row.station} {row.asset_no}",
            alert_type=row.alert_type,
            asset_type_hex=row.asset_type_hex,
            asset_type=asset_type,
            asset_no=row.asset_no,
            alert_status=row.alert_status,
            cause=row.cause,
            feedback=row.feedback,
            acknowledged=bool(row.acknowledged),
            incidence_date_time=row.alert_time.isoformat(),
            remarks=row.remark,
        ))
    return cards


@router.get("/types", response_model=List[AlertFilterOption])
def list_alert_types():
    """
    Return a list of alert types for dropdown filters.
    """
    return [
        AlertFilterOption(id=1, label="All", value="ALL"),
        AlertFilterOption(id=2, label="Predictive", value="Predictive"),
        AlertFilterOption(id=3, label="Failure", value="Failure"),
    ]


@router.get("/asset-numbers", response_model=List[AlertFilterOption])
def list_alert_asset_numbers(
    zone_id: Optional[int] = Query(None),
    division_id: Optional[int] = Query(None),
    station_id: Optional[int] = Query(None),
    asset_type_hex: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """
    Return a list of unique asset numbers for dropdown filters.

    Primary source: Asset (all registered physical assets).
    Fallback: AlertEvent.asset_no for any unregistered asset numbers
    that appear in historical alerts.
    """
    hex_list: Optional[List[str]] = None
    if asset_type_hex:
        hex_list = [h.strip().upper() for h in asset_type_hex.split(",") if h.strip()]

    # ── 1. Query Asset (registered assets) ───────────────────────────────
    master_q = db.query(Asset.asset_number_code).filter(Asset.is_active == True)

    if station_id is not None:
        master_q = master_q.filter(Asset.station_id == station_id)
    elif division_id is not None:
        master_q = master_q.join(Station, Station.id == Asset.station_id)\
                           .filter(Station.division_id == division_id)
    elif zone_id is not None:
        master_q = master_q.join(Station, Station.id == Asset.station_id)\
                           .join(Division, Division.id == Station.division_id)\
                           .filter(Division.zone_id == zone_id)

    if hex_list:
        master_q = master_q.filter(Asset.asset_type_hex.in_(hex_list))

    registered = {
        row.asset_number_code
        for row in master_q.distinct().all()
        if row.asset_number_code
    }

    # ── 2. Fallback: AlertEvent for any unregistered numbers ──────────────────
    event_q = db.query(AlertEvent.asset_no).distinct()

    if station_id is not None:
        event_q = event_q.filter(AlertEvent.station_id == station_id)
    elif division_id is not None:
        event_q = event_q.join(Station, Station.id == AlertEvent.station_id)\
                         .filter(Station.division_id == division_id)
    elif zone_id is not None:
        event_q = event_q.join(Station, Station.id == AlertEvent.station_id)\
                         .join(Division, Division.id == Station.division_id)\
                         .filter(Division.zone_id == zone_id)

    if hex_list:
        event_q = event_q.filter(AlertEvent.asset_type_hex.in_(hex_list))

    for row in event_q.all():
        if row.asset_no:
            registered.add(row.asset_no)

    # ── 3. Build sorted response ─────────────────────────────────────────
    return [
        AlertFilterOption(id=idx, label=code, value=code)
        for idx, code in enumerate(sorted(registered), start=1)
    ]


@router.get("/causes", response_model=List[AlertFilterOption])
def list_alert_causes(
    zone_id: Optional[int] = Query(None),
    division_id: Optional[int] = Query(None),
    station_id: Optional[int] = Query(None),
    asset_type_hex: Optional[str] = Query(None),
    asset_no: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """
    Return a list of unique causes filtered by zone, division, station, asset type, and asset number.
    """
    q_master = db.query(AlertCauseMaster)
    hex_list = []
    if asset_type_hex:
        hex_list = [h.strip().upper() for h in asset_type_hex.split(",") if h.strip()]
        if hex_list:
            q_master = q_master.filter(AlertCauseMaster.asset_type_id.in_(hex_list))

    master_causes = q_master.order_by(AlertCauseMaster.cause_code).all()
    master_codes = {c.cause_code.upper() for c in master_causes}

    q_events = db.query(AlertEvent.cause).distinct()
    if station_id is not None:
        q_events = q_events.filter(AlertEvent.station_id == station_id)
    elif division_id is not None:
        q_events = q_events.join(Station, Station.id == AlertEvent.station_id).filter(Station.division_id == division_id)
    elif zone_id is not None:
        q_events = q_events.join(Station, Station.id == AlertEvent.station_id)\
             .join(Division, Division.id == Station.division_id)\
             .filter(Division.zone_id == zone_id)

    if asset_type_hex and hex_list:
        q_events = q_events.filter(AlertEvent.asset_type_hex.in_(hex_list))

    if asset_no:
        q_events = q_events.filter(AlertEvent.asset_no == asset_no)

    event_causes = [row.cause for row in q_events.order_by(AlertEvent.cause).all() if row.cause]

    result_causes = []
    for c in master_causes:
        result_causes.append((c.cause_code, c.cause_detail))

    for code in event_causes:
        if code.upper() not in master_codes:
            result_causes.append((code, code))
            master_codes.add(code.upper())

    return [
        AlertFilterOption(id=idx, label=detail, value=code)
        for idx, (code, detail) in enumerate(result_causes, start=1)
    ]


@router.get("/live", response_model=AlertLiveResponse)
def get_alert_live(
    zone_id: Optional[int] = Query(None),
    division_id: Optional[int] = Query(None),
    station_id: Optional[int] = Query(None),
    alert_type: Optional[str] = Query(None),
    asset_type_hex: Optional[str] = Query(None),
    asset_type: Optional[str] = Query(None),
    limit: int = Query(100, le=1000),
    db: Session = Depends(get_db),
):
    """Return unresolved live alert cards and live counters."""
    raw_rows = _base_live_query(
        db, zone_id, division_id, station_id, None, None, None,
        alert_type, asset_type_hex, asset_type,
    ).limit(limit).all()
    alerts = _live_cards(raw_rows)
    predictive = sum(1 for row in alerts if row.alert_type.lower() == "predictive")
    failure = sum(1 for row in alerts if row.alert_type.lower() == "failure")
    return AlertLiveResponse(
        summary=AlertLiveSummary(
            predictive=predictive,
            failure=failure,
            total=len(alerts),
        ),
        alerts=alerts,
    )


@router.get("/summary", response_model=AlertSummaryResponse)
def get_alert_summary(
    zone_id: Optional[int] = Query(None),
    division_id: Optional[int] = Query(None),
    station_id: Optional[int] = Query(None),
    alert_type: Optional[str] = Query(None),
    asset_type_hex: Optional[str] = Query(None),
    asset_type: Optional[str] = Query(None),
    asset_no: Optional[str] = Query(None),
    cause: Optional[str] = Query(None),
    from_date: Optional[date] = Query(None),
    from_time: Optional[time] = Query(None),
    to_date: Optional[date] = Query(None),
    to_time: Optional[time] = Query(None),
    view: str = Query("table", description="Frontend view mode. Currently returns table rows."),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
):
    """Return the Alert Summary table with the same filters shown in the UI."""
    q = _base_summary_query(
        db, zone_id, division_id, station_id, None, None, None, alert_type,
        asset_type_hex, asset_type, asset_no, cause, from_date, from_time, to_date, to_time,
    )
    summary_sq = q.subquery()
    total_rows = db.query(func.count()).select_from(summary_sq).scalar() or 0
    total_alerts = db.query(func.coalesce(func.sum(summary_sq.c.total), 0)).scalar() or 0
    total_pages, offset = _page_meta(total_rows, page, page_size)
    rows = _summary_rows(q.offset(offset).limit(page_size).all(), start=offset + 1)
    return AlertSummaryResponse(
        from_time=_combine_datetime(from_date, from_time, is_end=False).isoformat()
        if from_date or from_time else None,
        to_time=_combine_datetime(to_date, to_time, is_end=True).isoformat()
        if to_date or to_time else None,
        total=int(total_alerts),
        total_rows=total_rows,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
        rows=rows,
    )


def _download_alert_summary_response(rows: List[AlertSummaryRow]) -> StreamingResponse:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "SR", "ZONE", "DIVISION", "STATION", "ALERT TYPE", "ASSET TYPE",
        "ASSET NO.", "CAUSE", "TOTAL", "TRUE", "PARTIALLY TRUE", "% (T+PT)/TOTAL",
    ])
    for row in rows:
        writer.writerow([
            row.sr,
            row.zone,
            row.division,
            row.station,
            row.alert_type,
            row.asset_type,
            row.asset_no,
            row.cause,
            row.total,
            row.true,
            row.partially_true,
            f"{row.percentage:.1f}%",
        ])
    output.seek(0)

    filename = f"alert_summary_{date.today().isoformat()}.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/summary/export")
@router.get("/summary/download")
def download_alert_summary(
    zone_id: Optional[int] = Query(None),
    division_id: Optional[int] = Query(None),
    station_id: Optional[int] = Query(None),
    alert_type: Optional[str] = Query(None),
    asset_type_hex: Optional[str] = Query(None),
    asset_type: Optional[str] = Query(None),
    asset_no: Optional[str] = Query(None),
    cause: Optional[str] = Query(None),
    from_date: Optional[date] = Query(None),
    from_time: Optional[time] = Query(None),
    to_date: Optional[date] = Query(None),
    to_time: Optional[time] = Query(None),
    db: Session = Depends(get_db),
):
    """Download the Alert Summary report as CSV."""
    raw_rows = _base_summary_query(
        db, zone_id, division_id, station_id, None, None, None, alert_type,
        asset_type_hex, asset_type, asset_no, cause, from_date, from_time, to_date, to_time,
    ).all()
    return _download_alert_summary_response(_summary_rows(raw_rows))


@router.get("/history", response_model=AlertHistoryResponse)
def get_alert_history(
    zone_id: Optional[int] = Query(None),
    division_id: Optional[int] = Query(None),
    station_id: Optional[int] = Query(None),
    alert_type: Optional[str] = Query(None),
    asset_type_hex: Optional[str] = Query(None),
    asset_type: Optional[str] = Query(None),
    asset_no: Optional[str] = Query(None),
    cause: Optional[str] = Query(None),
    feedback: Optional[str] = Query(None),
    alert_status: Optional[str] = Query(None),
    from_date: Optional[date] = Query(None),
    from_time: Optional[time] = Query(None),
    to_date: Optional[date] = Query(None),
    to_time: Optional[time] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
):
    """Return raw alert history rows for the Alert History table."""
    q = _base_history_query(
        db, zone_id, division_id, station_id, None, None, None, alert_type,
        asset_type_hex, asset_type, asset_no, cause, feedback, alert_status,
        from_date, from_time, to_date, to_time,
    )
    total = q.count()
    total_pages, offset = _page_meta(total, page, page_size)
    rows = _history_rows(q.offset(offset).limit(page_size).all(), start=offset + 1)
    return AlertHistoryResponse(
        from_time=_combine_datetime(from_date, from_time, is_end=False).isoformat()
        if from_date or from_time else None,
        to_time=_combine_datetime(to_date, to_time, is_end=True).isoformat()
        if to_date or to_time else None,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
        rows=rows,
    )


@router.get("/history/export")
@router.get("/history/download")
def download_alert_history(
    zone_id: Optional[int] = Query(None),
    division_id: Optional[int] = Query(None),
    station_id: Optional[int] = Query(None),
    alert_type: Optional[str] = Query(None),
    asset_type_hex: Optional[str] = Query(None),
    asset_type: Optional[str] = Query(None),
    asset_no: Optional[str] = Query(None),
    cause: Optional[str] = Query(None),
    feedback: Optional[str] = Query(None),
    alert_status: Optional[str] = Query(None),
    from_date: Optional[date] = Query(None),
    from_time: Optional[time] = Query(None),
    to_date: Optional[date] = Query(None),
    to_time: Optional[time] = Query(None),
    limit: int = Query(5000, le=20000),
    db: Session = Depends(get_db),
):
    """Download the Alert History report as CSV."""
    raw_rows = _base_history_query(
        db, zone_id, division_id, station_id, None, None, None, alert_type,
        asset_type_hex, asset_type, asset_no, cause, feedback, alert_status,
        from_date, from_time, to_date, to_time,
    ).limit(limit).all()
    rows = _history_rows(raw_rows)

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "SR", "ZONE", "DIVISION", "STATION", "ALERT TYPE", "ASSET TYPE",
        "ASSET NO.", "ALERT STATUS", "CAUSE", "FEEDBACK", "INCIDENCE DATE & TIME",
        "RECTIFICATION DATE & TIME", "DURATION (MIN)", "FEEDBACK DATE & TIME",
        "MAINTAINER NAME", "DESIGNATION", "MOBILE", "REMARKS",
    ])
    for row in rows:
        writer.writerow([
            row.sr,
            row.zone,
            row.division,
            row.station,
            row.alert_type,
            row.asset_type,
            row.asset_no,
            row.alert_status,
            row.cause,
            row.feedback or "",
            row.incidence_date_time,
            row.rectification_date_time or "",
            row.duration_min if row.duration_min is not None else "",
            row.feedback_date_time or "",
            row.maintainer_name or "",
            row.designation or "",
            row.mobile or "",
            row.remarks or "",
        ])
    output.seek(0)

    filename = f"alert_history_{date.today().isoformat()}.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/filters", response_model=AlertFiltersResponse)
def get_alert_filters(db: Session = Depends(get_db)):
    """Return dropdown data for the Alert Summary filter bar."""
    zones = db.query(Zone).order_by(Zone.zone_name).all()
    divisions = db.query(Division).order_by(Division.division_name).all()
    stations = db.query(Station).order_by(Station.station_name).all()
    master_causes = db.query(AlertCauseMaster).order_by(AlertCauseMaster.cause_code).all()
    master_codes = {c.cause_code.upper() for c in master_causes}

    event_causes = [
        row.cause for row in
        db.query(AlertEvent.cause).distinct().order_by(AlertEvent.cause).all()
        if row.cause
    ]

    result_causes = []
    for c in master_causes:
        result_causes.append((c.cause_code, c.cause_detail))

    for code in event_causes:
        if code.upper() not in master_codes:
            result_causes.append((code, code))
            master_codes.add(code.upper())

    cause_options_list = [
        AlertFilterOption(id=idx, label=detail, value=code)
        for idx, (code, detail) in enumerate(result_causes, start=1)
    ]
    alert_statuses = [
        row.alert_status for row in
        db.query(AlertEvent.alert_status).distinct().order_by(AlertEvent.alert_status).all()
        if row.alert_status
    ]
    asset_numbers = [
        row.asset_no for row in
        db.query(AlertEvent.asset_no).distinct().order_by(AlertEvent.asset_no).all()
        if row.asset_no
    ]

    db_types_map = {t.asset_type_id: t for t in db.query(AssetTypeMaster).all()}

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

    alert_types_list = [
        AlertFilterOption(id=1, label="All", value="ALL"),
        AlertFilterOption(id=2, label="Predictive", value="Predictive"),
        AlertFilterOption(id=3, label="Failure", value="Failure"),
    ]

    asset_numbers_list = [
        AlertFilterOption(id=idx, label=val, value=val)
        for idx, val in enumerate(asset_numbers, start=1)
    ]

    feedbacks_list = [
        AlertFilterOption(id=idx, label=val, value=val)
        for idx, val in enumerate(FEEDBACK_OPTIONS, start=1)
    ]

    alert_statuses_list = [
        AlertFilterOption(id=idx, label=val, value=val)
        for idx, val in enumerate(alert_statuses, start=1)
    ]

    return AlertFiltersResponse(
        zones=[DropdownOption(id=z.id, label=z.zone_name, code=z.zone_code, hex_id=z.zone_id_hex) for z in zones],
        divisions=[DropdownOption(id=d.id, label=d.division_name, code=d.division_code, hex_id=d.division_id_hex) for d in divisions],
        stations=[DropdownOption(id=s.id, label=s.station_name, code=s.station_code, hex_id=s.station_id_hex) for s in stations],
        alert_types=alert_types_list,
        asset_types=asset_groups,
        asset_numbers=asset_numbers_list,
        causes=cause_options_list,
        feedbacks=feedbacks_list,
        alert_statuses=alert_statuses_list,
    )


@router.get("/events", response_model=AlertEventsResponse)
def list_alert_events(
    station_id: Optional[int] = Query(None),
    alert_type: Optional[str] = Query(None),
    asset_type_hex: Optional[str] = Query(None),
    asset_no: Optional[str] = Query(None),
    cause: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
):
    """List raw alert events used by summary and future live/history screens."""
    q = db.query(AlertEvent)
    if station_id is not None:
        q = q.filter(AlertEvent.station_id == station_id)
    normalized_alert_type = _normalize_alert_type(alert_type)
    if normalized_alert_type:
        q = q.filter(func.lower(AlertEvent.alert_type) == normalized_alert_type.lower())
    if _blank_to_none(asset_type_hex):
        q = q.filter(AlertEvent.asset_type_hex == asset_type_hex.upper())
    if _blank_to_none(asset_no):
        q = q.filter(func.lower(AlertEvent.asset_no).like(f"%{asset_no.lower()}%"))
    if _blank_to_none(cause):
        q = q.filter(func.lower(AlertEvent.cause) == cause.lower())
    total = q.count()
    total_pages, offset = _page_meta(total, page, page_size)
    rows = q.order_by(AlertEvent.alert_time.desc()).offset(offset).limit(page_size).all()
    return AlertEventsResponse(
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
        rows=rows,
    )


@router.post("/events", response_model=AlertEventResponse, status_code=status.HTTP_201_CREATED)
def create_alert_event(payload: AlertEventCreate, db: Session = Depends(get_db)):
    """Create an alert event that appears in Alert Summary."""
    _validate_event_payload(payload, db)
    record = AlertEvent(
        station_id=payload.station_id,
        alert_type=payload.alert_type.strip().title(),
        asset_type_hex=payload.asset_type_hex.upper(),
        asset_no=payload.asset_no.strip(),
        cause=payload.cause.strip().upper(),
        alert_status=payload.alert_status.strip().title(),
        feedback=payload.feedback.upper() if payload.feedback else None,
        acknowledged=payload.acknowledged,
        remark=payload.remark,
        alert_time=payload.alert_time or datetime.utcnow(),
        rectification_time=payload.rectification_time,
        feedback_time=payload.feedback_time,
        maintainer_name=payload.maintainer_name,
        designation=payload.designation,
        mobile=payload.mobile,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


@router.post("/{event_id}/feedback", response_model=AlertEventResponse)
def update_alert_feedback(event_id: int, payload: AlertFeedbackUpdate, db: Session = Depends(get_db)):
    """Set operator feedback for an alert event."""
    record = db.query(AlertEvent).filter(AlertEvent.id == event_id).first()
    if not record:
        raise HTTPException(status_code=404, detail=f"Alert event {event_id} not found")
    if payload.feedback.upper() not in {"T", "PT", "F", "M"}:
        raise HTTPException(status_code=400, detail="feedback must be one of T, PT, F, M")

    record.feedback = payload.feedback.upper()
    record.feedback_time = payload.feedback_time or datetime.utcnow()
    db.commit()
    db.refresh(record)
    return record


@router.post("/{event_id}/remark", response_model=AlertEventResponse)
def update_alert_remark(event_id: int, payload: AlertRemarkUpdate, db: Session = Depends(get_db)):
    """Set or replace remarks for an alert event."""
    record = db.query(AlertEvent).filter(AlertEvent.id == event_id).first()
    if not record:
        raise HTTPException(status_code=404, detail=f"Alert event {event_id} not found")

    record.remark = payload.remark
    db.commit()
    db.refresh(record)
    return record


@router.post("/{event_id}/acknowledge", response_model=AlertEventResponse)
def acknowledge_alert(event_id: int, db: Session = Depends(get_db)):
    """Acknowledge a live alert without clearing/rectifying it."""
    record = db.query(AlertEvent).filter(AlertEvent.id == event_id).first()
    if not record:
        raise HTTPException(status_code=404, detail=f"Alert event {event_id} not found")

    record.acknowledged = True
    if record.alert_status.lower() != "cleared":
        record.alert_status = "Acknowledged"
    db.commit()
    db.refresh(record)
    return record


@router.post("/{event_id}/rectification", response_model=AlertEventResponse)
def update_alert_rectification(
    event_id: int,
    payload: AlertRectificationUpdate,
    db: Session = Depends(get_db),
):
    """Mark an alert as rectified/cleared and store maintainer details."""
    record = db.query(AlertEvent).filter(AlertEvent.id == event_id).first()
    if not record:
        raise HTTPException(status_code=404, detail=f"Alert event {event_id} not found")

    record.alert_status = payload.alert_status.strip().title()
    record.rectification_time = payload.rectification_time or datetime.utcnow()
    record.maintainer_name = payload.maintainer_name
    record.designation = payload.designation
    record.mobile = payload.mobile
    if payload.remarks is not None:
        record.remark = payload.remarks

    db.commit()
    db.refresh(record)
    return record


@router.put("/events/{event_id}", response_model=AlertEventResponse)
def update_alert_event(event_id: int, payload: AlertEventUpdate, db: Session = Depends(get_db)):
    """Update a raw alert event."""
    record = db.query(AlertEvent).filter(AlertEvent.id == event_id).first()
    if not record:
        raise HTTPException(status_code=404, detail=f"Alert event {event_id} not found")
    _validate_event_payload(payload, db)

    for field, value in payload.model_dump(exclude_unset=True).items():
        if value is None:
            setattr(record, field, value)
        elif field in {"alert_type", "alert_status"}:
            setattr(record, field, value.strip().title())
        elif field in {"asset_type_hex", "cause", "feedback"}:
            setattr(record, field, value.upper())
        elif field == "asset_no":
            setattr(record, field, value.strip())
        else:
            setattr(record, field, value)

    db.commit()
    db.refresh(record)
    return record
