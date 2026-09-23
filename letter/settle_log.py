"""
Our own record of the front-month settles, written every time a letter is built.

WHY THIS EXISTS. The week-over-week change needs one number per contract: the
prior Friday's settle. That normally comes from Massive's /aggs history -- and
that history has had NO BARS AT ALL for 2026-09-14..09-18 for over a week. The
live /snapshot endpoint the Seasonal dashboard uses was fine throughout; only
the historical series has the hole. So the durable fix is not a different API,
it is to stop depending on someone else's history for a number we see every day
anyway.

Every build appends what it just fetched. After one Friday's letter is built,
the following Tuesday's weekly change comes out of this file and never touches
/aggs again.

NOT IN out/. That directory is scratch and gets cleared; losing this file would
silently take the weekly change with it. It lives beside the code, gitignored --
it is market data, not source.

Last write wins for a given (ticker, date), so a letter rebuilt after the close
corrects an intraday value recorded earlier the same day.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

LOG_PATH = Path(__file__).resolve().parent / "data" / "settle_log.json"


def load(path: Path = None) -> dict:
    """{ticker: {iso_date: settle}}, or {} if nothing has been recorded yet."""
    p = Path(path or LOG_PATH)
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def record(ctx: dict, path: Path = None) -> int:
    """
    Append the settles this build fetched. Returns how many were written.

    Records against each contract's OWN settle_date, not the issue date -- on a
    Monday holiday, or when the newest bar lags, those differ and filing the
    price under the wrong day is exactly the error this is meant to prevent.
    """
    p = Path(path or LOG_PATH)
    log = load(p)

    written = 0
    for key in ("live_cattle", "feeder_cattle"):
        for c in ctx.get(key) or []:
            ticker, settle = c.get("ticker"), c.get("settle")
            when = str(c.get("settle_date") or "")[:10]
            if not ticker or settle is None or not when:
                continue
            log.setdefault(ticker, {})[when] = float(settle)
            written += 1

    if written:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(log, indent=2, sort_keys=True), encoding="utf-8")
    return written


def settles_on(when: date, path: Path = None) -> dict:
    """{ticker: settle} for one date, from whatever has been recorded."""
    iso = when.isoformat()
    return {t: v[iso] for t, v in load(path).items() if iso in v}


def coverage(path: Path = None) -> tuple:
    """(number of tickers, earliest date, latest date) -- for reporting."""
    log = load(path)
    days = sorted({d for v in log.values() for d in v})
    return (len(log), days[0] if days else None, days[-1] if days else None)
