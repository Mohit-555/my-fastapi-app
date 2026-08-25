"""Timestamp parsing helpers for telemetry records.

Telemetry.prt is stored as a string in the Annexure-B wire format
("DD-MM-YYYY HH:mm:ss.SSS[ IST]") or occasionally ISO-like strings from
older rows. It must never be compared lexicographically or trusted as a
datetime — always parse through parse_prt().
"""
from datetime import datetime
from typing import Optional

_PARSERS = (
    lambda s: datetime.fromisoformat(s),
    lambda s: datetime.strptime(s, "%Y-%m-%d %H:%M:%S.%f"),
    lambda s: datetime.strptime(s, "%Y-%m-%d %H:%M:%S"),
    # Annexure B wire format
    lambda s: datetime.strptime(s, "%d-%m-%Y %H:%M:%S.%f"),
    lambda s: datetime.strptime(s, "%d-%m-%Y %H:%M:%S"),
)


def parse_prt(prt_str: Optional[str]) -> Optional[datetime]:
    """Parse a Telemetry.prt string. Returns None when unparseable.

    Callers decide the fallback (e.g. Telemetry.received_at) — this function
    deliberately never fabricates a timestamp.
    """
    if not prt_str:
        return None
    clean = prt_str.replace(" IST", "").strip()
    for parser in _PARSERS:
        try:
            parsed = parser(clean)
        except ValueError:
            continue
        # Standardize on naive datetimes (device times are naive; make any
        # tz-aware input comparable by dropping tzinfo).
        if parsed.tzinfo is not None:
            parsed = parsed.replace(tzinfo=None)
        return parsed
    return None
