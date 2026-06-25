"""
Telemetry query router — supports the dashboard's filter bar:
  Zone → Division → Station → Asset Type → Asset No → time range

Also provides a Server-Sent Events (SSE) endpoint for the LIVE indicator.
"""
import csv
import io
import asyncio
import json
from datetime import datetime, timedelta
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import and_

from app.database import get_db, SessionLocal
from app.models.models import Telemetry, Gateway, Station, Division, Zone, Threshold, Asset, AssetTypeMaster
from app.models.schemas import (
    TelemetryQueryResponse, TelemetrySeriesResponse, TelemetryPoint,
    TelemetryHistoryResponse, TelemetryHistoryColumn, TelemetryHistoryRow,
)
from app.constants import ASSET_TYPE_MAP, PARAMETER_TYPE_MAP, PARAMETER_REPR_MAP

router = APIRouter(prefix="/telemetry", tags=["Telemetry Query"])


def _resolve_station_ids(
    db: Session,
    zone_id: Optional[int],
    division_id: Optional[int],
    station_id: Optional[int],
) -> Optional[List[int]]:
    """
    Return a flat list of station IDs matching the given filter combination.
    Returns None if no filter is set (= all stations).
    """
    if station_id:
        return [station_id]

    if division_id:
        rows = db.query(Station.id).filter(Station.division_id == division_id).all()
        return [r.id for r in rows]

    if zone_id:
        div_ids = [r.id for r in db.query(Division.id).filter(Division.zone_id == zone_id).all()]
        if not div_ids:
            return []
        rows = db.query(Station.id).filter(Station.division_id.in_(div_ids)).all()
        return [r.id for r in rows]

    return None  # no filter → all


def _get_threshold(
    db: Session,
    asset_type_hex: str,
    parameter_type_hex: str,
    station_id: Optional[int],
) -> Optional[Threshold]:
    """
    Look up threshold with station-specific override priority.
    First tries station-specific, then falls back to the global default.
    """
    if station_id:
        t = db.query(Threshold).filter(
            Threshold.asset_type_hex == asset_type_hex,
            Threshold.parameter_type_hex == parameter_type_hex,
            Threshold.station_id == station_id,
        ).first()
        if t:
            return t
    # fall back to global default (station_id IS NULL)
    return db.query(Threshold).filter(
        Threshold.asset_type_hex == asset_type_hex,
        Threshold.parameter_type_hex == parameter_type_hex,
        Threshold.station_id.is_(None),
    ).first()


def _build_series(
    db: Session,
    para_id: str,
    rows: List[Telemetry],
    gateway: Gateway,
) -> TelemetrySeriesResponse:
    """Build a TelemetrySeriesResponse from a list of Telemetry rows for one para_id."""
    asset_type_hex      = para_id[0:2]
    asset_number_hex    = para_id[2:4]
    parameter_type_hex  = para_id[4:6]
    repr_hex            = para_id[6:8]

    asset_info  = ASSET_TYPE_MAP.get(asset_type_hex)
    param_info  = PARAMETER_TYPE_MAP.get(parameter_type_hex)
    repr_info   = PARAMETER_REPR_MAP.get(repr_hex)

    threshold = _get_threshold(db, asset_type_hex, parameter_type_hex, gateway.station_id)

    data_points = [
        TelemetryPoint(
            t=row.prt or row.received_at.isoformat(),
            v=row.prv,
        )
        for row in sorted(rows, key=lambda r: r.received_at)
    ]

    latest = rows[0].prv if rows else None  # rows already ordered desc

    return TelemetrySeriesResponse(
        para_id=para_id,
        asset_type_hex=asset_type_hex,
        asset_type_name=asset_info[1] if asset_info else None,
        asset_type_code=asset_info[0] if asset_info else None,
        asset_number_hex=asset_number_hex,
        parameter_type_hex=parameter_type_hex,
        parameter_name=param_info[1] if param_info else None,
        parameter_unit=param_info[2] if param_info else None,
        representation=repr_info[1] if repr_info else None,
        stngw_id=gateway.stngw_id,
        data=data_points,
        latest_value=latest,
        threshold_warning_low=threshold.warning_low if threshold else None,
        threshold_warning_high=threshold.warning_high if threshold else None,
        threshold_critical_low=threshold.critical_low if threshold else None,
        threshold_critical_high=threshold.critical_high if threshold else None,
    )


@router.get("", response_model=TelemetryQueryResponse)
def query_telemetry(
    # ── Location filters ──────────────────────────────────────────────────────
    zone_id:     Optional[int]  = Query(None, description="Filter by zone"),
    division_id: Optional[int]  = Query(None, description="Filter by division"),
    station_id:  Optional[int]  = Query(None, description="Filter by station"),
    # ── Asset filters ─────────────────────────────────────────────────────────
    asset_type_hex: Optional[str] = Query(
        None,
        description="Asset type hex(es), comma-separated. e.g. '00' or '2D,2E,2F' for AC Track Circuit group",
    ),
    asset_number_hex: Optional[str] = Query(
        None,
        description="Asset number hex (bytes 2-3 of para_id), e.g. '01' for asset #1",
    ),
    parameter_type_hex: Optional[str] = Query(
        None,
        description="Parameter type hex (bytes 4-5 of para_id), e.g. '02' for Peak Current",
    ),
    # ── Time range ────────────────────────────────────────────────────────────
    from_time: Optional[datetime] = Query(
        None,
        description="Start of time range (ISO 8601). Defaults to 1 hour ago.",
    ),
    to_time: Optional[datetime] = Query(
        None,
        description="End of time range (ISO 8601). Defaults to now.",
    ),
    limit: int = Query(500, le=5000, description="Max readings per para_id"),
    db: Session = Depends(get_db),
):
    """
    Main telemetry query endpoint used by the dashboard filter bar.

    Returns grouped time-series data with threshold values and parameter metadata
    for every matching para_id × gateway combination.

    Examples:
      GET /telemetry?station_id=12&asset_type_hex=00
        → All Point Machine readings at station 12 for the last hour

      GET /telemetry?zone_id=7&division_id=3&asset_type_hex=2D,2E,2F&from_time=2025-11-04T10:00:00
        → AC Track Circuit data across all stations in a division since a given time
    """
    now = datetime.utcnow()
    if from_time is None:
        from_time = now - timedelta(hours=1)
    if to_time is None:
        to_time = now

    # ── Resolve station IDs from location filter ──────────────────────────────
    station_ids = _resolve_station_ids(db, zone_id, division_id, station_id)

    # ── Resolve gateway IDs ───────────────────────────────────────────────────
    gw_query = db.query(Gateway)
    if station_ids is not None:
        if not station_ids:
            # Location filter matched nothing
            return TelemetryQueryResponse(
                station_id=station_id,
                station_name=None,
                asset_type_hex=asset_type_hex,
                asset_number=asset_number_hex,
                from_time=from_time.isoformat(),
                to_time=to_time.isoformat(),
                series=[],
            )
        gw_query = gw_query.filter(Gateway.station_id.in_(station_ids))

    gateways = gw_query.all()
    if not gateways:
        return TelemetryQueryResponse(
            station_id=station_id,
            station_name=None,
            asset_type_hex=asset_type_hex,
            asset_number=asset_number_hex,
            from_time=from_time.isoformat(),
            to_time=to_time.isoformat(),
            series=[],
        )

    gateway_ids = [g.id for g in gateways]
    gateway_map = {g.id: g for g in gateways}

    # ── Build para_id prefix filters ─────────────────────────────────────────
    # para_id is 8 hex chars: [asset_type 2][asset_num 2][param_type 2][repr 2]
    # We filter with LIKE patterns for efficient DB-side filtering.
    base_filters = [
        Telemetry.gateway_id.in_(gateway_ids),
        Telemetry.received_at >= from_time,
        Telemetry.received_at <= to_time,
    ]

    asset_type_hexes = (
        [h.strip().upper() for h in asset_type_hex.split(",")]
        if asset_type_hex else None
    )

    # Fetch rows
    telem_query = db.query(Telemetry).filter(and_(*base_filters))

    # Apply para_id prefix filters in Python (avoids complex SQL LIKE OR chains)
    rows_all = (
        telem_query
        .order_by(Telemetry.received_at.desc())
        .limit(limit * 20)      # fetch extra, we'll filter + group in Python
        .all()
    )

    # ── Group by (gateway_id, para_id) and apply asset/param filters ──────────
    grouped: dict[tuple, list] = {}
    for row in rows_all:
        pid = row.para_id  # already upper from ingestion
        if len(pid) != 8:
            continue

        at_hex  = pid[0:2]
        an_hex  = pid[2:4]
        pt_hex  = pid[4:6]

        if asset_type_hexes and at_hex not in asset_type_hexes:
            continue
        if asset_number_hex and an_hex != asset_number_hex.upper():
            continue
        if parameter_type_hex and pt_hex != parameter_type_hex.upper():
            continue

        key = (row.gateway_id, pid)
        if key not in grouped:
            grouped[key] = []
        if len(grouped[key]) < limit:
            grouped[key].append(row)

    # ── Build series list ─────────────────────────────────────────────────────
    series: List[TelemetrySeriesResponse] = []
    for (gw_id, para_id_key), rows in grouped.items():
        gw = gateway_map[gw_id]
        series.append(_build_series(db, para_id_key, rows, gw))

    # ── Station name for response metadata ────────────────────────────────────
    stn_name = None
    if station_id:
        stn = db.query(Station).filter(Station.id == station_id).first()
        stn_name = stn.station_name if stn else None

    return TelemetryQueryResponse(
        station_id=station_id,
        station_name=stn_name,
        asset_type_hex=asset_type_hex,
        asset_number=asset_number_hex,
        from_time=from_time.isoformat(),
        to_time=to_time.isoformat(),
        series=series,
    )


@router.get("/latest/{station_id}", response_model=List[TelemetrySeriesResponse])
def get_latest_by_station(
    station_id: int,
    asset_type_hex: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """
    Get the single latest reading for every para_id at a station.
    Used to populate the dashboard summary strip / health cards.
    """
    station = db.query(Station).filter(Station.id == station_id).first()
    if not station:
        raise HTTPException(status_code=404, detail=f"Station {station_id} not found")

    gateways = db.query(Gateway).filter(Gateway.station_id == station_id).all()
    if not gateways:
        return []

    asset_type_hexes = (
        [h.strip().upper() for h in asset_type_hex.split(",")]
        if asset_type_hex else None
    )

    series = []
    for gw in gateways:
        # Get distinct para_ids for this gateway
        para_ids = (
            db.query(Telemetry.para_id)
            .filter(Telemetry.gateway_id == gw.id)
            .distinct()
            .all()
        )
        for (pid,) in para_ids:
            if len(pid) != 8:
                continue
            if asset_type_hexes and pid[0:2] not in asset_type_hexes:
                continue

            latest_row = (
                db.query(Telemetry)
                .filter(Telemetry.gateway_id == gw.id, Telemetry.para_id == pid)
                .order_by(Telemetry.received_at.desc())
                .first()
            )
            if latest_row:
                series.append(_build_series(db, pid, [latest_row], gw))

    return series


# ── SSE Live Stream ───────────────────────────────────────────────────────────

async def _sse_event_generator(station_id: int, asset_type_hexes: Optional[List[str]], poll_interval: int):
    """
    Async generator that polls for new telemetry every `poll_interval` seconds
    and yields SSE-formatted events.
    """
    last_seen_id = 0

    while True:
        db = SessionLocal()
        try:
            gateways = db.query(Gateway).filter(Gateway.station_id == station_id).all()
            gw_ids = [g.id for g in gateways]
            gateway_map = {g.id: g for g in gateways}

            if gw_ids:
                q = (
                    db.query(Telemetry)
                    .filter(
                        Telemetry.gateway_id.in_(gw_ids),
                        Telemetry.id > last_seen_id,
                    )
                    .order_by(Telemetry.id.asc())
                    .limit(100)
                )
                new_rows = q.all()

                if new_rows:
                    last_seen_id = new_rows[-1].id

                    # Group by para_id and emit one event per para_id
                    grouped: dict[str, list] = {}
                    for row in new_rows:
                        pid = row.para_id
                        if len(pid) != 8:
                            continue
                        if asset_type_hexes and pid[0:2] not in asset_type_hexes:
                            continue
                        grouped.setdefault(pid, []).append(row)

                    for pid, rows in grouped.items():
                        gw = gateway_map[rows[0].gateway_id]
                        param_info = PARAMETER_TYPE_MAP.get(pid[4:6])
                        asset_info = ASSET_TYPE_MAP.get(pid[0:2])
                        threshold = _get_threshold(db, pid[0:2], pid[4:6], station_id)

                        payload = {
                            "para_id": pid,
                            "stngw_id": gw.stngw_id,
                            "asset_type_hex": pid[0:2],
                            "asset_type_name": asset_info[1] if asset_info else None,
                            "parameter_name": param_info[1] if param_info else None,
                            "parameter_unit": param_info[2] if param_info else None,
                            "points": [
                                {"t": r.prt or r.received_at.isoformat(), "v": r.prv}
                                for r in rows
                            ],
                            "threshold_warning_high": threshold.warning_high if threshold else None,
                            "threshold_critical_high": threshold.critical_high if threshold else None,
                        }
                        yield f"data: {json.dumps(payload)}\n\n"

        except Exception as e:
            yield f"event: error\ndata: {json.dumps({'detail': str(e)})}\n\n"
        finally:
            db.close()

        await asyncio.sleep(poll_interval)

@router.get("/live/{station_id}")
async def live_telemetry_stream(
    station_id: int,
    token: str = Query(..., description="Access token (required because EventSource cannot send headers)"),
    asset_type_hex: Optional[str] = Query(
        None,
        description="Comma-separated asset_type_hex values to subscribe to, e.g. '00' or '00,20'",
    ),
    poll_interval: int = Query(5, ge=1, le=60, description="Polling interval in seconds (1–60)"),
    db: Session = Depends(get_db),
):
    """
    Server-Sent Events stream for live telemetry at a station.

    Connect with EventSource in the browser:
      const es = new EventSource('/telemetry/live/12?token=YOUR_TOKEN&asset_type_hex=00&poll_interval=5');
      es.onmessage = (e) => { const d = JSON.parse(e.data); ... };

    Each event payload:
    {
      "para_id": "00010202",
      "stngw_id": "05011200",
      "asset_type_name": "Point Machine",
      "parameter_name": "Peak Current",
      "parameter_unit": "A",
      "points": [{"t": "...", "v": 7.63}],
      "threshold_warning_high": 9.0,
      "threshold_critical_high": 11.0
    }
    """
    from app.auth_utils import get_current_user_from_token
    get_current_user_from_token(token, db)   # validates token — raises 401 if invalid

    station = db.query(Station).filter(Station.id == station_id).first()
    if not station:
        raise HTTPException(status_code=404, detail=f"Station {station_id} not found")

    asset_type_hexes = (
        [h.strip().upper() for h in asset_type_hex.split(",")]
        if asset_type_hex else None
    )

    return StreamingResponse(
        _sse_event_generator(station_id, asset_type_hexes, poll_interval),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
# ── Telemetry History ─────────────────────────────────────────────────────────

def _fetch_history_data(
    db: Session,
    zone_id: Optional[int],
    division_id: Optional[int],
    station_id: Optional[int],
    asset_type_hex: Optional[str],
    asset_number_hex: Optional[str],
    parameter_type_hex: Optional[str],
    from_time: datetime,
    to_time: datetime,
    limit: int = 10000,
):
    """
    Shared data-fetch logic for history table and CSV download.
    Returns (gateway_map, grouped_rows, asset_type_hexes_list).
    grouped_rows: dict[(gateway_id, para_id)] → List[Telemetry] sorted asc by received_at
    """
    station_ids = _resolve_station_ids(db, zone_id, division_id, station_id)

    gw_query = db.query(Gateway)
    if station_ids is not None:
        if not station_ids:
            return {}, {}, []
        gw_query = gw_query.filter(Gateway.station_id.in_(station_ids))

    gateways = gw_query.all()
    if not gateways:
        return {}, {}, []

    gateway_ids = [g.id for g in gateways]
    gateway_map = {g.id: g for g in gateways}

    asset_type_hexes = (
        [h.strip().upper() for h in asset_type_hex.split(",")]
        if asset_type_hex else None
    )

    rows_all = (
        db.query(Telemetry)
        .filter(
            Telemetry.gateway_id.in_(gateway_ids),
            Telemetry.received_at >= from_time,
            Telemetry.received_at <= to_time,
        )
        .order_by(Telemetry.received_at.asc())
        .limit(limit)
        .all()
    )

    grouped: dict[tuple, list] = {}
    for row in rows_all:
        pid = row.para_id
        if len(pid) != 8:
            continue
        at_hex = pid[0:2]
        an_hex = pid[2:4]
        pt_hex = pid[4:6]

        if asset_type_hexes and at_hex not in asset_type_hexes:
            continue
        if asset_number_hex and an_hex != asset_number_hex.upper():
            continue
        if parameter_type_hex and pt_hex != parameter_type_hex.upper():
            continue

        key = (row.gateway_id, pid)
        grouped.setdefault(key, []).append(row)

    return gateway_map, grouped, asset_type_hexes


def _build_history_columns_and_rows(
    db: Session,
    gateway_map: dict,
    grouped: dict,
    station_id: Optional[int],
) -> tuple[list[TelemetryHistoryColumn], list[TelemetryHistoryRow]]:
    """
    Pivot grouped telemetry into history table columns and rows.

    Columns  = one per unique parameter_type (e.g. I_AVG, I_PEAK, V_BATT …)
    Rows     = one per (timestamp, asset_number_hex, stngw_id)
    """
    # ── Build columns from discovered para_ids ────────────────────────────────
    # key: parameter_type_hex → TelemetryHistoryColumn
    col_map: dict[str, TelemetryHistoryColumn] = {}
    for (gw_id, pid) in grouped:
        pt_hex = pid[4:6]
        if pt_hex in col_map:
            continue
        param_info = PARAMETER_TYPE_MAP.get(pt_hex)
        if not param_info:
            continue
        p_name = param_info[1]
        p_unit = param_info[2]
        col_key = f"{p_name} ({p_unit})" if p_unit else p_name

        gw = gateway_map[gw_id]
        at_hex = pid[0:2]
        threshold = _get_threshold(db, at_hex, pt_hex, gw.station_id or station_id)

        col_map[pt_hex] = TelemetryHistoryColumn(
            key=col_key,
            parameter_name=p_name,
            parameter_unit=p_unit,
            parameter_type_hex=pt_hex,
            threshold_warning_low=threshold.warning_low if threshold else None,
            threshold_warning_high=threshold.warning_high if threshold else None,
            threshold_critical_low=threshold.critical_low if threshold else None,
            threshold_critical_high=threshold.critical_high if threshold else None,
        )

    columns = sorted(col_map.values(), key=lambda c: c.parameter_type_hex)

    # ── Pivot rows ────────────────────────────────────────────────────────────
    # Each unique (timestamp_str, asset_number_hex, stngw_id) becomes one row.
    # row_index: (ts, an_hex, stngw_id) → {col_key: value}
    row_index: dict[tuple, dict] = {}

    for (gw_id, pid), telem_rows in grouped.items():
        pt_hex = pid[4:6]
        an_hex = pid[2:4]
        if pt_hex not in col_map:
            continue
        col_key = col_map[pt_hex].key
        gw = gateway_map[gw_id]

        for row in telem_rows:
            ts = row.prt or row.received_at.isoformat()
            index_key = (ts, an_hex, gw.stngw_id)
            if index_key not in row_index:
                row_index[index_key] = {}
            row_index[index_key][col_key] = row.prv

    # Sort by timestamp ascending
    history_rows = [
        TelemetryHistoryRow(
            timestamp=ts,
            asset_number_hex=an_hex,
            stngw_id=stngw_id,
            values=vals,
        )
        for (ts, an_hex, stngw_id), vals in sorted(row_index.items(), key=lambda x: x[0][0], reverse=True)
    ]

    return columns, history_rows


@router.get("/history", response_model=TelemetryHistoryResponse)
def get_telemetry_history(
    zone_id:          Optional[int]      = Query(None),
    division_id:      Optional[int]      = Query(None),
    station_id:       Optional[int]      = Query(None),
    asset_type_hex:   Optional[str]      = Query(None, description="Comma-separated, e.g. '00' or '2D,2E,2F'"),
    asset_number_hex: Optional[str]      = Query(None, description="Asset number hex, e.g. '01'"),
    parameter_type_hex: Optional[str]    = Query(None, description="Filter to one parameter type"),
    from_time:        Optional[datetime] = Query(None, description="ISO 8601 start time"),
    to_time:          Optional[datetime] = Query(None, description="ISO 8601 end time. Defaults to now."),
    page:             int                = Query(1, ge=1),
    page_size:        int                = Query(50, ge=1, le=500),
    db:               Session            = Depends(get_db),
):
    """
    Telemetry History — paginated, pivoted table rows.

    Returns one row per timestamp with all parameter values as columns.
    Used by the Telemetry History screen with date/time range pickers.

    Example:
      GET /telemetry/history?station_id=1&asset_type_hex=00&from_time=2026-06-04T10:00:00
    """
    now = datetime.utcnow()
    if from_time is None:
        from_time = now - timedelta(hours=24)
    if to_time is None:
        to_time = now

    gateway_map, grouped, _ = _fetch_history_data(
        db, zone_id, division_id, station_id,
        asset_type_hex, asset_number_hex, parameter_type_hex,
        from_time, to_time,
    )

    if not grouped:
        stn_name = None
        if station_id:
            stn = db.query(Station).filter(Station.id == station_id).first()
            stn_name = stn.station_name if stn else None
        return TelemetryHistoryResponse(
            station_id=station_id,
            station_name=stn_name,
            asset_type_hex=asset_type_hex,
            asset_number=asset_number_hex,
            from_time=from_time.isoformat(),
            to_time=to_time.isoformat(),
            columns=[],
            total=0,
            page=page,
            page_size=page_size,
            total_pages=0,
            rows=[],
        )

    columns, all_rows = _build_history_columns_and_rows(db, gateway_map, grouped, station_id)

    total = len(all_rows)
    total_pages = (total + page_size - 1) // page_size if total else 0
    offset = (page - 1) * page_size
    paginated_rows = all_rows[offset: offset + page_size]

    stn_name = None
    if station_id:
        stn = db.query(Station).filter(Station.id == station_id).first()
        stn_name = stn.station_name if stn else None

    return TelemetryHistoryResponse(
        station_id=station_id,
        station_name=stn_name,
        asset_type_hex=asset_type_hex,
        asset_number=asset_number_hex,
        from_time=from_time.isoformat(),
        to_time=to_time.isoformat(),
        columns=columns,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
        rows=paginated_rows,
    )


@router.get("/history/download")
def download_telemetry_history(
    zone_id:          Optional[int]      = Query(None),
    division_id:      Optional[int]      = Query(None),
    station_id:       Optional[int]      = Query(None),
    asset_type_hex:   Optional[str]      = Query(None),
    asset_number_hex: Optional[str]      = Query(None),
    parameter_type_hex: Optional[str]    = Query(None),
    from_time:        Optional[datetime] = Query(None),
    to_time:          Optional[datetime] = Query(None),
    db:               Session            = Depends(get_db),
):
    """
    Download Telemetry History as CSV.
    Same filters as GET /telemetry/history — no pagination, returns all rows up to 20,000.

    Used by the Download button on the Telemetry History screen.
    """
    from datetime import date as date_type
    now = datetime.utcnow()
    if from_time is None:
        from_time = now - timedelta(hours=24)
    if to_time is None:
        to_time = now

    gateway_map, grouped, _ = _fetch_history_data(
        db, zone_id, division_id, station_id,
        asset_type_hex, asset_number_hex, parameter_type_hex,
        from_time, to_time,
        limit=20000,
    )

    columns, all_rows = _build_history_columns_and_rows(db, gateway_map, grouped, station_id)

    output = io.StringIO()
    writer = csv.writer(output)

    # Header row
    writer.writerow(["DATE & TIME", "ASSET NO.", "GATEWAY"] + [c.key for c in columns])

    # Data rows
    for row in all_rows:
        writer.writerow(
            [row.timestamp, row.asset_number_hex, row.stngw_id]
            + [row.values.get(c.key, "") for c in columns]
        )

    output.seek(0)
    filename = f"telemetry_history_{date_type.today().isoformat()}.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ── Telemetry Integration Endpoints ───────────────────────────────────────────
import uuid
from pydantic import BaseModel, Field, AliasChoices

integration_router = APIRouter(tags=["Telemetry Integration"])

class AssetNumberFilter(BaseModel):
    sc: str
    asset_number_code: str = Field(..., validation_alias=AliasChoices("asset_number_code", "assetNumberCode"))

class TelemetryHistoryRequestFilter(BaseModel):
    zone: Optional[List[str]] = []
    division: Optional[List[str]] = []
    station: Optional[List[str]] = []
    asset_type: Optional[List[str]] = Field([], validation_alias=AliasChoices("asset_type", "assetType"))
    asset_number: Optional[List[AssetNumberFilter]] = Field([], validation_alias=AliasChoices("asset_number", "assetNumber"))

class TelemetryHistoryReportRequest(BaseModel):
    start_date: str = Field(..., validation_alias=AliasChoices("start_date", "startDate"))
    start_time: str = Field(..., validation_alias=AliasChoices("start_time", "startTime"))
    end_date: str = Field(..., validation_alias=AliasChoices("end_date", "endDate"))
    end_time: str = Field(..., validation_alias=AliasChoices("end_time", "endTime"))
    request: TelemetryHistoryRequestFilter
    page_number: Optional[int] = Field(1, validation_alias=AliasChoices("page_number", "pageNumber"))
    page_size: Optional[int] = Field(20, validation_alias=AliasChoices("page_size", "pageSize"))

class SMMTelemetryRequest(BaseModel):
    rqi: Optional[str] = None
    vcc: Optional[str] = "XYZ"
    zc: Optional[str] = None
    dc: Optional[str] = None
    sc: Optional[str] = None
    smm_asset_code: Optional[str] = Field(None, validation_alias=AliasChoices("smm_asset_code", "smmAssetCode"))
    para_id: Optional[List[str]] = Field([], validation_alias=AliasChoices("para_id", "paraId"))


@integration_router.post("/vc_telemetry_history")
def vc_telemetry_history(payload: TelemetryHistoryReportRequest, db: Session = Depends(get_db)):
    # 1. Parse start and end datetimes
    def _parse_dt(date_str: str, time_str: str) -> datetime:
        for d_fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
            try:
                d = datetime.strptime(date_str.strip(), d_fmt).date()
                break
            except ValueError:
                continue
        else:
            raise HTTPException(status_code=400, detail=f"Could not parse date: {date_str}")
        
        for t_fmt in ("%H:%M:%S", "%H:%M"):
            try:
                t = datetime.strptime(time_str.strip(), t_fmt).time()
                break
            except ValueError:
                continue
        else:
            raise HTTPException(status_code=400, detail=f"Could not parse time: {time_str}")
        
        return datetime.combine(d, t)

    start_dt = _parse_dt(payload.start_date, payload.start_time)
    end_dt = _parse_dt(payload.end_date, payload.end_time)

    # 2. Filter assets
    asset_q = db.query(Asset).join(Station).join(Division).join(Zone)
    
    req_filter = payload.request
    if req_filter.zone:
        asset_q = asset_q.filter(Zone.zone_code.in_(req_filter.zone))
    if req_filter.division:
        asset_q = asset_q.filter(Division.division_code.in_(req_filter.division))
    if req_filter.station:
        asset_q = asset_q.filter(Station.station_code.in_(req_filter.station))
    if req_filter.asset_type:
        asset_q = asset_q.join(AssetTypeMaster).filter(AssetTypeMaster.asset_type_code.in_(req_filter.asset_type))
        
    if req_filter.asset_number:
        conditions = []
        for item in req_filter.asset_number:
            conditions.append(and_(Station.station_code == item.sc, Asset.asset_number_code == item.asset_number_code))
        from sqlalchemy import or_
        asset_q = asset_q.filter(or_(*conditions))

    total_assets = asset_q.count()
    offset = (payload.page_number - 1) * payload.page_size
    assets = asset_q.offset(offset).limit(payload.page_size).all()

    # 3. Build hierarchy map
    hierarchy = {}

    for asset in assets:
        zc = asset.station.division.zone.zone_code
        dc = asset.station.division.division_code
        sc = asset.station.station_code
        
        gateway = asset.gateway
        if not gateway:
            continue
            
        prefix = f"{asset.asset_type_hex}{asset.asset_number_id}"
        
        telemetry_rows = (
            db.query(Telemetry)
            .filter(
                Telemetry.gateway_id == gateway.id,
                Telemetry.para_id.like(f"{prefix}%"),
                Telemetry.received_at >= start_dt,
                Telemetry.received_at <= end_dt
            )
            .order_by(Telemetry.received_at.desc())
            .all()
        )
        
        param_values = {}
        for row in telemetry_rows:
            pt_hex = row.para_id[4:6]
            param_info = PARAMETER_TYPE_MAP.get(pt_hex)
            if not param_info:
                continue
            param_name = param_info[1]
            key = f"{asset.asset_number_code} {param_name}"
            if key not in param_values:
                param_values[key] = row.prv

        if not param_values:
            continue

        zone_node = hierarchy.setdefault(zc, {})
        division_node = zone_node.setdefault(dc, {})
        station_node = division_node.setdefault(sc, {})
        station_node.update(param_values)

    zone_list = []
    for zc, divisions_dict in hierarchy.items():
        div_list = []
        for dc, stations_dict in divisions_dict.items():
            stn_list = []
            for sc, params in stations_dict.items():
                stn_list.append({
                    "sc": sc,
                    "parameters": params
                })
            div_list.append({
                "dc": dc,
                "station": stn_list
            })
        zone_list.append({
            "zc": zc,
            "division": div_list
        })

    return {
        "vcc": "XYZ",
        "vcn": "XYZ TECHNOLOGIES",
        "start_date": payload.start_date,
        "start_time": payload.start_time,
        "end_date": payload.end_date,
        "end_time": payload.end_time,
        "zone": zone_list
    }


def _handle_get_asset_telemetry(
    zc: str,
    dc: str,
    sc: str,
    smm_asset_code: str,
    para_id: str,
    payload_rqi: Optional[str],
    payload_vcc: Optional[str],
    payload_para_ids: Optional[List[str]],
    db: Session
):
    asset = db.query(Asset).filter(Asset.smms_asset_code == smm_asset_code).first()
    if not asset:
        raise HTTPException(status_code=404, detail=f"Asset with SMMS code '{smm_asset_code}' not found")

    gateway = asset.gateway
    if not gateway:
        raise HTTPException(status_code=404, detail=f"Gateway not found for asset '{smm_asset_code}'")

    pids = []
    if payload_para_ids:
        pids = [pid.strip().upper() for pid in payload_para_ids if pid]
    else:
        pids = [pid.strip().upper() for pid in para_id.split(",") if pid]

    telemetry_data_list = []
    for pid in pids:
        row = (
            db.query(Telemetry)
            .filter(Telemetry.gateway_id == gateway.id, Telemetry.para_id == pid)
            .order_by(Telemetry.received_at.desc())
            .first()
        )
        if row:
            ts_str = row.prt
            if not ts_str:
                ts_str = row.received_at.strftime("%d-%m-%Y %H:%M:%S.000")
            telemetry_data_list.append({
                "para_id": pid,
                "prv": row.prv,
                "prt": ts_str
            })

    return {
        "resi": "RES-" + (payload_rqi or uuid.uuid4().hex[:12]),
        "vcc": payload_vcc or "XYZ",
        "zc": zc,
        "dc": dc,
        "sc": sc,
        "telemetry_data": [
            {
                "sms_asset_code": smm_asset_code,
                "parameters": telemetry_data_list
            }
        ]
    }


@integration_router.get("/get_asset_telemetry/{zc}/{dc}/{sc}/{smm_asset_code}/{para_id}")
def get_asset_telemetry_get(
    zc: str,
    dc: str,
    sc: str,
    smm_asset_code: str,
    para_id: str,
    db: Session = Depends(get_db)
):
    return _handle_get_asset_telemetry(
        zc=zc, dc=dc, sc=sc, smm_asset_code=smm_asset_code, para_id=para_id,
        payload_rqi=None, payload_vcc="XYZ", payload_para_ids=None,
        db=db
    )


@integration_router.post("/get_asset_telemetry/{zc}/{dc}/{sc}/{smm_asset_code}/{para_id}")
def get_asset_telemetry_post(
    zc: str,
    dc: str,
    sc: str,
    smm_asset_code: str,
    para_id: str,
    payload: Optional[SMMTelemetryRequest] = None,
    db: Session = Depends(get_db)
):
    rqi = payload.rqi if payload else None
    vcc = payload.vcc if payload else "XYZ"
    pids = payload.para_id if payload else None
    return _handle_get_asset_telemetry(
        zc=zc, dc=dc, sc=sc, smm_asset_code=smm_asset_code, para_id=para_id,
        payload_rqi=rqi, payload_vcc=vcc, payload_para_ids=pids,
        db=db
    )