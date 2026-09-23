"""
Every number the Tuesday letter prints, fetched from the same source the
matching dashboard uses.

WHY THE REPORT IDS ARE REPEATED HERE. The dashboards are Streamlit scripts:
apps/cash_trade/app.py and friends call st.markdown() at module scope, so
importing them to borrow a fetcher would execute a page. The constants below
are therefore copied, not imported -- and tests/test_letter_drift.py reads the
app files and asserts every one of them still agrees, so a dashboard changing
report IDs breaks the test instead of silently sending stale numbers to clients.

The two modules that ARE import-safe get imported rather than copied:
apps/livestock_seasonal/massive_api.py (no streamlit) and
apps/cme_feeder_cattle/snowflake_db.py (loaded under a private name -- see
_load_fci_db for why that matters).
"""
from __future__ import annotations

import importlib.util
import io
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

REPO = Path(__file__).resolve().parent.parent
APPS = REPO / "apps"

# -- AMS LMR: mirrored from the dashboards (see module docstring) -------------
LMR_BASE = "https://mpr.datamart.ams.usda.gov/services/v1.1/reports"

CT150_ID = 2477    # apps/cash_trade/app.py  -- 5-Area Weekly Weighted Average Direct Slaughter Cattle
CT154_ID = 2481    # apps/cash_trade/app.py  -- National Weekly Direct Slaughter Cattle, Negotiated
XB403_ID = 2453    # apps/beef_cutout/app.py -- National Daily Boxed Beef Cutout PM
GRADING_ID = 2700  # apps/beef_cutout/app.py -- National Weekly Fed Cattle Comprehensive
AMS_SJ_LS712 = "https://www.ams.usda.gov/mnreports/sj_ls712.txt"

# AMS report 3208, "Daily Livestock and Poultry Slaughter" -- the source of the
# letter's daily and week-to-date bullets. Published as a PDF at a stable path
# that needs no API key. Also available through MyMarketNews as report 3208 if a
# structured feed is ever wanted; the PDF is used because it costs no secret.
AMS_3208_PDF = "https://www.ams.usda.gov/mnreports/ams_3208.pdf"


def _session(backoff: float = 1.5) -> requests.Session:
    s = requests.Session()
    retry = Retry(total=3, backoff_factor=backoff,
                  status_forcelist=[429, 500, 502, 503, 504], allowed_methods=["GET"])
    s.mount("https://", HTTPAdapter(max_retries=retry))
    return s


def _num(x):
    """AMS ships numbers as strings with commas and the odd stray percent sign."""
    try:
        return float(str(x).replace(",", "").replace("%", "").strip())
    except (TypeError, ValueError):
        return None


# -- Futures ------------------------------------------------------------------

def _massive():
    sys.path.insert(0, str(APPS / "livestock_seasonal"))
    import massive_api
    return massive_api


_MONTHS = {"F": "Jan", "G": "Feb", "H": "Mar", "J": "Apr", "K": "May", "M": "Jun",
           "N": "Jul", "Q": "Aug", "U": "Sep", "V": "Oct", "X": "Nov", "Z": "Dec"}


def contract_month(ticker: str) -> str:
    """LEV6 -> 'Oct'. The letter labels contracts by month alone."""
    m = re.match(r"^[A-Z]{1,3}([FGHJKMNQUVXZ])\d$", ticker)
    return _MONTHS.get(m.group(1), ticker) if m else ticker


def fetch_futures(product_code: str, api_key: str, as_of: date, n: int = 3) -> list[dict]:
    """
    Front n outright contracts: last settle plus both candidate net changes.

    Returns settle, change_day (previous session) and change_week (the last
    settle on or before the prior Friday) for each contract. Both are carried
    because which one the letter quotes is still unconfirmed -- see
    config.CHANGE_BASIS.
    """
    api = _massive()
    contracts = api.get_active_contract_tickers(product_code, api_key, as_of)[:n]
    tickers = [c["ticker"] for c in contracts]
    hist = api.get_settlement_histories(tickers, api_key)

    # The most recent Friday strictly before as_of. A letter written ON a Friday
    # should compare against the PREVIOUS Friday, not itself, hence the "or 7".
    prior_friday = as_of - timedelta(days=(as_of.weekday() - 4) % 7 or 7)

    out = []
    for c in contracts:
        s = hist.get(c["ticker"], pd.Series(dtype=float)).dropna()
        # CLIP TO as_of. Without this the settle is always the NEWEST bar, so a
        # letter rebuilt for an earlier date silently carries today's prices --
        # and a stored letter stops being a record of what it printed.
        s = s[s.index <= as_of]
        if s.empty:
            continue
        settle = float(s.iloc[-1])
        prev = float(s.iloc[-2]) if len(s) > 1 else None

        # THE PRIOR FRIDAY'S BAR MUST EXIST. Reaching further back when it is
        # missing is what made this quietly wrong: on 2026-09-22 the Massive
        # history had no bars at all for 09-14..09-18, so the "week" change fell
        # through to 09-11 and computed -0.90 where the letter's own arithmetic
        # (218.775 - 215.925) gives +2.85. A wrong number that looks right is
        # worse than a marked gap, so a missing base yields None.
        base_week = float(s.loc[prior_friday]) if prior_friday in s.index else None

        last_date = s.index[-1]
        out.append({
            "ticker": c["ticker"],
            "month": contract_month(c["ticker"]),
            "settle": settle,
            "settle_date": last_date.isoformat() if hasattr(last_date, "isoformat") else str(last_date),
            "change_day": round(settle - prev, 4) if prev is not None else None,
            "change_week": round(settle - base_week, 4) if base_week is not None else None,
            "week_base_date": prior_friday.isoformat(),
            "week_base_missing": base_week is None,
            "gaps": [d.isoformat() for d in session_gaps(s.index, prior_friday, as_of)],
        })
    return out


def session_gaps(index, start: date, end: date) -> list:
    """
    Weekdays with no bar between start and end, reported only in RUNS OF TWO OR
    MORE.

    A single missing weekday is almost always an exchange holiday -- 2026-09-07
    was Labor Day and the series steps 09-04 to 09-08. A run of them is a data
    gap, and the 09-14..09-18 hole is what corrupted both the weekly change and
    the moving averages without raising anything.
    """
    have = {d for d in index}
    missing, d = [], start
    while d <= end:
        if d.weekday() < 5 and d not in have:
            missing.append(d)
        d += timedelta(days=1)

    runs, run = [], []
    for d in missing:
        if run and (d - run[-1]).days <= 3:
            run.append(d)
        else:
            if len(run) >= 2:
                runs.extend(run)
            run = [d]
    if len(run) >= 2:
        runs.extend(run)
    return runs


def fetch_settlement_series(ticker: str, api_key: str) -> pd.Series:
    """Daily settles for one contract -- what the moving averages are built on."""
    return _massive().get_settlement_history(ticker, api_key)


# -- Cash trade: LM_CT150 weighted averages + LM_CT154 negotiated volume ------

def fetch_cash_trade() -> dict:
    """
    The five "last week's cash trade" bullets.

    USDA publishes this week's and last week's figures in the SAME report, so
    the week-ago comparison is read straight out rather than stored and diffed
    here -- there is no history to keep and nothing to drift.
    """
    sess = _session()

    r = sess.get(f"{LMR_BASE}/{CT150_ID}/History", timeout=120)
    r.raise_for_status()
    price = pd.DataFrame(r.json().get("results", []))

    out: dict = {"live": {}, "dressed": {}, "volume": {}, "report_date": None}

    if not price.empty:
        price["report_date"] = pd.to_datetime(price["report_date"], format="%m/%d/%Y", errors="coerce")
        for col in ("head_count", "weighted_avg_price"):
            price[col] = pd.to_numeric(
                price[col].astype(str).str.replace(",", "", regex=False), errors="coerce")
        price = price.dropna(subset=["report_date"])
        latest = price["report_date"].max()
        cur = price[price["report_date"] == latest]
        out["report_date"] = latest.date().isoformat()

        # Steer and Heifer are published separately; the letter quotes one
        # number, so combine head-count-weighted exactly as the dashboard does.
        for basis, key in (("Live", "live"), ("Dressed", "dressed")):
            for period, label in (("WEEKLY WEIGHTED AVERAGES", "this_week"),
                                  ("SAME PERIOD LAST WEEK", "last_week")):
                rows = cur[(cur["selling_basis_desc"] == basis) &
                           (cur["current_period"] == period)]
                rows = rows.dropna(subset=["head_count", "weighted_avg_price"])
                if rows.empty or rows["head_count"].sum() == 0:
                    out[key][label] = None
                    continue
                out[key][label] = round(
                    float((rows["head_count"] * rows["weighted_avg_price"]).sum()
                          / rows["head_count"].sum()), 2)

    r = sess.get(f"{LMR_BASE}/{CT154_ID}", timeout=60)
    r.raise_for_status()
    vol = pd.DataFrame(r.json().get("results", []))
    if not vol.empty:
        vol["report_date"] = pd.to_datetime(vol["report_date"], format="%m/%d/%Y", errors="coerce")
        vol = vol.dropna(subset=["report_date"]).sort_values("report_date")
        v = vol.iloc[-1]
        # _1 / _2 are USDA's suffixes for the 1-14 and 15-30 day delivery windows.
        out["volume"] = {
            "confirmed": _num(v.get("total_head_count")),
            "confirmed_last_week": _num(v.get("head_count_week_ago")),
            "d14": _num(v.get("total_head_count_1")),
            "d14_last_week": _num(v.get("head_count_week_ago_1")),
            "d30": _num(v.get("total_head_count_2")),
            "d30_last_week": _num(v.get("head_count_week_ago_2")),
            "report_date": v["report_date"].date().isoformat(),
        }
    return out


# -- Boxed beef: LM_XB403 cutout + LSWFEDCC grading ---------------------------

def fetch_cutout() -> dict:
    """Choice/Select PM cutout, the session change, 5-day averages, grading %."""
    sess = _session()
    r = sess.get(f"{LMR_BASE}/{XB403_ID}/",
                 params={"lastReports": 30, "allSections": "true"}, timeout=60)
    r.raise_for_status()
    payload = r.json()
    sections = {}
    for sec in (payload if isinstance(payload, list) else [payload]):
        if sec.get("results"):
            df = pd.DataFrame(sec["results"])
            df["report_date"] = pd.to_datetime(df["report_date"], errors="coerce")
            sections[sec.get("reportSection", "")] = (
                df.dropna(subset=["report_date"]).sort_values("report_date"))

    cut = sections.get("Current Cutout Values", pd.DataFrame())
    out: dict = {}
    if not cut.empty:
        cut = cut.copy()
        cut["choice"] = pd.to_numeric(cut.get("choice_600_900_current"), errors="coerce")
        cut["select"] = pd.to_numeric(cut.get("select_600_900_current"), errors="coerce")
        for key in ("choice", "select"):
            s = cut[cut[key].notna()]
            if s.empty:
                continue
            cur = float(s.iloc[-1][key])
            prev = float(s.iloc[-2][key]) if len(s) > 1 else None
            out[key] = {
                "value": round(cur, 2),
                "change": round(cur - prev, 2) if prev is not None else None,
                # The letter quotes a 5-day average -- the trailing business week.
                "avg5": round(float(s[key].tail(5).mean()), 2) if len(s) >= 5 else None,
            }
        out["report_date"] = cut["report_date"].max().date().isoformat()

    r = sess.get(f"{LMR_BASE}/{GRADING_ID}/",
                 params={"lastReports": 10, "allSections": "true"}, timeout=60)
    r.raise_for_status()
    payload = r.json()
    for sec in (payload if isinstance(payload, list) else [payload]):
        if sec.get("reportSection") == "Weekly Fed Cattle Comprehensive":
            g = pd.DataFrame(sec["results"])
            g["report_date"] = pd.to_datetime(g["report_date"], errors="coerce")
            g["pct"] = pd.to_numeric(g.get("Pct_Choice_CW"), errors="coerce")
            g = g.dropna(subset=["report_date", "pct"]).sort_values("report_date")
            if not g.empty:
                out["grading"] = {
                    "pct": round(float(g.iloc[-1]["pct"]), 1),
                    "pct_last_week": round(float(g.iloc[-2]["pct"]), 1) if len(g) > 1 else None,
                    "report_date": g.iloc[-1]["report_date"].date().isoformat(),
                }
            break
    return out


# -- Slaughter and carcass weights: AMS SJ_LS712 ------------------------------

def _parse_ls712_date(s: str):
    for fmt in ("%d-%b-%y", "%d-%b-%Y"):
        try:
            return datetime.strptime(s.strip(), fmt).date()
        except ValueError:
            pass
    return None


def parse_3208(text: str) -> dict:
    """
    Pull the Cattle row out of AMS report 3208's extracted text.

    The report has two blocks -- Current Day and Previous Day -- each a table of
    species rows. Both contain a "Cattle" line, and the FIRST is the current
    day, which is the one the letter quotes. A third "Cattle" appears in the
    Previous Day Breakdown (Steers/Heifers, Cows/Bulls) and is skipped because
    it is reached only after nine numbers have already been collected.

    Columns, in the order they extract:

        current_day, day_week_ago, day_year_ago,
        wtd, wtd_week_ago, wtd_year_ago,
        ytd, ytd_prev_year, ytd_pct_change

    Verified against the 9/15/26 letter: the 9/22 report's day_week_ago (108,000)
    and wtd_week_ago (211,000) are exactly what that letter printed as its own
    daily and WTD figures.

    A bare "R" between values marks a revised figure and is skipped -- it is a
    footnote, not a column, and treating it as one would shift everything after
    it by a place.
    """
    lines = [ln.strip() for ln in text.splitlines()]
    try:
        start = lines.index("Cattle")
    except ValueError:
        return {}

    vals = []
    for ln in lines[start + 1:]:
        if ln == "R":
            continue
        try:
            vals.append(float(ln.replace(",", "").replace("%", "")))
        except ValueError:
            break
        if len(vals) == 9:
            break

    if len(vals) < 9:
        return {}

    keys = ["current_day", "day_week_ago", "day_year_ago",
            "wtd", "wtd_week_ago", "wtd_year_ago",
            "ytd", "ytd_prev_year", "ytd_pct_change"]
    out = dict(zip(keys, vals))

    m = re.search(r"Report for (\w+ \d+, \d{4})\s*-\s*(\w+)", text)
    if m:
        try:
            out["report_date"] = datetime.strptime(m.group(1), "%B %d, %Y").date().isoformat()
        except ValueError:
            pass
        # "Final" or "Preliminary". An early-afternoon run can catch a
        # preliminary print, and the letter should not quote one unknowingly.
        out["status"] = m.group(2)
    return out


def fetch_daily_slaughter() -> dict:
    """Daily and week-to-date cattle slaughter from AMS report 3208."""
    from pypdf import PdfReader

    r = _session().get(AMS_3208_PDF, timeout=40)
    r.raise_for_status()
    reader = PdfReader(io.BytesIO(r.content))
    text = "\n".join(p.extract_text() or "" for p in reader.pages)
    return parse_3208(text)


# -- Carcass weights: AMS MARS report 3658 -----------------------------------
# The SAME source the Cattle Weights dashboard uses, which is where Ross reads
# this figure. Mirrored from apps/beef_weight/app.py (see module docstring) and
# guarded by tests/test_letter_drift.py.
#
# Deliberately NOT the "Average Weights" table in SJ_LS712. That table carries
# USDA's weekly ESTIMATE and reads 889# where 3658's actual for the week Ross
# was quoting read 887#. Two defensible numbers, but only one is the series the
# letter has been printing, and quietly swapping series is how a letter starts
# disagreeing with the dashboard it is supposed to summarise.
MARS_BASE = "https://marsapi.ams.usda.gov/services/v1.2/reports"
FIS_REPORT_ID = 3658
# A PATH SEGMENT, NOT A QUERY PARAM -- "?section=" is accepted, ignored, and
# returns the header with zero rows and HTTP 200.
FIS_SECTION = "Report FIS Meat Production"


def fetch_carcass_weights() -> dict:
    """
    Weekly actual FIS dressed weight for the Cattle class, from AMS MARS 3658.

    Published Thursday, covering the week that ended about twelve days earlier,
    so on a Tuesday the newest row is roughly a fortnight old. That lag is the
    series behaving normally, not a stale fetch.

    Needs MARS_API_KEY -- the same secret Beef Trimmings already uses, so no new
    credential. Returns {} with an error key rather than raising.
    """
    from urllib.parse import quote

    import os
    key = (os.environ.get("MARS_API_KEY") or "").strip()
    if not key:
        return {"error": "MARS_API_KEY not configured"}

    r = _session().get(f"{MARS_BASE}/{FIS_REPORT_ID}/{quote(FIS_SECTION)}",
                       auth=(key, ""), timeout=(5, 120))
    if r.status_code in (204, 404):
        return {"error": f"AMS returned HTTP {r.status_code}"}
    r.raise_for_status()

    rows = []
    for x in r.json().get("results", []):
        if str(x.get("commodity", "")).strip() != "Slaughter Cattle":
            continue
        if str(x.get("description", "")).strip() != "Dressed Weight":
            continue
        if str(x.get("class", "")).strip() != "Cattle":
            continue
        # Unit guard, as in the dashboard: a silent unit rename would land as a
        # plausible wrong number rather than an error.
        if str(x.get("unit", "")).strip().lower() != "lbs":
            continue
        # 3658 has NO report_date field. The END date is the week ending.
        wk = x.get("report_end_date") or x.get("report_begin_date")
        val = _num(x.get("volume"))
        if not wk or val is None:
            continue
        try:
            d = datetime.strptime(str(wk).split()[0], "%m/%d/%Y").date()
        except ValueError:
            continue
        rows.append((d, val))

    if not rows:
        return {"error": "no Slaughter Cattle / Dressed Weight rows in report 3658"}

    rows.sort()
    by_date = dict(rows)
    last = rows[-1][0]
    week_ago = last - timedelta(days=7)
    year_ago = last - timedelta(days=364)   # same weekday, 52 weeks back
    return {
        "value": by_date.get(last),
        "week_ending": last.isoformat(),
        "last_week": by_date.get(week_ago),
        "year_ago": by_date.get(year_ago),
    }


# -- CFTC Commitments of Traders ---------------------------------------------
# Managed money net long for the Friday letter's CFTC block.
#
# THE VARIANT IS LOAD-BEARING. This must be the DISAGGREGATED, FUTURES-ONLY
# report. Verified against the 9/18/26 letter: futures-only gives Live Cattle
# 47,696 / -1,209 and Feeder 7,211 / -237, matching to the contract. The
# futures-and-options-combined set gives 45,262 / -1,987 and 6,701 / -81, and
# the legacy commercial/non-commercial breakdown flips Feeder Cattle to a NET
# SHORT of 3,853 -- which would invert the market read. All three return
# plausible cattle numbers, so a wrong choice here fails silently.
#
# THE DATASET ID IS ALSO LOAD-BEARING. publicreporting.cftc.gov carries a
# frozen duplicate (ubmb-6exi) last updated in 2022. It answers happily with
# four-year-old positions and no error.
CFTC_DATASET = "https://publicreporting.cftc.gov/resource/72hh-3qpy.json"
CFTC_MARKETS = {
    "057642": "Live Cattle",
    "061641": "Feeder Cattle",
}


def fetch_cftc() -> dict:
    """
    Latest managed money net long and week-on-week change for both cattle
    contracts, plus the report's as-of date.

    Net long is long minus short. The spread column is deliberately excluded --
    including it does not reproduce the letter.

    FILTERED ON cftc_contract_market_code, NEVER ON cftc_commodity_code. The
    commodity code comes back in two whitespace variants ('057' and '057 '), so
    an equality filter on it silently drops rows.
    """
    params = {
        "$select": ("report_date_as_yyyy_mm_dd,cftc_contract_market_code,"
                    "m_money_positions_long_all,m_money_positions_short_all,"
                    "change_in_m_money_long_all,change_in_m_money_short_all"),
        "$where": "cftc_contract_market_code in('057642','061641')",
        "$order": "report_date_as_yyyy_mm_dd DESC",
        "$limit": 8,
    }
    r = _session().get(CFTC_DATASET, params=params, timeout=60)
    r.raise_for_status()
    rows = r.json()
    if not rows:
        return {}

    as_of = max(row["report_date_as_yyyy_mm_dd"] for row in rows)[:10]
    out = {"as_of": as_of, "markets": {}}
    for row in rows:
        if row["report_date_as_yyyy_mm_dd"][:10] != as_of:
            continue
        name = CFTC_MARKETS.get(row["cftc_contract_market_code"])
        if not name:
            continue
        long_, short = int(row["m_money_positions_long_all"]), int(row["m_money_positions_short_all"])
        d_long = int(row["change_in_m_money_long_all"])
        d_short = int(row["change_in_m_money_short_all"])
        out["markets"][name] = {"net_long": long_ - short, "wow": d_long - d_short}
    return out


def cftc_is_current(cftc: dict, issue: date) -> bool:
    """
    True when the fetched report is the one for the issue's own week.

    THE TIMING TRAP. CFTC releases Friday at 3:30pm ET, as-of the Tuesday three
    days earlier. A Friday letter built before 3:30 gets LAST week's report with
    no error at all -- correct-looking positions that are a week stale. Callers
    warn on False rather than printing it silently.
    """
    as_of = cftc.get("as_of")
    if not as_of:
        return False
    tuesday = issue - timedelta(days=(issue.weekday() - 1) % 7)
    return as_of == tuesday.isoformat()


# -- Regional cash cattle trade ----------------------------------------------
# The Friday letter's "Cash Cattle Trade" block: North and South negotiated
# ranges. AMS has no north/south field, so the regions are assembled from the
# per-state daily reports -- North being Nebraska plus the Western Cornbelt.
#
# Verified against 9/18/26: min low / max high of LIVE FOB across NE and IA-MN,
# restricted to STEER and HEIFER, gives 220.00-222.50, exactly the letter's
# "North: 220-222.50 FOB live".
#
# THE CLASS FILTER IS NOT COSMETIC. Including MIXED STEER/HEIFER or the
# ALL BEEF TYPE rollup widens it to 218.00-222.50, and DAIRYBRED rows drag the
# dressed range down to 320.00.
CASH_REGIONS = {
    "North": {2667: "Nebraska", 2671: "Iowa/Minnesota"},
    "South": {2663: "TX/OK/NM", 2665: "Kansas"},
}
CASH_CLASSES = ("STEER", "HEIFER")


def _cash_rows(slug: int, on: date) -> list:
    """
    Detail rows for one region on one day, or [] when nothing was published.

    AMS ANSWERS 200 WITH A BARE JSON STRING when a date has no report -- not an
    error status, not an empty list, not an object with zero results. Iterating
    that as sections walks its CHARACTERS and dies on str.get, which is how a
    perfectly ordinary "no trade that day" took the whole section down. Every
    shape other than the documented one is treated as no rows.
    """
    r = _session().get(f"{LMR_BASE}/{slug}/Detail",
                       params={"q": f"report_date={on.strftime('%m/%d/%Y')}"}, timeout=60)
    if r.status_code in (204, 404):
        return []
    r.raise_for_status()
    try:
        payload = r.json()
    except ValueError:
        return []

    if isinstance(payload, dict):
        results = payload.get("results")
        return results if isinstance(results, list) else []
    if isinstance(payload, list):
        out = []
        for sec in payload:
            if isinstance(sec, dict) and isinstance(sec.get("results"), list):
                out.extend(sec["results"])
        return out
    return []


# The same daily reports, kept flat and abbreviated the way the morning brief
# names them -- "NE 221.00-222.50 live, 350 dressed" rather than a North/South
# rollup. The evening letter still wants the rollup; this is a different read of
# the same four slugs.
# THE SUMMARY REPORTS, NOT THE AFTERNOON ONES -- and the difference is not
# cosmetic. Nebraska on Monday 2026-09-21: the Afternoon report carried ZERO
# priced rows while the Summary carried nine, so a week-to-date built on
# Afternoon silently dropped Nebraska from a week it had traded.
#
# The evening letter still uses the Afternoon reports, deliberately. Written on
# a Friday evening, that is the latest print available, and it is what Ross
# quoted: 9/18 Afternoon gives the letter's 220-222.50, while the Summary for
# the same day runs to 224.00 because it includes trade confirmed later. Same
# day, two honest answers to two different questions -- "what is out now" and
# "what did the day finally do".
CASH_STATES = [(2668, "NE"), (2672, "IA/MN"), (2664, "TX/OK/NM"), (2666, "KS")]


def fetch_regional_cash_wtd(as_of: date) -> dict:
    """
    Week-to-date negotiated cash by state, Monday through as_of.

    A single day is the wrong window for a morning brief: Monday is routinely
    untested, so a Tuesday brief built from Monday alone says "no established
    test" while the week has in fact traded. Ranges span every priced day of the
    week so far, and `days` records how many actually carried a price.

    Same class filter as the evening letter -- STEER and HEIFER only. Adding
    MIXED or the ALL BEEF TYPE rollup widens the range, and DAIRYBRED drags
    dressed down.
    """
    monday = as_of - timedelta(days=as_of.weekday())
    span = [monday + timedelta(days=i) for i in range((as_of - monday).days + 1)
            if (monday + timedelta(days=i)).weekday() < 5]

    out = {"from": monday.isoformat(), "to": as_of.isoformat(), "regions": {}}
    for slug, label in CASH_STATES:
        live_lo, live_hi, dr_lo, dr_hi, head, days = [], [], [], [], 0.0, set()
        for day in span:
            for row in _cash_rows(slug, day):
                if str(row.get("purchase_type_code", "")).strip() != "NEGOTIATED CASH":
                    continue
                if str(row.get("class_desc", "")).strip() not in CASH_CLASSES:
                    continue
                lo, hi = _num(row.get("price_range_low")), _num(row.get("price_range_high"))
                if lo is None or hi is None:
                    continue
                basis = str(row.get("selling_basis_desc", "")).strip()
                if basis == "LIVE FOB":
                    live_lo.append(lo); live_hi.append(hi)
                    head += _num(row.get("head_count")) or 0
                    days.add(day)
                elif basis.startswith("DRESSED"):
                    dr_lo.append(lo); dr_hi.append(hi)
                    days.add(day)
        out["regions"][label] = {
            "live_low": min(live_lo) if live_lo else None,
            "live_high": max(live_hi) if live_hi else None,
            "dressed_low": min(dr_lo) if dr_lo else None,
            "dressed_high": max(dr_hi) if dr_hi else None,
            "head": int(head) or None,
            "days": len(days),
            "undefined": not live_lo and not dr_lo,
        }
    return out


def fetch_regional_cash(on: date) -> dict:
    """
    North and South negotiated ranges for one trading day.

    A region with no priced rows is reported as undefined, which is USDA's own
    state when there is not enough confirmed trade for a market test -- and is
    what the letter prints as "South: Undefined". That is a real answer, not a
    fetch failure, so it is represented explicitly rather than as a gap.
    """
    out: dict = {"date": on.isoformat(), "regions": {}}
    for region, slugs in CASH_REGIONS.items():
        live_lows, live_highs, dressed_lows, dressed_highs, head = [], [], [], [], 0
        for slug in slugs:
            for row in _cash_rows(slug, on):
                if str(row.get("purchase_type_code", "")).strip() != "NEGOTIATED CASH":
                    continue
                if str(row.get("class_desc", "")).strip() not in CASH_CLASSES:
                    continue
                lo, hi = _num(row.get("price_range_low")), _num(row.get("price_range_high"))
                if lo is None or hi is None:
                    continue
                basis = str(row.get("selling_basis_desc", "")).strip()
                hd = _num(row.get("head_count")) or 0
                if basis == "LIVE FOB":
                    live_lows.append(lo); live_highs.append(hi); head += hd
                elif basis.startswith("DRESSED"):
                    dressed_lows.append(lo); dressed_highs.append(hi)
        out["regions"][region] = {
            "live_low": min(live_lows) if live_lows else None,
            "live_high": max(live_highs) if live_highs else None,
            "dressed_low": min(dressed_lows) if dressed_lows else None,
            "dressed_high": max(dressed_highs) if dressed_highs else None,
            "head": int(head) or None,
            "undefined": not live_lows and not dressed_lows,
        }
    return out


# -- Outside markets, for the morning brief ----------------------------------
# Corn is feed cost, equities are risk appetite, crude moves both. Fetched
# through the same Massive client the Seasonal dashboard uses.
#
# THESE ARE THE ONLY ONES WITH A REAL OVERNIGHT MOVE AT 8:30am CENTRAL. CME
# livestock futures do not open until 08:30 CT, so there is no overnight cattle
# print to report -- grain and equities have traded through the night and are
# where the morning signal actually is. Dollar Index is deliberately absent:
# Massive returns no contracts for DX.
# "eighths" quotes in whole cents and eighths -- 531.25 prints as 531'2, the way
# the grain trade writes it and the way Ross writes it ("5'4 lower at 531'2").
# Corn, wheat, oats and soybeans trade in eighths; meal, equities and crude are
# plain decimals.
OUTSIDE_MARKETS = [
    ("ZC", "Corn", "eighths"),
    ("ES", "S&P", "decimal"),
    ("CL", "Crude", "decimal"),
]


def front_contracts(product_code: str, api_key: str, as_of: date, n: int = 1) -> list:
    """
    The n nearest outright contracts, following /contracts pagination.

    massive_api.get_active_contract_tickers() reads ONE page. That is fine for
    cattle and corn, whose listings are mostly outrights, and silently wrong for
    crude: CL's page is dominated by spread and butterfly combos, the response
    caps at 1000 rows, and the near months fall off the end. On 2026-09-23 it
    returned six CL outrights, all January and February, so the brief quoted
    CLF7 at 86.85 while the actual front month CLX6 was 91.94 -- five dollars
    away, with nothing to show anything was wrong.

    Following next_url fixes it without touching the shared dashboard module.
    """
    api = _massive()
    seen, url, params = {}, "/contracts", {
        "product_code": product_code, "active": "true",
        "date": as_of.isoformat(), "limit": 1000,
    }
    for _ in range(12):                      # bounded: a runaway feed cannot hang a build
        data = api._get(url, api_key, params=params) if params else api._get(url, api_key)
        for r in data.get("results", []):
            ticker = r.get("ticker", "")
            if not api._is_outright_ticker(ticker, product_code):
                continue
            when = r.get("settlement_date") or r.get("last_trade_date")
            if when:
                seen.setdefault(ticker, when)
        nxt = data.get("next_url")
        if not nxt:
            break
        # next_url is absolute; strip the base so _get can prepend it again.
        url, params = nxt.replace(api.BASE_URL, ""), None

    rows = [{"ticker": t, "expiration": w} for t, w in seen.items()]
    rows.sort(key=lambda r: r["expiration"])
    live = [r for r in rows if str(r["expiration"])[:10] >= as_of.isoformat()]
    return (live or rows)[:n]


def fetch_outside_markets(api_key: str, as_of: date) -> list:
    """
    Front-month price and overnight change for each outside market.

    THE CHANGE COMES FROM THE SNAPSHOT'S OWN session.previous_settlement, not
    from differencing the settlement history. The history's newest bar is TODAY'S
    own in-progress session, so subtracting it gave corn -0.25 where the real
    overnight move was -9.00 against a 536.75 prior settle. Massive already
    carries both the base and the change; computing it again only adds a way to
    get it wrong, and it sidesteps the gaps that history has had.
    """
    api = _massive()
    out = []
    for code, label, style in OUTSIDE_MARKETS:
        row = {"code": code, "label": label, "style": style,
               "price": None, "change": None, "month": None, "ticker": None}
        try:
            contracts = front_contracts(code, api_key, as_of, n=1)
            if contracts:
                front = contracts[0]["ticker"]
                snap = api.get_snapshots([front], api_key).get(front, {})
                session = snap.get("session") or {}
                price = (session.get("settlement_price")
                         or (snap.get("last_trade") or {}).get("price")
                         or session.get("close"))
                prior = session.get("previous_settlement")
                change = session.get("change")
                if change is None and price is not None and prior:
                    change = float(price) - float(prior)
                row.update({
                    "ticker": front, "month": contract_month(front),
                    "price": round(float(price), 4) if price else None,
                    "prior_settle": round(float(prior), 4) if prior else None,
                    "change": round(float(change), 4) if change is not None else None,
                })
        except Exception:
            pass
        out.append(row)
    return out


# -- USDA release calendar ----------------------------------------------------
# What prints today. The highest value-per-second line in a morning brief: it
# says what to be ready for. Same ESMIS endpoint and publication ids the
# Seasonal dashboard uses for its report vlines.
ESMIS_BASE = "https://esmis.nal.usda.gov/api/v1"

# THE MONTHLY REPORTS ONLY. Weekly rhythms -- carcass weights, CFTC, weekly
# meat production -- are deliberately absent: they recur on the same weekday
# every week, so listing them is a line the reader already knows and skips, and
# in a three-minute brief that costs more than it gives.
#
# IDS, NOT SLUGS, AND CHECKED. Several near-misses exist: "Cold Storage Annual
# Summary" (1190) and "Weekly Cold Storage Holdings" (1867) are not "Cold
# Storage" (2111), and "Historical Track Record - Grain Stocks" (58) is not
# "Grain Stocks" (1480). The web slugs are not guessable either -- Cattle on
# Feed lives at /publication/cattle-feed, not /cattle-on-feed.
ESMIS_PUBLICATIONS = {
    "WASDE": 1659,
    "Cattle on Feed": 2270,
    "Cold Storage": 2111,
    "Grain Stocks": 1480,
    "Crop Production": 1632,
}

# The window is the REST OF THIS MONTH, not a rolling number of days. A week is
# wrong for monthly reports -- most weeks show nothing and the section reads as
# broken -- and a fixed 45 days makes "this month" mean something different
# every morning.
#
# Late in a month that leaves little or nothing, so it rolls into the following
# month when fewer than MIN_ITEMS remain. The heading says Upcoming rather than
# naming a month, so extending it is not a contradiction.
CALENDAR_MIN_ITEMS = 2

_WD = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def fetch_report_calendar(as_of: date) -> dict:
    """
    The monthly USDA reports due between today and roughly six weeks out.

    READS upcoming_releases FROM /publication/findById. The obvious endpoint,
    /release/findByPubId, is an ARCHIVE -- it returns only releases that have
    already happened, newest first, so a forward calendar built on it comes back
    empty and looks like a bug rather than a wrong source. The publication
    record carries the scheduled dates directly, as ISO timestamps.

    Forward-looking on purpose: a WASDE or a Cattle on Feed a fortnight out
    changes how the month is traded, and a reader who first hears about it on
    the morning is hearing too late.
    """
    # End of the current month, then the end of the next, as a fallback.
    def _month_end(d):
        return (d.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)

    this_month_end = _month_end(as_of)
    horizon = _month_end(this_month_end + timedelta(days=1))
    sess = _session()
    scheduled = []

    for name, pub_id in ESMIS_PUBLICATIONS.items():
        try:
            r = sess.get(f"{ESMIS_BASE}/publication/findById/{pub_id}", timeout=25)
            r.raise_for_status()
            payload = r.json()
        except (requests.RequestException, ValueError):
            continue
        rows = payload.get("results", [payload]) if isinstance(payload, dict) else payload
        for rec in (rows if isinstance(rows, list) else [rows]):
            if not isinstance(rec, dict):
                continue
            for stamp in rec.get("upcoming_releases") or []:
                try:
                    when = pd.to_datetime(stamp)
                except (ValueError, TypeError):
                    continue
                d = when.date()
                if not (as_of <= d <= horizon):
                    continue
                # Built by hand: "%-I" is a POSIX extension and raises
                # ValueError on Windows, which is where this runs.
                hour = when.hour % 12 or 12
                ampm = "am" if when.hour < 12 else "pm"
                scheduled.append({"date": d, "name": name,
                                  "time": f"{hour}:{when.minute:02d}{ampm}"})

    # WASDE: ESMIS lists it as an active monthly publication but returns
    # upcoming_releases: [] for it -- WAOB publishes it, not NASS, and the
    # forward schedule is simply not in this feed. Rather than drop a report
    # that was explicitly asked for, it is paired with Crop Production, which
    # USDA releases in the SAME noon-ET slot.
    #
    # THE LIMIT, AND IT IS ABSENCE NOT ERROR: a paired date is right whenever it
    # appears, but WASDE also prints in months with no Crop Production release
    # (roughly December through April), and those will not show. Flagged with
    # "inferred" so the build can say so.
    if not any(r["name"] == "WASDE" for r in scheduled):
        for r in [x for x in scheduled if x["name"] == "Crop Production"]:
            scheduled.append({"date": r["date"], "name": "WASDE",
                              "time": r["time"], "inferred": True})

    scheduled.sort(key=lambda r: (r["date"], r["name"]))

    # Prefer this month alone; roll into next only when this month is thin.
    this_month = [r for r in scheduled if r["date"] <= this_month_end]
    if len(this_month) >= CALENDAR_MIN_ITEMS:
        scheduled = this_month

    return {
        "inferred": [f"{r['name']} {r['date'].isoformat()}"
                     for r in scheduled if r.get("inferred")],
        "items": [{"date": r["date"].isoformat(),
                   "label": r["name"],
                   "when": f"{_WD[r['date'].weekday()]} {r['date'].month}/{r['date'].day}, {r['time']}",
                   "is_today": r["date"] == as_of}
                  for r in scheduled],
    }


def _ls712_section(text: str, heading: str) -> list:
    """
    Split one SJ_LS712 table into classified rows.

    Every table in this report shares a layout: a week-ending row for the
    current week, one for the prior week, a "Change:" percentage row, a row for
    the same week a year ago, another "Change:", then two "<year> YTD" rows and
    a final "Change:". Rows are returned in file order as (kind, label, numbers)
    with kind one of "week", "ytd", "change", so the caller can index by
    position without re-parsing.
    """
    m = re.search(rf"{heading}(.*?)(?:----)", text, re.DOTALL)
    if not m:
        return []
    rows = []
    for line in m.group(1).splitlines():
        s = line.strip()
        if not s:
            continue
        parts = s.split()
        nums = [n for n in (_num(p) for p in parts) if n is not None]
        if s.startswith("Change:"):
            # Percentages carry a trailing % that _num already strips.
            rows.append(("change", "Change", nums))
            continue
        d = _parse_ls712_date(parts[0])
        if d:
            rows.append(("week", d.isoformat(), [n for n in (_num(p) for p in parts[1:]) if n is not None]))
        elif len(parts) >= 2 and parts[1].upper() == "YTD":
            rows.append(("ytd", parts[0], [n for n in (_num(p) for p in parts[2:]) if n is not None]))
    return rows


def _first_col(rows: list, kind: str, index: int):
    """The Cattle/Beef column is the first number in every one of these tables."""
    hits = [r for r in rows if r[0] == kind]
    if index >= len(hits) or not hits[index][2]:
        return None, None
    return hits[index][2][0], hits[index][1]


def fetch_slaughter() -> dict:
    """
    Completed-week cattle slaughter and carcass weights from AMS SJ_LS712.

    WHAT THIS REPORT IS, AND IS NOT. SJ_LS712 is "Estimated Weekly Meat
    Production Under Federal Inspection" -- published Friday, covering the week
    ending the previous Saturday. It gives the completed week, the week before,
    the same week a year ago, and year-to-date, which is exactly the
    "529,000 compared to 505,000 head LW and 559,000 LY" line and both YTD
    percentages.

    It contains NO DAILY FIGURES AT ALL -- the letter's "Daily slaughter" and
    "WTD slaughter" bullets come from AMS report 3208 instead (fetch_daily_
    slaughter), and its "Average Weights" table is NOT the carcass weight the
    letter prints either (fetch_carcass_weights, AMS 3658). What is used from
    here is the completed-week head count and the two YTD percentages.

    Recent weeks are USDA ESTIMATES; only the year-ago row is actual. The report
    says so itself and the estimate is revised the following week -- which is
    why the weights here are reference only.
    """
    r = _session().get(AMS_SJ_LS712, timeout=30)
    r.raise_for_status()
    text = r.text

    out: dict = {
        "daily": None,          # not in this report -- see docstring
        "wtd": None,            # ditto
        "weekly": {},
        "beef_production": {},
        "weights": {},
        "report_date": None,
    }

    m = re.search(r"(Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+(\w+\s+\d+,\s+\d{4})", text)
    if m:
        try:
            out["report_date"] = datetime.strptime(
                m.group(2).strip(), "%b %d, %Y").date().isoformat()
        except ValueError:
            pass

    # -- Head slaughtered -----------------------------------------------------
    rows = _ls712_section(text, r"Livestock Slaughter \(head\)")
    if rows:
        cur, cur_date = _first_col(rows, "week", 0)
        lw, _ = _first_col(rows, "week", 1)
        ly, ly_date = _first_col(rows, "week", 2)
        changes = [r[2][0] for r in rows if r[0] == "change" and r[2]]
        out["weekly"] = {
            "value": cur, "week_ending": cur_date,
            "last_week": lw, "year_ago": ly, "year_ago_week": ly_date,
            # Three Change rows in order: week on week, year on year, then YTD.
            "chg_wow_pct": changes[0] if len(changes) > 0 else None,
            "chg_yoy_pct": changes[1] if len(changes) > 1 else None,
            "ytd_chg_pct": changes[2] if len(changes) > 2 else None,
        }

    # -- Beef production ------------------------------------------------------
    rows = _ls712_section(text, r"Meat Production \(millions of pounds\)")
    if rows:
        cur, cur_date = _first_col(rows, "week", 0)
        changes = [r[2][0] for r in rows if r[0] == "change" and r[2]]
        out["beef_production"] = {
            "value": cur, "week_ending": cur_date,
            "chg_wow_pct": changes[0] if len(changes) > 0 else None,
            "chg_yoy_pct": changes[1] if len(changes) > 1 else None,
            "ytd_chg_pct": changes[2] if len(changes) > 2 else None,
        }

    # -- Average weights ------------------------------------------------------
    # Live and Dressed are two blocks under one heading, each with the same
    # three rows (current week, prior week, year ago). The block header lines
    # carry "Live:" / "Dressed:" and no date, so they switch mode without
    # contributing a row.
    m = re.search(r"Average Weights \(lbs\)(.*?)(?:----)", text, re.DOTALL)
    if m:
        mode = None
        blocks: dict = {"live": [], "dressed": []}
        for line in m.group(1).splitlines():
            s = line.strip()
            if not s:
                continue
            if re.search(r"\bLive:", s, re.IGNORECASE):
                mode = "live"
            elif re.search(r"\bDressed:", s, re.IGNORECASE):
                mode = "dressed"
            if mode is None:
                continue
            parts = s.split()
            d = _parse_ls712_date(parts[0])
            if not d:
                continue
            # Row shape: "<date> Estimate 889 217 212 56" -- skip the word.
            nums = [n for n in (_num(p) for p in parts[1:]) if n is not None]
            if nums:
                blocks[mode].append((d.isoformat(), nums[0]))
        for mode, rows_ in blocks.items():
            if rows_:
                out["weights"][mode] = {
                    "value": rows_[0][1],
                    "date": rows_[0][0],
                    "last_week": rows_[1][1] if len(rows_) > 1 else None,
                    "year_ago": rows_[2][1] if len(rows_) > 2 else None,
                }
    return out


# -- Snowflake: CME feeder cattle index, Douglas imports ----------------------

def _load_fci_db():
    """
    Load apps/cme_feeder_cattle/snowflake_db.py under a PRIVATE module name.

    CLAUDE.md records that snowflake_db.py exists five times in this repo and
    that Python caches by module NAME, so whichever page imports first wins and
    every later one silently gets that copy. This generator never runs inside
    the Streamlit process today, but naming the module "_letter_fci_db" means it
    can never join that collision if it ever does.
    """
    path = APPS / "cme_feeder_cattle" / "snowflake_db.py"
    spec = importlib.util.spec_from_file_location("_letter_fci_db", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_letter_fci_db"] = mod
    spec.loader.exec_module(mod)
    return mod


def _load_index_dates():
    """index_dates.py, under a private name -- same reasoning as _load_fci_db."""
    path = APPS / "cme_feeder_cattle" / "index_dates.py"
    spec = importlib.util.spec_from_file_location("_letter_index_dates", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_letter_index_dates"] = mod
    spec.loader.exec_module(mod)
    return mod


def fetch_feeder_index() -> dict:
    """
    JSA's OWN feeder cattle index estimate, as the dashboard headlines it.

    READS fci_daily, NOT cme_ftp_daily. fci_daily is the JSA reconstruction --
    the number the CME Feeder Cattle Index dashboard leads with and the one the
    letter should quote. cme_ftp_daily holds CME's published file and is read
    here only for its DATE, to decide which of our own estimates is the headline.

    WHICH DATE. Not MAX(report_date) -- the newest row is always the least
    complete, and on a Monday it can hold one Saturday auction and nothing else.
    The rule is the first business day after CME's last published file, which is
    index_dates.headline_index_date(), the same function the dashboard and the
    daily email use. CLAUDE.md is explicit that this must not be simplified back
    to the newest row, and the tests for it live in the cme-feeder-cattle-index
    repo.

    One consequence worth knowing: the headline follows CME's publication clock,
    so if the CME ingest breaks, this figure freezes while the rest of the letter
    keeps moving.
    """
    db = _load_fci_db()
    idx = _load_index_dates()
    conn = db.get_conn()
    try:
        ours = db.read_sql_lower(
            "SELECT report_date AS date, fci_value FROM fci_daily "
            "WHERE fci_value IS NOT NULL", conn)
        try:
            published = db.read_sql_lower("SELECT report_date AS date FROM cme_ftp_daily", conn)
        except Exception:
            # A missing CME table degrades to the newest estimate rather than
            # to nothing -- headline_index_date() handles last_published=None.
            published = pd.DataFrame(columns=["date"])
    finally:
        conn.close()

    if ours.empty:
        return {}

    ours["date"] = pd.to_datetime(ours["date"], errors="coerce")
    ours = ours.dropna(subset=["date"]).sort_values("date")
    available = {d.date() for d in ours["date"]}

    last_published = None
    if not published.empty:
        pub = pd.to_datetime(published["date"], errors="coerce").dropna()
        if not pub.empty:
            last_published = pub.max().date()

    headline = idx.headline_index_date(last_published, available)
    if headline is None:
        return {}

    row = ours[ours["date"].dt.date == headline]
    if row.empty:
        return {}
    value = float(row.iloc[0]["fci_value"])

    # Prior available date, for the day-on-day move.
    earlier = sorted(d for d in available if d < headline)
    prev_val = None
    if earlier:
        prev_row = ours[ours["date"].dt.date == earlier[-1]]
        if not prev_row.empty:
            prev_val = float(prev_row.iloc[0]["fci_value"])

    return {
        "value": round(value, 2),
        "date": headline.isoformat(),
        "change": round(value - prev_val, 2) if prev_val is not None else None,
        "source": "JSA estimate (fci_daily)",
        "cme_last_published": last_published.isoformat() if last_published else None,
    }


def fetch_douglas_ytd(year: int = None) -> dict:
    """Year-to-date feeder imports through the Douglas, AZ crossing."""
    year = year or date.today().year
    db = _load_fci_db()
    conn = db.get_conn()
    try:
        df = db.read_sql_lower(
            "SELECT report_date AS date, crossing_point, receipts_est "
            "FROM border_receipts WHERE is_total = 0", conn)
    finally:
        conn.close()
    if df.empty:
        return {"year": year, "head": None}
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"])
    df = df[df["date"].dt.year == year]
    doug = df[df["crossing_point"].astype(str).str.contains("Douglas", case=False, na=False)]
    if doug.empty:
        return {"year": year, "head": None}
    return {"year": year,
            "head": int(pd.to_numeric(doug["receipts_est"], errors="coerce").fillna(0).sum())}
