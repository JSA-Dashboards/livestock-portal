"""
Every number on the board, fetched once, from the module that already owns it.

THE BOARD CALLS THE SAME FUNCTION THE PAGE IT SUMMARISES CALLS. That is the
whole architecture and everything else here serves it. There is no second
implementation of any figure, so there is nothing to drift -- the failure
CLAUDE.md records four times, where the letter and a dashboard quoted the same
number, disagreed, and both were defensible.

**IT NEVER CALLS `letter.build.gather()`.** That function looks like a pure
assembly and is not: `build.py:324` runs `settle_log.sync()`, which INSERTs
local-only entries into `JSA.LETTER.DRAFTS`. A dashboard calling it would write
to the letter's durable store on every page load, from every viewer's session.
The individual `letter.sources.fetch_*` functions are read-only and are what
this uses.

**EVERY CACHE KEY CARRIES `SCHEMA`, AND THAT IS NOT BELT AND BRACES.**
`st.cache_data` keys on the decorated function's own code and its arguments and
NEVER on the modules it calls. Adding a key to `leverage.load()` once changed
nothing on the Packer Leverage tab -- the tile read a dash and the whole
section vanished, silently -- because `fetch_leverage`'s one-line body had not
changed and the disk cache kept handing back a dict from before the key
existed. `SCHEMA` below is a TUPLE of this module's version and every upstream
module's, so an upstream reshape invalidates us too.

**NO `persist="disk"` ANYWHERE.** Streamlit ignores `ttl` when `persist` is
set, so a cache written that way never expires. That is not theoretical here:
it is exactly how `fetch_leverage` on the Cash Cattle Trade page froze, keyed
on a constant sentinel, until it was fixed on 2026-10-07.

**EVERY LOADER RETURNS A DICT AND RAISES NOTHING.** A failed fetch returns
`{"error": ...}` and the board renders that signal as MISSING with the reason.
A raise here would stop the Streamlit script and blank the page -- and a board
whose whole job is showing twenty numbers must not be taken down by one dead
feed.
"""

from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import requests
import streamlit as st

REPO = Path(__file__).resolve().parent.parent.parent
APPS = REPO / "apps"

# Both of these exist exactly ONCE in the repo, so unlike `snowflake_db` they
# cannot join the five-copy sys.modules collision CLAUDE.md documents. Checked
# before adding either: leverage.py imports neither `requests` nor
# `snowflake_db`, so this page widens no collision set at all.
sys.path.insert(0, str(APPS / "cash_trade"))
sys.path.insert(0, str(APPS / "fed_cattle_crush"))

import leverage                      # noqa: E402
import corn_cost                     # noqa: E402

sys.path.insert(0, str(REPO))
from letter import sources           # noqa: E402

#: LM_CT150. Named here rather than imported because `leverage` does not define
#: it and `apps/cash_trade/app.py` is a page, not an importable module.
#: tests/test_market_board.py pins it against the page's own constant.
CT150_ID = 2477

#: Bump when a loader changes the SHAPE of what it returns. See the docstring.
BOARD_SCHEMA = 1

#: The full key. Every cached function takes it, and a test asserts that.
SCHEMA = (BOARD_SCHEMA, leverage.SCHEMA)

TIMEOUT = 60


def _session():
    s = requests.Session()
    s.headers.update({"User-Agent": "jsa-livestock-portal/market-board"})
    return s


def _err(e) -> dict:
    return {"error": f"{type(e).__name__}: {e}"}


# ── LMR: the packer-position block ───────────────────────────────────────────

@st.cache_data(ttl=3600, show_spinner=False)  # LM_CT153 publishes Monday for the prior week
def load_leverage(_schema=SCHEMA) -> dict:
    """
    The purchase mix, forward book, committed inventory and delivery schedule.

    Five concurrent section GETs against two slugs, ~3 s and ~6 MB for the full
    history of each. `leverage.load` takes a session FACTORY rather than making
    its own, which is why this page can supply one and add no global state.

    SECTIONS ARE A PATH SEGMENT, not a query parameter -- `leverage` handles
    that, and the bare slug would answer 200 with a near-empty row rather than
    an error.
    """
    try:
        frames = leverage.load(_session)
        if frames.get("mix") is None or frames["mix"].empty:
            return {"error": "LM_CT153 returned no purchase-mix rows"}
        out = {
            "frames": frames,
            "latest": leverage.latest(frames),
            "need": leverage.cash_need(frames["mix"]),
            "near": leverage.near_months(frames["schedule"], 3),
            "accuracy": leverage.need_accuracy(frames["mix"]),
        }
        # The audit USDA gives for free: the sixteen monthly totals must sum to
        # the published book figure exactly. If the row layout ever shifts, this
        # stops matching instead of quietly mis-attributing a month.
        book = out["latest"].get("forward", {}).get("fwd_book")
        out["book_reconciles"] = (
            bool(leverage.reconciles(frames["schedule"], book))
            if book is not None else None)
        return out
    except Exception as e:                      # noqa: BLE001
        return _err(e)


@st.cache_data(ttl=3600, show_spinner=False)  # LM_CT150 is weekly
def load_weights(_schema=SCHEMA) -> dict:
    """
    Head-weighted 5-Area live and dressed weight, and this week against trend.

    ONE CT150 /History CAPTURE, not two. An earlier design had this fetched
    separately from the cash price, which would let the price tile and the
    weight tile on one screen describe different weeks after a Monday
    publication -- two correct numbers, one wrong picture, nothing raising.
    The cash tiles read `letter.sources.fetch_cash_trade`, which is a different
    capture; so the WEIGHT is the only thing taken from here and the two never
    appear in one computed figure.
    """
    try:
        got = leverage.fetch(_session, [("price", CT150_ID, "History")])
        rows = got.get("price") or []
        if not rows:
            return {"error": "LM_CT150 /History returned no rows"}
        df = pd.DataFrame(rows)
        for col in ("head_count", "weight_range_avg"):
            if col in df:
                df[col] = pd.to_numeric(
                    df[col].astype(str).str.replace(",", "", regex=False),
                    errors="coerce")
        if "report_date" in df:
            df["report_date"] = pd.to_datetime(df["report_date"], errors="coerce")
        frame = leverage.weight_frame(df)
        if frame.empty:
            return {"error": "no weekly weighted-average weights in LM_CT150"}
        return {"live": leverage.weight_context(frame, "Live"),
                "dressed": leverage.weight_context(frame, "Dressed")}
    except Exception as e:                      # noqa: BLE001
        return _err(e)


# ── the letter's own read-only fetchers ──────────────────────────────────────

@st.cache_data(ttl=900, show_spinner=False)  # LM_XB403 prints every afternoon
def load_cutout(_schema=SCHEMA) -> dict:
    try:
        return sources.fetch_cutout() or {"error": "no cutout returned"}
    except Exception as e:                      # noqa: BLE001
        return _err(e)


@st.cache_data(ttl=3600, show_spinner=False)  # LM_CT150/154 are weekly
def load_cash(_schema=SCHEMA) -> dict:
    try:
        return sources.fetch_cash_trade() or {"error": "no cash trade returned"}
    except Exception as e:                      # noqa: BLE001
        return _err(e)


@st.cache_data(ttl=3600, show_spinner=False)  # SJ_LS712 is weekly
def load_slaughter(_schema=SCHEMA) -> dict:
    try:
        return sources.fetch_slaughter() or {"error": "no slaughter returned"}
    except Exception as e:                      # noqa: BLE001
        return _err(e)


@st.cache_data(ttl=900, show_spinner=False)  # the index moves daily
def load_fci(_schema=SCHEMA) -> dict:
    """
    The feeder index, headlined on the date CME will print NEXT.

    NOT `MAX(report_date)`. The newest row is always the least complete -- on a
    Monday it can hold one Saturday auction -- so `index_dates` picks the first
    business day after CME's last published file, and `fetch_feeder_index`
    applies it. CME's published value wins for any date it covers; ours is the
    estimate for the day it has not printed yet.
    """
    try:
        return sources.fetch_feeder_index() or {"error": "no feeder index returned"}
    except Exception as e:                      # noqa: BLE001
        return _err(e)


# ── Snowflake ────────────────────────────────────────────────────────────────

@st.cache_data(ttl=1800, show_spinner=False)  # basis snapshots land through the day
def load_corn(_schema=SCHEMA) -> dict:
    """
    Delivered corn by feeding state -- the cost side of every feeder bid.

    DELIVERED, NOT AN ELEVATOR BID. Measured on the one region where AMS
    publishes both, the spread is 86c/bu, which at an 80% ration and 6.5:1
    conversion is about $52 a head over 650 lb of gain. Feeding a bid into a
    cost-of-gain calculation understates corn by that much, silently.
    """
    try:
        conn = corn_cost.db.get_conn()
        try:
            out = corn_cost.delivered_corn(conn, days=10)
        finally:
            conn.close()
        return out or {"error": "no delivered corn returned"}
    except Exception as e:                      # noqa: BLE001
        return _err(e)


# ── the bundle ───────────────────────────────────────────────────────────────

def bundle(today: date | None = None) -> dict:
    """
    Everything the registry picks from, plus the errors, in one dict.

    ERRORS ARE COLLECTED, NEVER RAISED. `errors` maps a block name to why it
    failed, and the freshness strip prints them. A block that fails leaves its
    signals MISSING and marked -- which is a different statement from a tile
    that quietly disappears, and CLAUDE.md is explicit that the quiet one reads
    as "nothing to report there".
    """
    # CONCURRENTLY, because they are seven independent feeds against four hosts
    # and nothing downstream needs one before another. Measured cold on
    # 2026-10-07: 32.5 s for leverage, 12.0 fci, 8.1 cash, 6.3 weights, 5.1
    # cutout, 3.1 corn, 2.1 slaughter -- 69 s in sequence against about 33
    # concurrent, which is the difference between a page you wait for and one
    # you abandon. Each is separately cached on its own feed's cadence, so this
    # cost is paid once an hour for the weekly blocks rather than per view.
    with ThreadPoolExecutor(max_workers=7) as ex:
        jobs = {k: ex.submit(f) for k, f in (
            ("lev", load_leverage), ("weights", load_weights),
            ("cutout", load_cutout), ("cash", load_cash),
            ("slaughter", load_slaughter), ("fci", load_fci),
            ("corn", load_corn))}
        # A thread that raises must not take the page down, so the result is
        # collected the same way a failed fetch is: as an error dict.
        done = {}
        for k, fut in jobs.items():
            try:
                done[k] = fut.result()
            except Exception as e:                  # noqa: BLE001
                done[k] = _err(e)
    lev, weights = done["lev"], done["weights"]
    cutout, cash = done["cutout"], done["cash"]
    slaughter, fci, corn = done["slaughter"], done["fci"], done["corn"]

    errors = {}
    for name, blk in (("packer leverage (LM_CT153/142)", lev),
                      ("carcass weights (LM_CT150)", weights),
                      ("boxed beef (LM_XB403)", cutout),
                      ("cash trade (LM_CT150/154)", cash),
                      ("weekly slaughter (SJ_LS712)", slaughter),
                      ("feeder index (Snowflake)", fci),
                      ("delivered corn (Snowflake)", corn)):
        if isinstance(blk, dict) and blk.get("error"):
            errors[name] = blk["error"]

    return {
        "lev": (lev.get("latest") or {}),
        "frames": (lev.get("frames") or {}),
        "need": (lev.get("need") or {}),
        "near": (lev.get("near") or {}),
        "accuracy": (lev.get("accuracy") or {}),
        "book_reconciles": lev.get("book_reconciles"),
        "weight": (weights.get("live") or {}),
        "weight_dressed": (weights.get("dressed") or {}),
        "cutout": cutout if not cutout.get("error") else {},
        "cash": cash if not cash.get("error") else {},
        "slaughter": slaughter if not slaughter.get("error") else {},
        "fci": fci if not fci.get("error") else {},
        "corn": corn if not corn.get("error") else {},
        # Corn rows carry no observation date of their own -- the query window
        # is "the last ten days" -- so the as-of is the run, and the tile says
        # so rather than implying a quote date it does not have.
        "asof": {"corn": (today or date.today()) if not corn.get("error") else None},
        "errors": errors,
    }
