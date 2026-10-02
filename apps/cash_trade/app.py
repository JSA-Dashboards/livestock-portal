import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
import html
import time

# ── JPSI Brand ───────────────────────────────────────────────────────────────
JPSI_DARK = "#32373c"
JPSI_BLUE = "#0693e3"
MUTED     = "#6b7280"
BORDER    = "#e2e5e9"
POS       = "#1a7f37"
NEG       = "#c62828"

FOB_COLOR  = JPSI_BLUE     # Live FOB
DEL_COLOR  = "#e8833a"     # Dressed Delivered
CONF_COLOR = JPSI_BLUE     # Total confirmed
D14_COLOR  = "#5aa469"     # 1-14 day delivery
D30_COLOR  = "#e8833a"     # 15-30 day delivery

JSA_LOGO = "https://www.jpsi.com/wp-content/themes/gate39media/img/logo-full.png"
WATERMARK_OPACITY = 0.10

# ── Data sources ─────────────────────────────────────────────────────────────
# USDA AMS LMR (old datamart system) — no API key required.
LMR_BASE = "https://mpr.datamart.ams.usda.gov/services/v1.1/reports"

# 5 Area Weekly Weighted Average Direct Slaughter Cattle (LM_CT150). "History"
# section carries USDA's own pre-computed weekly weighted averages for Live FOB
# and Dressed Delivered, by class (Steer/Heifer), for three aligned periods per
# report: "WEEKLY WEIGHTED AVERAGES" (this week), "SAME PERIOD LAST WEEK", and
# "SAME PERIOD LAST YEAR" — matches the PDF's own weekly/week-ago/year-ago panel.
CT150_ID = 2477

# National Weekly Direct Slaughter Cattle - Negotiated Purchases (LM_CT154).
# "Summary" section (the API's default) carries the confirmed / 1-14 day /
# 15-30 day negotiated cash trade head counts plus the weekly market narrative.
CT154_ID = 2481

# Daily negotiated purchases by region. USDA publishes each region TWICE a day,
# and THE TWO FILES DO NOT DESCRIBE THE SAME TRADING DAY:
#
#   "Afternoon" (median 15:08 CT) is dated the trading day and carries that
#   day's trade as of the 1:30 pm cut -- a PARTIAL count, still moving.
#   "Summary" (median 11:17 CT) is dated the day it is PUBLISHED and carries
#   the PREVIOUS business day's COMPLETE trade.
#
# So the morning file dated D finalises trading day D-1. Taking its report_date
# as the trading day prints yesterday's average under today's date, and nothing
# looks wrong when it does -- the head count is plausible and the price is off
# by cents. Verified on Nebraska across 08/25-09/22/2026: every Summary row is
# the prior business day's Afternoon row plus the late trade, nine pairs in a
# row (Aftn 08/27 195 hd @ 220.00 -> Summary 08/28 584 hd @ 220.00).
# fetch_daily_cash() shifts the morning file back a business day to correct it.
#
# COLORADO IS ABSENT ON PURPOSE. USDA discontinued the CO daily reports -- the
# afternoon file (LM_CT133) last published 06/27/2023 and the summary
# (LM_CT134) 07/05/2024, and the API returns nothing for either on any date
# since. Colorado is still inside the 5-Area WEEKLY average on the other tab;
# there is no daily Colorado series left to show. Do not "fix" this by adding
# slugs 2669/2670 back -- they return zero rows, not an error.
DAILY_REGIONS = {
    "TX/OK/NM":       {"morning": 2664, "afternoon": 2663},   # LM_CT118 / LM_CT117
    "Kansas":         {"morning": 2666, "afternoon": 2665},   # LM_CT121 / LM_CT120
    "Nebraska":       {"morning": 2668, "afternoon": 2667},   # LM_CT124 / LM_CT123
    "Iowa/Minnesota": {"morning": 2672, "afternoon": 2671},   # LM_CT137 / LM_CT136
}

# Only NEGOTIATED CASH, only Steer and Heifer, only the roll-up grade row.
# Widening any of the three changes the number: the graded rows double-count
# against "Total all grades", and ALL BEEF TYPE folds in dairybred and mixed
# lots -- the same filter the letter's fetch_regional_cash() documents.
DAILY_PURCHASE_TYPE = "NEGOTIATED CASH"
DAILY_CLASSES = ("STEER", "HEIFER")
DAILY_GRADE_TOTAL = "Total all grades"
DAILY_BASES = {"LIVE FOB": "Live FOB", "DRESSED DELIVERED": "Dressed Delivered"}
DAILY_CUT_LABEL = {"morning": "Final", "afternoon": "1:30 pm cut"}

# /Summary rows carry both the day total and the running week total, tagged in
# current_period. "Confirmed" is that trading day; "Week to Date" is cumulative
# from Monday and resets on the trading Monday, not the file Monday.
DAILY_VOLUME_PERIODS = {"Confirmed": "day", "Week to Date": "wtd"}

# Consecutive trading days of NULL week-to-date volume after which a region is
# reported as WITHHELD rather than quiet. See _null_run_days() for the measured
# gap this sits in the middle of.
SUPPRESSION_RUN_DAYS = 10

# The window drives the FETCH, not just the view, so the default is the cheap
# one. A hidden tab still executes (see the Tabs block), which means every load
# of the WEEKLY tab pays for whatever this defaults to: 1M is about 12 s across
# the eight reports on a cold cache and instant for the next hour, where 1Y is
# nearer 40 s. Anyone who wants the longer series can ask for it and wait once.
DAILY_WINDOWS = {"1M": 30, "3M": 90, "6M": 180, "1Y": 365}
DAILY_WINDOW_DEFAULT = "1M"
DAILY_REGION_COLORS = {
    "TX/OK/NM": JPSI_BLUE, "Kansas": D14_COLOR,
    "Nebraska": DEL_COLOR, "Iowa/Minnesota": "#7e57c2",
}

# ── Monday-print forecast ────────────────────────────────────────────────────
# How much daily history the forecast calibrates on. A FULL YEAR, ASKED FOR
# OUTRIGHT, and that is safe for a reason that is easy to get wrong: the cost
# of a /Summary request is FLAT in the window length. Measured 2026-10-02, the
# eight Summary reports take 4.8 s for 30 days and 5.6 s for 365 -- 675 KB
# against 8.0 MB, server-bound either way. It is fetch_daily_cash's /Detail
# section that is expensive (11 MB for one region-year), and DAILY_WINDOW_DEFAULT
# exists to hold THAT down under the hidden-tab rule. Do not "fix" this by
# shrinking it to match the Daily tab: a year buys ~50 calibration weeks for
# under a second, and a month buys four.
FORECAST_CAL_DAYS = 365

# Trailing weeks used to carry the 5-Area number across to the national one.
# FOUR, AND THE SHORTNESS IS THE POINT. Backtested on 175 weekly pairs since
# 2023: in normal times every window from 4 to 26 weeks and all three methods
# (additive gap, ratio, OLS) land inside 2.4-3.4% median absolute error, so the
# choice barely matters -- until the relationship steps, when it is the only
# thing that matters. Since Kansas and TX/OK/NM stopped publishing daily
# volumes the gap roughly doubled and every method under-predicts; measured
# over those weeks the bias is -3.5% at 4 weeks, -12.4% at 8, -16.0% at 13 and
# -15.1% at 26. The short window is the one that notices a regime change.
FORECAST_GAP_WEEKS = 4
# Band is drawn from a slightly longer window so it spans a real range of
# outcomes rather than the four points the centre is built from.
FORECAST_BAND_WEEKS = 6

# Checkpoint ordering within a trading week. The afternoon file for day D is
# published about 15:08 CT on D; the morning file that FINALISES D lands about
# 11:17 CT on D+1. So for one trade_date the 1:30 pm cut comes first and the
# final second, and Monday's final precedes Tuesday's cut. Sorting on
# (weekday, CUT_ORDER[cut]) therefore puts a week's publications in the order
# they actually appeared, which is what "the latest thing USDA has told us"
# has to mean.
CUT_ORDER = {"afternoon": 0, "morning": 1}

PRICE_PERIODS = ["WEEKLY WEIGHTED AVERAGES", "SAME PERIOD LAST WEEK", "SAME PERIOD LAST YEAR"]
PERIOD_LABEL = {
    "WEEKLY WEIGHTED AVERAGES": "This Week",
    "SAME PERIOD LAST WEEK": "Week Ago",
    "SAME PERIOD LAST YEAR": "Year Ago",
}
BASIS_LABEL = {"Live": "Live FOB", "Dressed": "Dressed Delivered"}

# st.set_page_config removed — the Livestock Portal shell (Home.py) makes the
# single set_page_config call allowed per multi-page run.

st.markdown(f"""
<style>
  @import url('https://fonts.googleapis.com/css2?family=Source+Sans+Pro:wght@300;400;600;700&display=swap');
  html, body, [class*="css"], .stApp, button, input, select, textarea, table, td, th, .stMarkdown,
  h1, h2, h3, h4, h5, h6, p, span, div {{
    font-family: 'Source Sans Pro', system-ui, -apple-system, sans-serif !important;
  }}

  #MainMenu, footer {{ visibility:hidden !important; }}
  .stDeployButton {{ display:none; }}

  .stApp {{ background-color:#ffffff; }}
  .block-container {{ padding-top:0.75rem !important; max-width:1250px; }}

  [data-testid="stSidebar"] {{ background-color:#f6f8fa; border-right:1px solid {BORDER}; }}

  .dash-header {{
    background:#ffffff; border-bottom:3px solid {JPSI_BLUE};
    padding:16px 8px 14px 8px; margin:-0.75rem 0 22px 0;
    display:flex; align-items:center; gap:20px;
  }}
  .dash-header-logo img {{ height:48px; display:block; }}
  .dash-header-text {{ flex:1; text-align:center; }}
  .dash-header-text h1 {{
    margin:0; color:{JPSI_DARK} !important; font-size:1.65rem; font-weight:700; letter-spacing:-0.01em;
  }}
  .dash-header-text .subtitle {{ color:{MUTED}; font-size:0.83rem; margin:3px 0 0 0; }}
  .dash-header-meta {{ text-align:right; color:{MUTED}; font-size:0.75rem; min-width:150px; }}
  .dash-header-meta b {{ color:{JPSI_DARK}; font-size:1rem; }}

  .sec-header {{
    color:{JPSI_DARK}; font-size:0.78rem; font-weight:700; text-transform:uppercase;
    letter-spacing:0.08em; padding:6px 0 6px 10px; border-left:4px solid {JPSI_BLUE};
    margin:22px 0 12px;
  }}

  .tile {{
    background:#ffffff; border:1px solid {BORDER}; border-top:3px solid {JPSI_BLUE};
    border-radius:10px; padding:14px 16px; text-align:center; height:100%;
    box-shadow:0 1px 4px rgba(50,55,60,0.06);
  }}
  .tile-fob   {{ border-top-color:{FOB_COLOR}; }}
  .tile-del   {{ border-top-color:{DEL_COLOR}; }}
  .tile-conf  {{ border-top-color:{CONF_COLOR}; }}
  .tile-d14   {{ border-top-color:{D14_COLOR}; }}
  .tile-d30   {{ border-top-color:{D30_COLOR}; }}
  .tile-neu   {{ border-top-color:{MUTED}; }}
  /* Same reasoning as .tile-value: a label that breaks as "IOWA/MI/NNESOT/A"
     is worse than a small one. The letter-spacing shrinks with the font,
     because at 0.08em it is what pushes the longest label over the edge. */
  .tile-label {{ color:{MUTED}; font-size:clamp(0.5rem, 0.85vw, 0.66rem);
                 text-transform:uppercase; letter-spacing:clamp(0.02em, 0.1vw, 0.08em);
                 margin-bottom:6px; white-space:nowrap; }}
  /* Tile values must never break mid-token. Streamlit's default overflow-wrap
     splits them once four tiles share a narrow row -- "Undefined" rendered as
     "Undefin/ed" and "$222.00" as "$222./00". nowrap stops the break and the
     clamp shrinks the text to fit rather than letting it overflow the tile.
     At desktop width the clamp resolves to 1.55rem, so nothing changes there
     and the weekly tiles, which use the same class, are untouched in practice. */
  .tile-value {{ color:{JPSI_DARK}; font-size:clamp(1rem, 2vw, 1.55rem);
                 font-weight:700; line-height:1.1; white-space:nowrap; }}
  .tile-delta-pos {{ color:{POS}; font-size:clamp(0.62rem, 1.05vw, 0.8rem); font-weight:600; margin-top:4px; white-space:nowrap; }}
  .tile-delta-neg {{ color:{NEG}; font-size:clamp(0.62rem, 1.05vw, 0.8rem); font-weight:600; margin-top:4px; white-space:nowrap; }}
  .tile-delta-neu {{ color:{MUTED}; font-size:clamp(0.62rem, 1.05vw, 0.8rem); font-weight:600; margin-top:4px; white-space:nowrap; }}

  .narrative {{
    background:#f6f8fa; border:1px solid {BORDER}; border-left:4px solid {JPSI_BLUE};
    border-radius:8px; padding:14px 18px; color:{JPSI_DARK}; font-size:0.85rem; line-height:1.55;
  }}

  .note {{ color:{MUTED}; font-size:0.72rem; line-height:1.5; }}
  hr {{ border-color:{BORDER}; }}
</style>
""", unsafe_allow_html=True)


# ── Helpers ──────────────────────────────────────────────────────────────────

def fmt_price(v):
    return f"${v:.2f}" if v is not None and pd.notna(v) else "—"


def fmt_hd(v):
    return f"{v:,.0f} hd" if v is not None and pd.notna(v) else "—"


def price_delta_html(cur, prior):
    if cur is None or prior is None or pd.isna(cur) or pd.isna(prior):
        return '<div class="tile-delta-neu">—</div>'
    diff = cur - prior
    sign = "▲" if diff > 0 else ("▼" if diff < 0 else "")
    color = "pos" if diff > 0 else ("neg" if diff < 0 else "neu")
    return f'<div class="tile-delta-{color}">{sign} ${abs(diff):.2f}</div>'


def hd_delta_html(cur, prior):
    if cur is None or prior is None or pd.isna(cur) or pd.isna(prior):
        return '<div class="tile-delta-neu">—</div>'
    diff = cur - prior
    pct = (diff / prior * 100) if prior else None
    sign = "▲" if diff > 0 else ("▼" if diff < 0 else "")
    color = "pos" if diff > 0 else ("neg" if diff < 0 else "neu")
    pct_str = f" ({pct:+.1f}%)" if pct is not None else ""
    return f'<div class="tile-delta-{color}">{sign} {abs(diff):,.0f} hd{pct_str}</div>'


def and_list(items) -> str:
    """["a"] -> "a"; ["a","b"] -> "a and b"; ["a","b","c"] -> "a, b and c"."""
    items = list(items)
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    return f"{', '.join(items[:-1])} and {items[-1]}"


def tile(label, value, delta="", cls=""):
    return (f'<div class="tile {cls}">'
            f'<div class="tile-label">{label}</div>'
            f'<div class="tile-value">{value}</div>'
            f'{delta}</div>')


# ── Data Fetching ────────────────────────────────────────────────────────────

def _session(backoff=3) -> requests.Session:
    s = requests.Session()
    retry = Retry(total=3, backoff_factor=backoff,
                   status_forcelist=[429, 500, 502, 503, 504], allowed_methods=["GET"])
    s.mount("https://", HTTPAdapter(max_retries=retry))
    return s


def _probe_session() -> requests.Session:
    """
    A deliberately impatient session, used ONLY by publication_stamps().

    _session() retries three times with a backoff_factor of 3, so against an
    unresponsive USDA it blocks for roughly a minute and a half before giving
    up. That is the right trade for the data fetches, which have nothing to
    show without it. It is the wrong trade here: the probe runs at module scope
    above st.tabs, so during an outage EVERY visitor would pay that wait on
    every rerun, on whichever tab they are looking at, to learn something the
    page already has a fallback for. One attempt, split connect/read timeout,
    worst case about eleven seconds.
    """
    s = requests.Session()
    s.mount("https://", HTTPAdapter(max_retries=Retry(
        total=0, status_forcelist=[], allowed_methods=["GET"])))
    return s


# `stamps` is unused in the body and must stay: it is USDA's published_date for
# LM_CT150, taken as an argument so st.cache_data keys on it. This used to read
# ttl=3600, persist="disk", which NEVER EXPIRED -- Streamlit ignores ttl when
# persist is set, so the sidebar's "Cache: 1 hr" was not true and a weekly
# release was only picked up by "Refresh now" or a restart. See publication_stamps.
@st.cache_data(persist="disk", max_entries=8, show_spinner=False)
def fetch_price_history(stamps: str) -> pd.DataFrame:
    """Full-history weekly Live FOB / Dressed Delivered weighted averages by
    class (Steer/Heifer), for all three USDA-aligned periods, from LM_CT150."""
    url = f"{LMR_BASE}/{CT150_ID}/History"
    sess = _session()
    resp = sess.get(url, timeout=120)
    resp.raise_for_status()
    rows = resp.json().get("results", [])
    df = pd.DataFrame(rows)
    if df.empty:
        return df

    df["report_date"] = pd.to_datetime(df["report_date"], format="%m/%d/%Y", errors="coerce")
    # previous_week_head_count rides along for the forecast tab. It is a
    # HEADER-LEVEL field repeated on every row of the report, not a per-class
    # one -- de-duplicate by report_date before using it, which
    # weekly_5area_head() does. Carrying it here costs nothing: this request
    # already pulls the whole History section for the price panel.
    for c in ["head_count", "weight_range_avg", "weighted_avg_price",
              "previous_week_head_count"]:
        df[c] = pd.to_numeric(df[c].astype(str).str.replace(",", "", regex=False), errors="coerce")

    df = df.dropna(subset=["report_date"])
    keep = ["report_date", "current_period", "selling_basis_desc", "class_description",
            "head_count", "weight_range_avg", "weighted_avg_price",
            "previous_week_head_count"]
    return df[keep].sort_values("report_date").reset_index(drop=True)


# `stamps` as above, for LM_CT154. Same never-expiring ttl bug, same fix.
@st.cache_data(persist="disk", max_entries=8, show_spinner=False)
def fetch_volume_history(stamps: str) -> pd.DataFrame:
    """Full-history weekly negotiated cash trade volumes (confirmed, 1-14 day,
    15-30 day) plus the weekly market narrative, from LM_CT154."""
    url = f"{LMR_BASE}/{CT154_ID}"
    sess = _session()
    resp = sess.get(url, timeout=60)
    resp.raise_for_status()
    rows = resp.json().get("results", [])
    df = pd.DataFrame(rows)
    if df.empty:
        return df

    df["report_date"] = pd.to_datetime(df["report_date"], format="%m/%d/%Y", errors="coerce")
    num_cols = ["total_head_count", "head_count_week_ago", "head_count_year_ago",
                "total_head_count_1", "head_count_week_ago_1",
                "total_head_count_2", "head_count_week_ago_2"]
    for c in num_cols:
        df[c] = pd.to_numeric(df[c].astype(str).str.replace(",", "", regex=False), errors="coerce")

    df = df.dropna(subset=["report_date"]).sort_values("report_date").reset_index(drop=True)
    return df[["report_date", "trend"] + num_cols]


def combine_steer_heifer(df: pd.DataFrame) -> pd.DataFrame:
    """Head-count-weighted combine of Steer + Heifer rows, per report_date /
    period / selling basis — a simple weighted average, no double-counting."""
    d = df.copy()
    d["wp"] = d["head_count"] * d["weighted_avg_price"]
    g = d.groupby(["report_date", "current_period", "selling_basis_desc"], as_index=False).agg(
        head_count=("head_count", "sum"), wp_sum=("wp", "sum"),
    )
    g["combo_price"] = g["wp_sum"] / g["head_count"]
    return g.drop(columns="wp_sum")


def period_value(g: pd.DataFrame, report_date, period, basis):
    row = g[(g["report_date"] == report_date) & (g["current_period"] == period) &
            (g["selling_basis_desc"] == basis)]
    if row.empty:
        return None, None
    r = row.iloc[0]
    return r["combo_price"], r["head_count"]


def _dnum(x):
    """USDA ships numbers as comma-grouped strings and blanks as None or ''."""
    if x is None:
        return None
    s = str(x).replace(",", "").strip()
    if not s or s in {"-", "--"}:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _daily_rows(payload) -> list:
    """
    AMS ANSWERS 200 WITH A BARE JSON STRING when a window has no report -- not
    an error status, not an empty list, not an object with zero results.
    Iterating that as sections walks its CHARACTERS and dies on str.get. Every
    shape but the documented one is treated as no rows.
    """
    if isinstance(payload, dict):
        r = payload.get("results")
        return r if isinstance(r, list) else []
    if isinstance(payload, list):
        out = []
        for sec in payload:
            if isinstance(sec, dict) and isinstance(sec.get("results"), list):
                out.extend(sec["results"])
        return out
    return []


PROBE_FAILED = "probe-unavailable"
# NO persist="disk" HERE, AND THAT IS THE WHOLE POINT. Streamlit documents that
# "ttl will be ignored if persist='disk' or persist=True" -- so a probe written
# @st.cache_data(ttl=300, persist="disk") never expires and the freshness check
# freezes at whatever it first saw. Verified against streamlit 1.63's own source.
# This cache is process-wide and in-memory, which is what a 5-minute freshness
# probe wants anyway.
@st.cache_data(ttl=300, show_spinner=False)
def publication_stamps() -> str:
    """
    When USDA last published each of our eight reports, as one opaque string.
    It is passed to fetch_daily_cash() purely as a cache key, so the expensive
    fetch re-runs exactly when USDA publishes and not on a timer.

    WHY NOT REFRESH ON A SCHEDULE, which is the obvious thing to do: AMS DOES
    NOT PUBLISH ONE. Its 30 Apr 2020 LMR notice says that from 4 May 2020 report
    data is released "in real time", replacing the old top-of-the-hour release,
    and there is no livestock equivalent of the dairy release-times page. The
    measured spread says the same -- over 180 days (n=506 AM, 497 PM):

        AM  min 10:52  median 11:17  p90 11:39  p95 11:55  p99 13:17  max 16:18
        PM  min 14:49  median 15:08  p90 15:23  p95 15:28  p99 16:14  max 16:49

    4.9% of AM files land after noon and the tail runs past 16:00, so a refresh
    pinned to the median would miss them outright. The only clock AMS commits to
    is a 5:00 pm Central cutoff, past which a delayed report is held to the next
    business day. Keying on the stamp USDA itself publishes needs no schedule.

    The stamps are US CENTRAL with daylight saving -- AMS LMPR API User Guide
    V3.3 (Nov 2024) section 2.2: "The LMPR API is set to Central Standard Time
    (CST) time zone. Standard and daylight time rules apply." Confirmed live on
    2026-09-23: the Nebraska AM stamp read 11:10:32 and appeared at 11:11:22
    CDT. Nothing here depends on that -- this compares stamps to stamps, never
    to our own clock -- but it is what the displayed time means.

    The reports LIST endpoint carries published_date for every slug in a single
    request (~67KB, ~3.7s measured), which is far cheaper than the eight Detail
    calls it guards, and it matters that it is cheap: this page is behind a tab,
    and a hidden Streamlit tab still executes on every rerun.

    On failure this returns a STABLE sentinel rather than "" or a timestamp. A
    key that varies on failure would turn every probe outage into a full
    eight-request refetch -- the opposite of the point. A constant means the
    first failure refetches once and every failure after it is a cache hit.
    """
    try:
        resp = _probe_session().get(LMR_BASE, timeout=(3, 8))
        resp.raise_for_status()
        rows = resp.json()
    except Exception:
        return PROBE_FAILED
    if not isinstance(rows, list):
        return PROBE_FAILED
    wanted = {CT150_ID, CT154_ID}
    wanted |= {slug for cuts in DAILY_REGIONS.values() for slug in cuts.values()}
    stamps = {x.get("slug_id"): x.get("published_date") for x in rows
              if isinstance(x, dict) and x.get("slug_id") in wanted}
    if not stamps:
        return PROBE_FAILED
    return "|".join(f"{k}={stamps[k]}" for k in sorted(stamps))


def stamps_for(stamps: str, slugs) -> str:
    """
    The publication stamps for just `slugs`, as a cache key.

    One probe covers every report on the page, but each consumer must key on
    only its OWN reports -- otherwise the weekly fetch, whose data changes on
    Mondays, would re-run every time a daily file published.
    """
    if not stamps or stamps == PROBE_FAILED:
        return PROBE_FAILED
    want = {str(s) for s in slugs}
    keep = [p for p in stamps.split("|")
            if "=" in p and p.split("=", 1)[0] in want]
    return "|".join(keep) if keep else PROBE_FAILED


def daily_last_published(stamps: str) -> str:
    """The newest publication stamp in the probe string, for display."""
    if not stamps or stamps == PROBE_FAILED:
        return ""
    seen = [s.split("=", 1)[1] for s in stamps.split("|") if "=" in s]
    seen = [s for s in seen if s]
    if not seen:
        return ""
    # Stamps are "MM/DD/YYYY HH:MM:SS"; sort on a comparable key, not the string.
    def _key(s):
        try:
            d, t = s.split(" ", 1)
            m, dd, y = d.split("/")
            return (y, m, dd, t)
        except Exception:
            return ("", "", "", "")
    return max(seen, key=_key)


# NO ttl, deliberately: persist="disk" would ignore it anyway (see
# publication_stamps), and stating one would only mislead the next reader into
# thinking time drives this. The `stamps` argument drives it. max_entries bounds
# what disk collects, since the key changes roughly twice a day.
def _fetch_many(jobs: list, timeout: int = 90) -> dict:
    """
    Run independent datamart GETs concurrently, returning {key: rows}.

    Latency here is server-bound, not payload-bound: a 30-day window costs
    about 2.2 s whether it returns 108 KB of Summary or 1 MB of Detail. Run
    sequentially, the sixteen requests this page needs are over half a minute
    of wall clock on a cold cache -- and because a hidden Streamlit tab still
    executes, everyone pays it, including someone who only opens the Weekly
    tab. They are independent GETs, so they overlap cleanly.

    Each worker builds its OWN session via _session(): requests.Session is not
    safe to share across threads. Nothing in here touches st.*, so it is safe
    inside a cached function.

    A job that fails yields [] rather than raising: these are independent
    reports and one being down is not a reason to blank the others.
    """
    def run(job):
        key, slug, section, params = job
        try:
            resp = _session().get(f"{LMR_BASE}/{slug}/{section}",
                                  params=params, timeout=timeout)
            if resp.status_code in (204, 404):
                return key, []
            resp.raise_for_status()
            return key, _daily_rows(resp.json())
        except Exception:
            return key, []

    if not jobs:
        return {}
    with ThreadPoolExecutor(max_workers=min(8, len(jobs))) as ex:
        return dict(ex.map(run, jobs))


@st.cache_data(persist="disk", max_entries=64, show_spinner=False)
def fetch_daily_cash(start: str, end: str, stamps: str) -> pd.DataFrame:
    """
    Daily negotiated Steer/Heifer prices for the four regions USDA still
    publishes daily, both cuts, keyed on the TRADING day rather than the file
    date.

    `stamps` IS DELIBERATELY UNUSED IN THIS BODY. It is USDA's own publication
    timestamps from publication_stamps(), taken as an argument solely so
    that st.cache_data includes it in the cache key: when USDA publishes, the
    string changes, the key changes, and this re-runs. Deleting it as a dead
    parameter would silently restore pure time-based expiry and put the page
    back to serving data up to six hours stale.

    Eight requests in all -- one per region per cut -- because the datamart
    accepts a report_date RANGE (report_date=MM/DD/YYYY:MM/DD/YYYY). A day at a
    time would be some 600 requests for a year of history.

    THE grade_desc FILTER IS WHAT MAKES THIS AFFORDABLE, and it matters because
    of the hidden-tab rule: this runs on every rerun, including for someone who
    only ever looks at the Weekly tab. Unfiltered, a year of Nebraska is 43,176
    rows and 48 MB in 12 s; asking the server for "Total all grades" alone cuts
    it to 10,280 rows and 11 MB in 4.5 s, and those are exactly the rows kept
    below. Measured 2026-09-23.

    Only ONE extra filter can be passed: chaining a second (grade_desc AND
    purchase_type_code) makes AMS return its bare-string no-results sentinel
    rather than an intersection. The class and purchase-type filters therefore
    stay client-side, and the grade check below stays too -- the server filter
    is an optimisation, not a guarantee.

    A region that fails is SKIPPED, not raised: these are eight independent
    reports and one being down is not a reason to blank the other three.
    """
    jobs = [((region, cut), slug, "Detail",
             {"q": f"report_date={start}:{end};grade_desc={DAILY_GRADE_TOTAL}"})
            for region, cuts in DAILY_REGIONS.items() for cut, slug in cuts.items()]
    fetched = _fetch_many(jobs)

    out = []
    for (region, cut), rows in fetched.items():
        for x in rows:
            if str(x.get("purchase_type_code", "")).strip() != DAILY_PURCHASE_TYPE:
                continue
            if str(x.get("class_desc", "")).strip() not in DAILY_CLASSES:
                continue
            if str(x.get("grade_desc", "")).strip() != DAILY_GRADE_TOTAL:
                continue
            basis = str(x.get("selling_basis_desc", "")).strip()
            if basis not in DAILY_BASES:
                continue
            # UNPRICED ROWS ARE KEPT, and that is load-bearing. USDA
            # publishes a file for a day with no confirmed trade, every
            # price null -- that is its "Undefined" market test, a real
            # answer. Dropping those rows made a published no-trade day
            # indistinguishable from a day USDA never published, so the
            # headline silently fell back to an older day: measured over the
            # last year the headline was behind the newest published day for
            # 15% of wall-clock. daily_combined() still drops them, so no
            # unpriced row reaches an average; they exist only so the page
            # can tell "nothing traded" from "nothing published".
            price = _dnum(x.get("wtd_avg_price"))
            out.append({
                "region": region, "cut": cut,
                "file_date": x.get("report_date"),
                "class": str(x.get("class_desc", "")).strip(),
                "basis": DAILY_BASES[basis],
                "head": _dnum(x.get("head_count")),
                "weight": _dnum(x.get("wtd_avg_weight")),
                "price": price,
            })

    df = pd.DataFrame(out)
    if df.empty:
        return df

    df["file_date"] = pd.to_datetime(df["file_date"], format="%m/%d/%Y", errors="coerce")
    df = df.dropna(subset=["file_date"])
    if df.empty:
        return df

    # THE ONE-BUSINESS-DAY SHIFT -- see DAILY_REGIONS for the evidence. Only the
    # morning file moves; the afternoon file is already dated its trading day.
    #
    # BDay steps over weekends but NOT holidays, so a morning file published the
    # day after a holiday resolves to the holiday rather than the last session
    # that actually traded. It is off by one session on those few dates a year,
    # and the tell is a holiday carrying a full day of trade.
    df["trade_date"] = df["file_date"]
    morning = df["cut"] == "morning"
    df.loc[morning, "trade_date"] = (
        df.loc[morning, "file_date"] - pd.tseries.offsets.BDay(1))

    return df.sort_values(["trade_date", "region", "cut"]).reset_index(drop=True)


@st.cache_data(persist="disk", max_entries=64, show_spinner=False)
def fetch_daily_volume(start: str, end: str, stamps: str) -> pd.DataFrame:
    """
    Negotiated cash HEAD COUNT per region -- the day's confirmed total and the
    running week-to-date -- from each report's /Summary section, which the
    price fetch never asks for.

    `stamps` is the cache key, exactly as in fetch_daily_cash(); see there.

    THIS IS A BROADER UNIVERSE THAN THE PRICES, and must never be shown as the
    head count behind them. fetch_daily_cash() filters to Steer and Heifer,
    Live FOB and Dressed Delivered, "Total all grades", because that is what a
    quoted average has to be built from. USDA's Confirmed and Week-to-Date
    volumes count every class and all four selling bases -- mixed lots,
    dairybred, the FOB/delivered variants the price section leaves out. On
    09/18/2026 Nebraska that is 3,690 head confirmed against 1,547 in the live
    FOB steer row. Same market, different question.

    A NULL VOLUME IS ZERO IN THE 5-AREA SUM, AND NOT A ZERO ANYWHERE ELSE.
    USDA leaves the field empty for a region it is not giving a number for, and
    its own aggregate adds that in as nothing: summing these four regions with
    nulls as zero reproduces LM_CT100's current_week_head_count EXACTLY on 118
    of 118 file dates (verified 2026-09-23), and LM_CT150's published
    previous_week_head_count on 23 of 23 weeks back to April 2026 (re-verified
    2026-10-02). That is why the 5-Area figure on the page is a sum of these
    four and not a fifth request.

    THE RULE DOES NOT CARRY TO A PER-REGION FIGURE, and reading it as though it
    did is what put "0 head" on the Kansas and TX/OK/NM tiles while USDA was
    withholding both for confidentiality. USDA NEVER PUBLISHES A LITERAL 0 --
    zero occurrences in 2,877 region-trading-days over 2024-01-01..2026-10-02 --
    so a 0 on a region tile is always this page's own invention, and it reads
    as "nobody traded". The trade is real: as TX/OK/NM (last number 2026-06-26)
    and Kansas (2026-08-14) went dark, the gap between LM_CT154 national
    confirmed negotiated and the LM_CT150 5-Area doubled from a median 11,567
    hd/wk to 23,172 hd/wk, with 4 of 6 weeks above the entire pre-period max.
    Roughly 11,600 hd/wk of real negotiated trade is counted nationally and
    absent from the 5-Area -- absent from USDA's figure as well as ours, which
    is why the sum above still reconciles. weekly_to_date() carries the raw
    null out for the tiles and zeroes it only for the total; see there and
    _null_run_days() for telling a withheld region from a quiet one.

    Coverage over the last 180 days, morning files: IA/MN 88%, Nebraska 78%,
    Kansas 57%, TX/OK/NM 38%.
    """
    jobs = [((region, cut), slug, "Summary",
             {"q": f"report_date={start}:{end}"})
            for region, cuts in DAILY_REGIONS.items() for cut, slug in cuts.items()]
    fetched = _fetch_many(jobs)

    out = []
    for (region, cut), rows in fetched.items():
        for x in rows:
            if str(x.get("purchase_type_desc", "")).strip() != DAILY_PURCHASE_TYPE:
                continue
            period = str(x.get("current_period", "")).strip()
            if period not in DAILY_VOLUME_PERIODS:
                continue
            out.append({
                "region": region, "cut": cut,
                "file_date": x.get("report_date"),
                "period": DAILY_VOLUME_PERIODS[period],
                "head": _dnum(x.get("current_date_volume")),
                # On the Week-to-Date row this is the RUNNING TOTAL AT THE SAME
                # POINT LAST WEEK, not last week's finished total: measured,
                # week_ago_volume(D) equals current_date_volume(D-7). It is the
                # like-for-like comparison, which is the useful one midweek.
                "head_week_ago": _dnum(x.get("week_ago_volume")),
            })

    df = pd.DataFrame(out)
    if df.empty:
        return df
    df["file_date"] = pd.to_datetime(df["file_date"], format="%m/%d/%Y", errors="coerce")
    df = df.dropna(subset=["file_date"])
    if df.empty:
        return df

    # Same one-business-day shift as the prices -- the morning file's volumes
    # describe the previous business day too, so the week-to-date must be keyed
    # on the TRADING day or it lands a day late and the Monday reset moves.
    df["trade_date"] = df["file_date"]
    morning = df["cut"] == "morning"
    df.loc[morning, "trade_date"] = (
        df.loc[morning, "file_date"] - pd.tseries.offsets.BDay(1))
    return df.sort_values(["trade_date", "region", "cut"]).reset_index(drop=True)


def _null_run_days(vol: pd.DataFrame, region: str, trade_date) -> int:
    """
    Consecutive trading days up to `trade_date` on which USDA published this
    region's week-to-date volume BLANK.

    THE FIELD ALONE CANNOT SAY WHY IT IS BLANK, which is the whole reason this
    exists. USDA never publishes a literal 0 -- zero occurrences in 2,877
    region-trading-days over 2024-01-01..2026-10-02 -- so "no confirmed trade"
    and "withheld for confidentiality" are the SAME empty field on the day, and
    the obvious discriminators do not work. The full-skeleton signature in
    particular does not: on days where NEGOTIATED CASH is blank, NEGOTIATED
    GRID BASE still carries a number 90% of the time for Iowa/Minnesota.

    The RUN separates them cleanly. Over those same three years:

        Iowa/Minnesota   longest blank run  3
        Nebraska         longest blank run  4
        Kansas           runs of 1-4, then one run now 35 days and open
        TX/OK/NM         runs of 1-4, then two runs reaching 36 and 67

    Every ordinary quiet stretch ended by day 4; every run that reached day 5
    went on to at least 35. SUPPRESSION_RUN_DAYS sits in that empty middle, so
    a quiet week is never called withheld and a region that goes dark is named
    within two trading weeks. The measurement needs the fetched window to be
    longer than the threshold: the shortest DAILY_WINDOWS option is 30 calendar
    days, about 21 trading days, so it is.
    """
    d = vol[(vol["period"] == "wtd") & (vol["region"] == region)
            & (vol["trade_date"] <= trade_date)]
    if d.empty:
        return 0
    # Morning is the final figure and wins where both cuts exist -- the same
    # precedence the tiles use, so the run describes the number on screen.
    seen = {}
    for cut in ("afternoon", "morning"):
        hit = d[d["cut"] == cut]
        seen.update(dict(zip(hit["trade_date"], hit["head"])))
    run = 0
    for td in sorted(seen, reverse=True):
        if pd.notna(seen[td]):
            break
        run += 1
    return run


def weekly_to_date(vol: pd.DataFrame, trade_date) -> dict:
    """
    Week-to-date head per region for one trading day, plus the 5-Area sum.

    Prefers the final (morning) figure and falls back to the 1:30 pm cut, the
    same precedence the price tiles use, so a region reports as far through the
    day as USDA has taken it.

    A BLANK VOLUME MEANS DIFFERENT THINGS IN THE TWO HALVES OF THIS RETURN, and
    that is not an inconsistency. The 5-Area total adds it in as zero because
    USDA's own aggregate does -- see fetch_daily_volume, and the 2026-10-02
    re-verification in the footnote this feeds. The per-region entry carries the
    raw None, because on a tile a 0 is a number this page invented and reads as
    "nobody traded" for a region whose trade USDA is withholding.
    """
    if vol.empty:
        return {}
    day = vol[(vol["trade_date"] == trade_date) & (vol["period"] == "wtd")]
    if day.empty:
        return {}
    out = {}
    for region in DAILY_REGIONS:
        reg = day[day["region"] == region]
        row = None
        for cut in ("morning", "afternoon"):
            hit = reg[reg["cut"] == cut]
            if not hit.empty:
                row = hit.iloc[0]
                break
        if row is None:
            continue
        blank = bool(pd.isna(row["head"]))
        out[region] = {
            "head": None if blank else float(row["head"]),
            "week_ago": (None if pd.isna(row["head_week_ago"])
                         else float(row["head_week_ago"])),
            "cut": row["cut"],
            # A blank that has lasted -- USDA is publishing the file and
            # holding the number back. Short blanks stay unflagged: they are
            # indistinguishable from a quiet day and must not be asserted.
            "suppressed": (blank and _null_run_days(vol, region, trade_date)
                           >= SUPPRESSION_RUN_DAYS),
        }
    if not out:
        return {}
    # Bound before the assignment rather than read out of `out` inside the
    # literal, so nobody has to reason about whether _total is in its own sum.
    withheld = [r for r, v in out.items() if v["suppressed"]]
    counted = [r for r, v in out.items() if not v["suppressed"]]
    out["_total"] = {
        # NULLS SUM AS ZERO HERE AND MUST KEEP DOING SO. USDA's published
        # 5-Area total drops a withheld region exactly this way: summing these
        # four with blanks as zero reproduces LM_CT150's own
        # previous_week_head_count on 23 of 23 weeks back to April 2026
        # (verified 2026-10-02), a span covering both TX/OK/NM and Kansas going
        # dark. The identity breaks if a blank is ever treated as missing here.
        "head": sum(0.0 if v["head"] is None else v["head"] for v in out.values()),
        "week_ago": (sum(v["week_ago"] for v in out.values()
                         if v["week_ago"] is not None)
                     if any(v["week_ago"] is not None for v in out.values()) else None),
        "cut": None,
        "withheld": withheld,
        "counted": counted,
    }
    return out


def _week_start(dates: pd.Series) -> pd.Series:
    """
    The Monday of the week a weekly report DESCRIBES, from its report_date.

    Both weekly reports print on the Monday after the week they cover, so the
    week is report_date minus seven days -- but only normalising to Monday
    afterwards is safe. A holiday pushes the release to Tuesday, and Tuesday
    minus seven is the PREVIOUS Tuesday, which would key that week one day off
    and silently fail to join against everything else.
    """
    shifted = dates - pd.to_timedelta(7, unit="D")
    return shifted - pd.to_timedelta(shifted.dt.weekday, unit="D")


def weekly_5area_head(price_df: pd.DataFrame) -> pd.Series:
    """
    USDA's own published 5-Area weekly negotiated head, keyed to the week it
    describes. Indexed by the Monday of that week.

    THIS IS THE NUMBER THE FORECAST IS AIMING AT, and it is also what makes the
    forecast arithmetic rather than a guess. Verified 2026-10-02 on every one
    of the 23 weeks back to April 2026: this equals the four daily regions'
    Friday-FINAL week-to-date, summed with nulls as zero -- exactly, not
    approximately, including the weeks where two of the four regions published
    nothing at all. So the only unknown left in Monday's 5-Area print is the
    trade that lands after USDA's last published cut.
    """
    if price_df.empty or "previous_week_head_count" not in price_df:
        return pd.Series(dtype=float)
    d = price_df.dropna(subset=["report_date"]).drop_duplicates("report_date")
    d = d.dropna(subset=["previous_week_head_count"])
    if d.empty:
        return pd.Series(dtype=float)
    out = pd.Series(d["previous_week_head_count"].values,
                    index=_week_start(d["report_date"]))
    return out[~out.index.duplicated(keep="last")].sort_index()


def weekly_national_head(vol_df: pd.DataFrame) -> pd.Series:
    """National weekly confirmed negotiated head (LM_CT154), keyed the same way."""
    if vol_df.empty or "total_head_count" not in vol_df:
        return pd.Series(dtype=float)
    d = vol_df.dropna(subset=["report_date", "total_head_count"]).drop_duplicates("report_date")
    if d.empty:
        return pd.Series(dtype=float)
    out = pd.Series(d["total_head_count"].values, index=_week_start(d["report_date"]))
    return out[~out.index.duplicated(keep="last")].sort_index()


def wtd_checkpoints(vol: pd.DataFrame) -> pd.DataFrame:
    """
    The 5-Area week-to-date head at every publication USDA has made, one row
    per (week, weekday, cut).

    Regions are summed with nulls as zero, the same rule weekly_to_date() and
    USDA's own aggregate follow -- see fetch_daily_volume. A region missing from
    the frame entirely contributes nothing, which is what makes a suppressed
    Kansas drop out here exactly as it drops out of USDA's published figure.
    """
    cols = ["week", "weekday", "cut", "order", "wtd"]
    if vol.empty:
        return pd.DataFrame(columns=cols)
    d = vol[vol["period"] == "wtd"].copy()
    if d.empty:
        return pd.DataFrame(columns=cols)
    d["week"] = d["trade_date"] - pd.to_timedelta(d["trade_date"].dt.weekday, unit="D")
    d["weekday"] = d["trade_date"].dt.weekday
    # One row per region per checkpoint first, so a region USDA happens to
    # repeat cannot be counted twice into the sum.
    g = d.groupby(["week", "weekday", "cut", "region"], as_index=False)["head"].first()
    # to_numeric first: a checkpoint where every region is withheld arrives as
    # an all-None object column, and .fillna on one of those downcasts with a
    # FutureWarning today and changes behaviour later.
    cp = (g.assign(head=pd.to_numeric(g["head"], errors="coerce").fillna(0.0))
            .groupby(["week", "weekday", "cut"], as_index=False)["head"].sum()
            .rename(columns={"head": "wtd"}))
    cp["order"] = cp["cut"].map(CUT_ORDER)
    return cp.sort_values(["week", "weekday", "order"]).reset_index(drop=True)


def _front_of(cps: pd.DataFrame, week, weekday, order, wtd_now) -> float:
    """The previous checkpoint's share of this one, within one past week."""
    if not wtd_now:
        return float("nan")
    w = cps[cps["week"] == week].sort_values(["weekday", "order"])
    before = w[(w["weekday"] < weekday) |
               ((w["weekday"] == weekday) & (w["order"] < order))]
    if before.empty:
        return float("nan")
    return float(before.iloc[-1]["wtd"]) / float(wtd_now)


def forecast_5area(vol: pd.DataFrame, published5: pd.Series) -> dict:
    """
    Where Monday's 5-Area negotiated head is likely to land, given the
    week-to-date USDA has published so far.

    The week's final is known exactly once Friday's morning file lands; until
    then the gap is whatever trades after the last cut. That is estimated from
    the SAME CHECKPOINT in past weeks -- a Friday 1:30 pm cut is compared only
    against other Friday 1:30 pm cuts, because how much of a week is still to
    come depends entirely on how far into it you are standing.

    Past weeks' finals come from published5, not from the daily frame. The two
    are identical (see weekly_5area_head), but the published series exists for
    every week whether or not the daily window reaches back that far.

    THE ANALOGUES ARE NARROWED BY HOW FRONT-LOADED THE WEEK IS, which is the
    difference between a usable estimate and a useless one. Late-Friday trade
    ran a median 2,860 head across weeks already ~90% done by Thursday, against
    a median 7,330 over all weeks and 50,330 in the worst back-loaded one. The
    observable proxy is the previous checkpoint's share of the current one:
    high means the market has gone quiet, low means it is trading right now.

    Narrowing on WEEK MATURITY instead -- week-to-date against a typical recent
    week -- is the obvious alternative and is WORSE, 12.2% median absolute
    error against front-loading's 7.8% over the same 52 weeks, with band
    coverage falling from 65% to 50%. Tried 2026-10-02; do not swap them. A
    low maturity says the week is quiet but not whether it has finished being
    quiet, and those are different questions. It earns its keep as the
    reliability label below, where it beats front-loading outright.
    """
    cps = wtd_checkpoints(vol)
    if cps.empty or published5.empty:
        return {}
    cur_week = cps["week"].max()
    this = cps[cps["week"] == cur_week].sort_values(["weekday", "order"])
    if this.empty:
        return {}
    cp = this.iloc[-1]
    wtd_now = float(cp["wtd"])

    # Friday's final IS the week -- there is nothing left to estimate, and the
    # tab says so rather than printing a forecast of a number already known.
    done = bool(cp["weekday"] == 4 and cp["cut"] == "morning")

    prior = this.iloc[-2] if len(this) > 1 else None
    front = (float(prior["wtd"]) / wtd_now) if (prior is not None and wtd_now > 0) else None

    hist = cps[(cps["week"] < cur_week) & (cps["weekday"] == cp["weekday"]) &
               (cps["cut"] == cp["cut"])].copy()
    hist["final"] = hist["week"].map(published5)
    hist = hist.dropna(subset=["final"])
    hist = hist[hist["wtd"] > 0].copy()
    hist["late"] = hist["final"] - hist["wtd"]
    # A negative "late" is USDA revising the week down, which happens rarely and
    # is not a shape to project forward onto a cumulative count.
    hist = hist[hist["late"] >= 0]

    pool, narrowed = hist, False
    if front is not None and not hist.empty:
        hist["front"] = [
            _front_of(cps, r.week, r.weekday, r.order, r.wtd)
            for r in hist.itertuples()
        ]
        near = hist[hist["front"].notna() & ((hist["front"] - front).abs() <= 0.10)]
        if len(near) >= 5:
            pool, narrowed = near, True

    # HOW FAR INTO THE WEEK WE ARE STANDING IS THE ACCURACY, and it is worth
    # saying out loud rather than printing one number with one error bar.
    # Backtested over 52 Friday-1:30 checkpoints, split into quartiles by how
    # much had already traded: the busiest quartile lands within a median 3%
    # and its p10-p90 band holds the answer 92% of the time; the quietest
    # quartile is a median 36% out and its band holds 38%. Same method, same
    # band, utterly different thing to hand someone.
    #
    # Maturity, not raw head, because a 45,000-head week in March is a full
    # week and in August is half of one. MATURITY IS A LABEL HERE AND NOT A
    # SELECTOR -- picking analogues on it was tried and is worse than picking
    # on front-loading (median absolute error 12.2% against 7.8% over the same
    # 52 weeks), which is why the pool above is still chosen on `front`.
    prior_weeks = published5[published5.index < cur_week]
    typical = float(prior_weeks.tail(13).median()) if len(prior_weeks) else float("nan")
    maturity = (wtd_now / typical) if typical and typical == typical else float("nan")
    if done:
        grade = "final"
    elif maturity != maturity:
        grade = "unknown"
    elif maturity >= 0.85:
        grade = "firm"
    elif maturity >= 0.50:
        grade = "provisional"
    else:
        grade = "weak"

    base = {"wtd": wtd_now, "checkpoint": cp, "done": done, "front": front,
            "narrowed": narrowed, "week": cur_week, "maturity": maturity,
            "typical": typical, "grade": grade}
    if pool.empty or done:
        return {**base, "n": int(len(pool)), "central": wtd_now,
                "low": wtd_now, "high": wtd_now, "late_median": 0.0}

    late = pool["late"]
    return {**base, "n": int(len(pool)),
            "central": wtd_now + float(late.median()),
            "low": wtd_now + float(late.quantile(0.10)),
            "high": wtd_now + float(late.quantile(0.90)),
            "late_median": float(late.median())}


def forecast_national(f5: dict, published5: pd.Series, national: pd.Series) -> dict:
    """
    Carry a 5-Area figure across to the national print USDA publishes the same
    morning, using the recent gap between the two.

    THE GAP IS TAKEN ADDITIVELY, NOT AS A RATIO, and over a short trailing
    window -- see FORECAST_GAP_WEEKS for the backtest behind both choices. The
    gap is negotiated trade in states outside the five areas, plus (right now)
    the Kansas and TX/OK/NM trade USDA is withholding regionally while still
    counting it nationally. Neither part scales with the 5-Area number, which
    is why a ratio drifts whenever the 5-Area total is unusually high or low.
    """
    if not f5 or published5.empty or national.empty:
        return {}
    pair = pd.DataFrame({"h5": published5, "nat": national}).dropna().sort_index()
    if pair.empty:
        return {}
    pair["gap"] = pair["nat"] - pair["h5"]
    recent = pair.tail(FORECAST_GAP_WEEKS)["gap"]
    band = pair.tail(FORECAST_BAND_WEEKS)["gap"]
    if recent.empty:
        return {}
    gap = float(recent.median())
    return {"central": f5["central"] + gap,
            "low": f5["low"] + float(band.min()),
            "high": f5["high"] + float(band.max()),
            "gap": gap, "gap_lo": float(band.min()), "gap_hi": float(band.max()),
            "n": int(len(recent)), "pair": pair}


def daily_combined(df: pd.DataFrame) -> pd.DataFrame:
    """
    Head-count-weighted Steer+Heifer combine per trading day / region / cut /
    basis -- the same combine the weekly tab does, for the same reason: USDA
    publishes two classes and the page quotes one number.

    A row with a price but no head count cannot be weighted, so it is dropped
    rather than counted as zero head, which would silently delete a real print.
    """
    if df.empty:
        return df
    d = df.dropna(subset=["head", "price"]).copy()
    if d.empty:
        return pd.DataFrame()

    key = ["trade_date", "region", "cut", "basis"]
    d["wp"] = d["head"] * d["price"]
    g = d.groupby(key, as_index=False).agg(head=("head", "sum"), wp=("wp", "sum"))
    g = g[g["head"] > 0].copy()
    if g.empty:
        return pd.DataFrame()
    g["price"] = g["wp"] / g["head"]
    g = g.drop(columns="wp")

    # Average weight is head-weighted as well, over only the rows that carry
    # one. A plain mean of the Steer and Heifer figures would weigh a 50-head
    # heifer lot the same as a 3,000-head steer lot, and USDA does not always
    # publish a weight alongside a price -- those rows must drop out of the
    # divisor too, not be counted as head with no weight.
    w = d.dropna(subset=["weight"]).copy()
    if w.empty:
        g["weight"] = float("nan")
        return g
    w["ww"] = w["head"] * w["weight"]
    wg = w.groupby(key, as_index=False).agg(hw=("head", "sum"), ww=("ww", "sum"))
    wg = wg[wg["hw"] > 0].copy()
    wg["weight"] = wg["ww"] / wg["hw"]
    return g.merge(wg[key + ["weight"]], on=key, how="left")


def daily_price_state(priced_rows, published_rows, suppressed=False):
    """
    Which of four things a region's price tile is saying on one trading day.

    Returns (state, row): "priced" and the print to headline, or one of
    "withheld", "undefined", "unpublished" and None.

    `priced_rows` is the region's daily_combined() rows for the day -- averages
    only, the unpriced ones already dropped. `published_rows` is its raw
    fetch_daily_cash() rows, which KEEP the unpriced ones, and asking both is
    the only way to tell a file USDA never published from one it published
    blank. Reading the combined frame alone collapses those two into a single
    "Undefined", which is what this exists to stop.

    THE PRINT TO HEADLINE IS LIVE FOB IF IT TRADED, ELSE DRESSED; final cut
    preferred over the 1:30 pm cut.

    IT MUST FALL BACK TO DRESSED. Some days trade dressed only -- Tuesday
    09/22/2026 was one, its entire national print being Nebraska 2,349 steers
    and 550 heifers at 350.00 dressed with no live FOB anywhere. Headlining
    Live FOB alone put "Undefined" on all four tiles under that day's own
    heading, which reads as "nothing traded" when nearly 2,900 head did. The
    tile names the basis for that reason: on a mixed day the four tiles are not
    all the same quote.

    "UNDEFINED" IS USDA'S OWN MARKET TEST AND STAYS. On a genuine quiet day it
    is the right word and the 09/22/2026 day above is the case it was written
    for. It is simply not what a WITHHELD region is doing: USDA has the trade,
    is publishing the file, and is holding the number back under LMR
    confidentiality. Calling that "no confirmed trade" says nobody traded in
    Texas since June, which is false.

    THE DISCRIMINATOR IS THE VOLUME FLAG, NOT A SECOND RUN DETECTOR ON PRICES.
    `suppressed` comes from weekly_to_date(); the two panels headline the same
    `last_trade`, so they line up by construction. Measured over
    2024-01-01..2026-10-02, a blank week-to-date volume NEVER coincides with a
    published price: 0 counterexamples in 2,833 region-trading-days, every
    region. So the flag can only ever fire on a day whose price is blank
    anyway, which makes reusing it strictly conservative -- it cannot overwrite
    a real print. The converse is common and must stay "undefined": 316 days
    carry a week-to-date volume with no price that day, because the region
    traded earlier in the week and was quiet on it.

    The threshold behind the flag transfers. Blank-PRICE runs over the same
    window end at 6 for an ordinary quiet stretch (TX/OK/NM; 4 elsewhere) and
    run 33, 36 and 63 where the region went dark, so SUPPRESSION_RUN_DAYS sits
    in that gap on this series as well as on the volume one.

    `suppressed` defaults False, and a caller with no volume for the region
    must leave it there: the tile falls back to USDA's own word rather than to
    a claim about USDA that nothing has established.
    """
    for basis in ("Live FOB", "Dressed Delivered"):
        b = priced_rows[priced_rows["basis"] == basis]
        for cut in ("morning", "afternoon"):
            hit = b[b["cut"] == cut]
            if not hit.empty:
                return "priced", hit.iloc[0]
    if published_rows is None or published_rows.empty:
        return "unpublished", None
    return ("withheld" if suppressed else "undefined"), None


# ── Load Data ────────────────────────────────────────────────────────────────

with st.spinner("Loading full USDA cash cattle trade history…"):
    try:
        # One probe for the whole page; each fetch keys on only its own reports.
        _probe = publication_stamps()
        price_df = fetch_price_history(stamps_for(_probe, [CT150_ID]))
        vol_df = fetch_volume_history(stamps_for(_probe, [CT154_ID]))
        load_ok, err_msg = True, ""
    except Exception as e:
        _probe = PROBE_FAILED
        load_ok, err_msg = False, str(e)
        price_df, vol_df = pd.DataFrame(), pd.DataFrame()


# ── Header ───────────────────────────────────────────────────────────────────

c1, c2 = st.columns([7, 3])
with c1:
    st.markdown(
        '<div class="dash-header">'
        f'<div class="dash-header-logo"><img src="{JSA_LOGO}"></div>'
        '<div class="dash-header-text">'
        '<h1>Cash Cattle Trade Dashboard</h1>'
        '<div class="subtitle">5-Area weighted-average FOB/Delivered prices and national negotiated cash trade volume</div>'
        '</div></div>',
        unsafe_allow_html=True,
    )

last_price_date = price_df["report_date"].max() if not price_df.empty else None
last_vol_date = vol_df["report_date"].max() if not vol_df.empty else None

with c2:
    meta = []
    if last_price_date is not None:
        meta.append(f"LM_CT150: <b>{last_price_date.strftime('%b %d, %Y')}</b>")
    if last_vol_date is not None:
        meta.append(f"LM_CT154: <b>{last_vol_date.strftime('%b %d, %Y')}</b>")
    st.markdown('<div class="dash-header-meta">' + "<br>".join(meta) + '</div>', unsafe_allow_html=True)


# ── Tabs ─────────────────────────────────────────────────────────────────────────
# Weekly is the main page and displays first; Daily is the second view.
#
# NEITHER BRANCH CALLS st.stop(). st.stop() halts the WHOLE script, so a weekly
# LM_CT150 outage would blank the Daily tab too -- different reports, published
# on a different clock, perfectly healthy. Commit 19d2ee0 fixed this same trap
# on the COF Recap tab and CLAUDE.md records it. Dropping st.stop() also means
# the sidebar renders during an outage, so the "use Refresh now in the sidebar"
# that the warning offers is actually reachable -- it was not before.
#
# And the hidden-tab rule: a hidden tab is hidden, NOT skipped. The Daily block
# runs on every rerun whether or not anyone opens it, which is why its fetch is
# one cached range request per region rather than one per day.
tab_weekly, tab_daily, tab_fcst = st.tabs(
    ["Weekly Cash Trade Averages", "Daily Cash Trade", "Monday Print Forecast"])

with tab_weekly:
    if not load_ok:
        st.warning(
            "⏳ **USDA data temporarily unavailable** — the USDA server is not responding. "
            "This usually resolves in a few minutes. Use **Refresh now** in the sidebar to retry."
        )
        with st.expander("Technical details"):
            st.code(err_msg)
    elif price_df.empty and vol_df.empty:
        st.warning("No data returned from USDA APIs.")
    else:
        # ── Section 1: Combined Steer & Heifer prices ───────────────────────────────

        st.markdown(
            '<div class="sec-header">Cash Cattle Prices — Combined Steer &amp; Heifer, Head-Count Weighted (LM_CT150, 5-Area)</div>',
            unsafe_allow_html=True,
        )

        combo = combine_steer_heifer(price_df) if not price_df.empty else pd.DataFrame()

        if combo.empty:
            st.info("No price data available.")
            fob_now = fob_wk = fob_yr = del_now = del_wk = del_yr = None
            fob_now_hd = del_now_hd = None
        else:
            fob_now, fob_now_hd = period_value(combo, last_price_date, "WEEKLY WEIGHTED AVERAGES", "Live")
            fob_wk, _ = period_value(combo, last_price_date, "SAME PERIOD LAST WEEK", "Live")
            fob_yr, _ = period_value(combo, last_price_date, "SAME PERIOD LAST YEAR", "Live")
            del_now, del_now_hd = period_value(combo, last_price_date, "WEEKLY WEIGHTED AVERAGES", "Dressed")
            del_wk, _ = period_value(combo, last_price_date, "SAME PERIOD LAST WEEK", "Dressed")
            del_yr, _ = period_value(combo, last_price_date, "SAME PERIOD LAST YEAR", "Dressed")

        st.markdown(f'<div class="sec-header" style="border-left-color:{FOB_COLOR};margin-top:6px;">Live FOB ($/cwt) — {fmt_hd(fob_now_hd)}</div>', unsafe_allow_html=True)
        cols = st.columns(3)
        with cols[0]:
            st.markdown(tile("This Week", fmt_price(fob_now), cls="tile-fob"), unsafe_allow_html=True)
        with cols[1]:
            st.markdown(tile("vs Week Ago", fmt_price(fob_wk), price_delta_html(fob_now, fob_wk), "tile-fob"), unsafe_allow_html=True)
        with cols[2]:
            st.markdown(tile("vs Year Ago", fmt_price(fob_yr), price_delta_html(fob_now, fob_yr), "tile-fob"), unsafe_allow_html=True)

        st.markdown(f'<div class="sec-header" style="border-left-color:{DEL_COLOR};">Dressed Delivered ($/cwt) — {fmt_hd(del_now_hd)}</div>', unsafe_allow_html=True)
        cols = st.columns(3)
        with cols[0]:
            st.markdown(tile("This Week", fmt_price(del_now), cls="tile-del"), unsafe_allow_html=True)
        with cols[1]:
            st.markdown(tile("vs Week Ago", fmt_price(del_wk), price_delta_html(del_now, del_wk), "tile-del"), unsafe_allow_html=True)
        with cols[2]:
            st.markdown(tile("vs Year Ago", fmt_price(del_yr), price_delta_html(del_now, del_yr), "tile-del"), unsafe_allow_html=True)

        st.markdown(
            '<div class="note" style="margin-top:6px;">Combined price = (Steer head count × Steer price + Heifer head count × '
            'Heifer price) ÷ total head count — a simple head-count-weighted average of USDA\'s own published Steer and Heifer '
            'weekly weighted averages. "This Week", "Week Ago" and "Year Ago" are the exact aligned periods USDA publishes '
            'alongside the current report.</div>',
            unsafe_allow_html=True,
        )


        # ── Price Trend Chart ────────────────────────────────────────────────────────

        st.markdown('<div class="sec-header">Weekly combined price trend</div>', unsafe_allow_html=True)

        AXIS = dict(gridcolor=BORDER, linecolor=BORDER, showgrid=True,
                    tickfont=dict(color=MUTED, size=11), title_font=dict(color=MUTED, size=11),
                    zeroline=False)

        if not combo.empty:
            trend = combo[combo["current_period"] == "WEEKLY WEIGHTED AVERAGES"].sort_values("report_date")
            fob_trend = trend[trend["selling_basis_desc"] == "Live"]
            del_trend = trend[trend["selling_basis_desc"] == "Dressed"]

            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=fob_trend["report_date"], y=fob_trend["combo_price"],
                name="Live FOB (combined)", mode="lines+markers",
                line=dict(color=FOB_COLOR, width=2), marker=dict(size=4),
                hovertemplate="<b>Live FOB</b>: $%{y:.2f}<extra></extra>",
            ))
            fig.add_trace(go.Scatter(
                x=del_trend["report_date"], y=del_trend["combo_price"],
                name="Dressed Delivered (combined)", mode="lines+markers",
                line=dict(color=DEL_COLOR, width=2), marker=dict(size=4),
                hovertemplate="<b>Dressed Delivered</b>: $%{y:.2f}<extra></extra>",
            ))

            _end = trend["report_date"].max()
            _start = _end - pd.Timedelta(days=3 * 365) if pd.notna(_end) else None

            fig.add_layout_image(dict(
                source=JSA_LOGO, xref="paper", yref="paper",
                x=0.5, y=0.5, sizex=0.5, sizey=0.5,
                xanchor="center", yanchor="middle", sizing="contain",
                opacity=WATERMARK_OPACITY, layer="below",
            ))
            fig.update_layout(
                paper_bgcolor="#ffffff", plot_bgcolor="#ffffff",
                font=dict(color=JPSI_DARK, size=11), hovermode="x unified",
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1,
                            font=dict(color=JPSI_DARK, size=11), bgcolor="rgba(0,0,0,0)"),
                margin=dict(l=55, r=20, t=15, b=40),
                xaxis=dict(
                    **AXIS, title="",
                    range=[_start, _end] if _start is not None else None,
                    rangeselector=dict(
                        buttons=[
                            dict(count=6, label="6M", step="month", stepmode="backward"),
                            dict(count=1, label="YTD", step="year", stepmode="todate"),
                            dict(count=1, label="1Y", step="year", stepmode="backward"),
                            dict(count=3, label="3Y", step="year", stepmode="backward"),
                            dict(count=10, label="10Y", step="year", stepmode="backward"),
                            dict(step="all", label="All"),
                        ],
                        bgcolor="#f6f8fa", activecolor=JPSI_BLUE,
                        font=dict(color=JPSI_DARK, size=10), bordercolor=BORDER,
                    ),
                    rangeslider=dict(visible=False), type="date",
                ),
                yaxis=dict(**AXIS, title="$/cwt", tickprefix="$"),
                height=400,
            )
            st.plotly_chart(fig, width="stretch")
        else:
            st.info("No price trend data available.")


        # ── Steer / Heifer detail table ─────────────────────────────────────────────

        with st.expander("📋  Steer / Heifer / Combined detail — this week, week ago, year ago"):
            if price_df.empty:
                st.info("No data.")
            else:
                detail = price_df[price_df["report_date"] == last_price_date].copy()
                detail["Class"] = detail["class_description"]
                detail["Period"] = detail["current_period"].map(PERIOD_LABEL)
                detail["Basis"] = detail["selling_basis_desc"].map(BASIS_LABEL)
                detail = detail.rename(columns={"head_count": "Head Count", "weight_range_avg": "Avg Weight",
                                                 "weighted_avg_price": "Wtd Avg Price"})

                combo_detail = combo[combo["report_date"] == last_price_date].copy()
                combo_detail["Class"] = "Combined (Steer+Heifer)"
                combo_detail["Period"] = combo_detail["current_period"].map(PERIOD_LABEL)
                combo_detail["Basis"] = combo_detail["selling_basis_desc"].map(BASIS_LABEL)
                combo_detail = combo_detail.rename(columns={"head_count": "Head Count", "combo_price": "Wtd Avg Price"})
                combo_detail["Avg Weight"] = float("nan")

                full = pd.concat([
                    detail[["Period", "Basis", "Class", "Head Count", "Avg Weight", "Wtd Avg Price"]],
                    combo_detail[["Period", "Basis", "Class", "Head Count", "Avg Weight", "Wtd Avg Price"]],
                ], ignore_index=True)

                period_order = {"This Week": 0, "Week Ago": 1, "Year Ago": 2}
                class_order = {"Steer": 0, "Heifer": 1, "Combined (Steer+Heifer)": 2}
                full["_p"] = full["Period"].map(period_order)
                full["_c"] = full["Class"].map(class_order)
                full = full.sort_values(["_p", "Basis", "_c"]).drop(columns=["_p", "_c"]).reset_index(drop=True)

                full["Head Count"] = full["Head Count"].apply(lambda v: f"{v:,.0f}" if pd.notna(v) else "—")
                full["Avg Weight"] = full["Avg Weight"].apply(lambda v: f"{v:,.0f}" if pd.notna(v) else "—")
                full["Wtd Avg Price"] = full["Wtd Avg Price"].apply(lambda v: f"${v:.2f}" if pd.notna(v) else "—")

                st.dataframe(full, width="stretch", height=380, hide_index=True)


        # ── Section 2: Negotiated cash trade volume ─────────────────────────────────

        st.markdown(
            '<div class="sec-header">Negotiated Cash Trade Volume — National (LM_CT154)</div>',
            unsafe_allow_html=True,
        )

        if vol_df.empty:
            st.info("No volume data available.")
            conf_now = conf_wk = conf_yr = d14_now = d14_wk = d30_now = d30_wk = None
            narrative = None
        else:
            latest_vol = vol_df.iloc[-1]
            conf_now, conf_wk, conf_yr = latest_vol["total_head_count"], latest_vol["head_count_week_ago"], latest_vol["head_count_year_ago"]
            d14_now, d14_wk = latest_vol["total_head_count_1"], latest_vol["head_count_week_ago_1"]
            d30_now, d30_wk = latest_vol["total_head_count_2"], latest_vol["head_count_week_ago_2"]
            narrative = latest_vol["trend"]

        cols = st.columns(3)
        with cols[0]:
            st.markdown(tile("Total Confirmed — This Week", fmt_hd(conf_now), cls="tile-conf"), unsafe_allow_html=True)
        with cols[1]:
            st.markdown(tile("vs Week Ago", fmt_hd(conf_wk), hd_delta_html(conf_now, conf_wk), "tile-conf"), unsafe_allow_html=True)
        with cols[2]:
            st.markdown(tile("vs Year Ago", fmt_hd(conf_yr), hd_delta_html(conf_now, conf_yr), "tile-conf"), unsafe_allow_html=True)

        cols = st.columns(4)
        with cols[0]:
            st.markdown(tile("1-14 Day Delivery — This Week", fmt_hd(d14_now), cls="tile-d14"), unsafe_allow_html=True)
        with cols[1]:
            st.markdown(tile("1-14 Day vs Week Ago", fmt_hd(d14_wk), hd_delta_html(d14_now, d14_wk), "tile-d14"), unsafe_allow_html=True)
        with cols[2]:
            st.markdown(tile("15-30 Day Delivery — This Week", fmt_hd(d30_now), cls="tile-d30"), unsafe_allow_html=True)
        with cols[3]:
            st.markdown(tile("15-30 Day vs Week Ago", fmt_hd(d30_wk), hd_delta_html(d30_now, d30_wk), "tile-d30"), unsafe_allow_html=True)

        st.markdown(
            '<div class="note" style="margin-top:6px;">USDA does not publish a year-ago figure for the 1-14 day / 15-30 day '
            'delivery windows — only for total confirmed trade — so those two rows compare to week-ago only, matching the source report.</div>',
            unsafe_allow_html=True,
        )

        if narrative:
            st.markdown('<div class="sec-header">This week\'s market narrative</div>', unsafe_allow_html=True)
            st.markdown(f'<div class="narrative">{narrative}</div>', unsafe_allow_html=True)


        # ── Volume Trend Chart ───────────────────────────────────────────────────────

        st.markdown('<div class="sec-header">Weekly negotiated cash trade volume trend</div>', unsafe_allow_html=True)

        if not vol_df.empty:
            fig2 = go.Figure()
            fig2.add_trace(go.Scatter(
                x=vol_df["report_date"], y=vol_df["total_head_count"],
                name="Total Confirmed", mode="lines+markers",
                line=dict(color=CONF_COLOR, width=2), marker=dict(size=4),
                hovertemplate="<b>Total Confirmed</b>: %{y:,.0f} hd<extra></extra>",
            ))
            fig2.add_trace(go.Scatter(
                x=vol_df["report_date"], y=vol_df["total_head_count_1"],
                name="1-14 Day Delivery", mode="lines+markers",
                line=dict(color=D14_COLOR, width=2), marker=dict(size=4),
                hovertemplate="<b>1-14 Day</b>: %{y:,.0f} hd<extra></extra>",
            ))
            fig2.add_trace(go.Scatter(
                x=vol_df["report_date"], y=vol_df["total_head_count_2"],
                name="15-30 Day Delivery", mode="lines+markers",
                line=dict(color=D30_COLOR, width=2), marker=dict(size=4),
                hovertemplate="<b>15-30 Day</b>: %{y:,.0f} hd<extra></extra>",
            ))

            _vend = vol_df["report_date"].max()
            _vstart = _vend - pd.Timedelta(days=2 * 365) if pd.notna(_vend) else None

            fig2.add_layout_image(dict(
                source=JSA_LOGO, xref="paper", yref="paper",
                x=0.5, y=0.5, sizex=0.5, sizey=0.5,
                xanchor="center", yanchor="middle", sizing="contain",
                opacity=WATERMARK_OPACITY, layer="below",
            ))
            fig2.update_layout(
                paper_bgcolor="#ffffff", plot_bgcolor="#ffffff",
                font=dict(color=JPSI_DARK, size=11), hovermode="x unified",
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1,
                            font=dict(color=JPSI_DARK, size=11), bgcolor="rgba(0,0,0,0)"),
                margin=dict(l=55, r=20, t=15, b=40),
                xaxis=dict(
                    **AXIS, title="",
                    range=[_vstart, _vend] if _vstart is not None else None,
                    rangeselector=dict(
                        buttons=[
                            dict(count=6, label="6M", step="month", stepmode="backward"),
                            dict(count=1, label="YTD", step="year", stepmode="todate"),
                            dict(count=1, label="1Y", step="year", stepmode="backward"),
                            dict(count=5, label="5Y", step="year", stepmode="backward"),
                            dict(step="all", label="All"),
                        ],
                        bgcolor="#f6f8fa", activecolor=JPSI_BLUE,
                        font=dict(color=JPSI_DARK, size=10), bordercolor=BORDER,
                    ),
                    rangeslider=dict(visible=False), type="date",
                ),
                yaxis=dict(**AXIS, title="Head Count"),
                height=380,
            )
            st.plotly_chart(fig2, width="stretch")
        else:
            st.info("No volume trend data available.")


        # ── Data Tables ────────────────────────────────────────────────────────────

        with st.expander("📋  Weekly combined price history"):
            if combo.empty:
                st.info("No data.")
            else:
                trend = combo[combo["current_period"] == "WEEKLY WEIGHTED AVERAGES"].sort_values("report_date")
                piv = trend.pivot_table(index="report_date", columns="selling_basis_desc", values="combo_price").reset_index()
                piv = piv.rename(columns={"report_date": "Week Of", "Live": "Live FOB", "Dressed": "Dressed Delivered"})
                piv["Week Of"] = piv["Week Of"].dt.strftime("%Y-%m-%d")
                piv = piv.sort_values("Week Of", ascending=False).reset_index(drop=True)
                st.dataframe(piv.style.format({"Live FOB": "${:.2f}", "Dressed Delivered": "${:.2f}"}, na_rep="—"),
                             width="stretch", height=320)

        with st.expander("📋  Weekly negotiated cash trade volume history"):
            if vol_df.empty:
                st.info("No data.")
            else:
                disp = vol_df.drop(columns="trend").copy()
                disp["report_date"] = disp["report_date"].dt.strftime("%Y-%m-%d")
                disp = disp.rename(columns={
                    "report_date": "Week Of", "total_head_count": "Confirmed", "head_count_week_ago": "Confirmed (Wk Ago)",
                    "head_count_year_ago": "Confirmed (Yr Ago)", "total_head_count_1": "1-14 Day",
                    "head_count_week_ago_1": "1-14 Day (Wk Ago)", "total_head_count_2": "15-30 Day",
                    "head_count_week_ago_2": "15-30 Day (Wk Ago)",
                }).sort_values("Week Of", ascending=False).reset_index(drop=True)
                st.dataframe(disp.style.format({c: "{:,.0f}" for c in disp.columns if c != "Week Of"}, na_rep="—"),
                             width="stretch", height=320)


with tab_daily:
    st.markdown(
        '<div class="sec-header">Daily Negotiated Cash Trade &mdash; by region, Steer &amp; Heifer combined</div>',
        unsafe_allow_html=True,
    )

    _win = st.segmented_control(
        "History window", list(DAILY_WINDOWS), default=DAILY_WINDOW_DEFAULT,
        key="daily_window", label_visibility="collapsed")
    _days = DAILY_WINDOWS.get(_win or DAILY_WINDOW_DEFAULT,
                              DAILY_WINDOWS[DAILY_WINDOW_DEFAULT])

    _end_d = datetime.now().date()
    _start_d = _end_d - timedelta(days=_days)

    with st.spinner("Loading USDA daily regional cash trade…"):
        try:
            _daily_slugs = [s for cuts in DAILY_REGIONS.values() for s in cuts.values()]
            _stamps = stamps_for(_probe, _daily_slugs)
            daily_df = fetch_daily_cash(_start_d.strftime("%m/%d/%Y"),
                                        _end_d.strftime("%m/%d/%Y"), _stamps)
            daily_vol = fetch_daily_volume(_start_d.strftime("%m/%d/%Y"),
                                           _end_d.strftime("%m/%d/%Y"), _stamps)
            daily_err = ""
        except Exception as e:
            _stamps = PROBE_FAILED
            daily_df, daily_vol, daily_err = pd.DataFrame(), pd.DataFrame(), str(e)

    # Show the publication stamp rather than a "last refreshed" clock. Our
    # refresh time says nothing useful -- USDA's does, and it is the number that
    # tells you whether a quiet page is quiet because nothing traded or because
    # the feed stopped.
    _pub = daily_last_published(_stamps)
    if _pub:
        st.markdown(
            f'<div class="note" style="margin:-4px 0 10px;">USDA last published '
            f'these reports <b>{html.escape(_pub)}</b>. This page follows that stamp, '
            f'so it picks up a release as soon as one lands rather than on a timer.'
            f'</div>', unsafe_allow_html=True)
    elif _stamps == PROBE_FAILED:
        st.markdown(
            '<div class="note" style="margin:-4px 0 10px;">Could not reach USDA\'s '
            'report index, so the figures below are whatever was last cached and '
            'may be behind a release.</div>', unsafe_allow_html=True)

    dcombo = daily_combined(daily_df)

    if daily_err:
        st.warning(
            "⏳ **USDA daily data unavailable** — the USDA server is not responding. "
            "Use **Refresh now** in the sidebar to retry."
        )
        with st.expander("Technical details"):
            st.code(daily_err)
    elif daily_df.empty:
        st.info("USDA published no daily reports for these regions in this window.")
    else:
        # The newest day USDA PUBLISHED, which is not the same as the newest day
        # that PRICED -- see the unpriced-rows note in fetch_daily_cash. Taking
        # it from dcombo instead would skip every no-trade day and head this
        # section with an older date, which is what made a Wednesday page read
        # "Monday" with nothing saying Tuesday had been published and was quiet.
        last_trade = daily_df["trade_date"].max()
        day = (dcombo[dcombo["trade_date"] == last_trade] if not dcombo.empty
               else pd.DataFrame(columns=["region", "basis", "cut", "head", "price"]))

        _priced = dcombo["trade_date"].max() if not dcombo.empty else None
        _quiet = _priced is not None and _priced < last_trade

        # COMPUTED HERE, DISPLAYED TWICE, AND THE ORDER IS THE POINT. The price
        # tiles below need the per-region `suppressed` flag, and the week-to-date
        # panel further down needs the whole dict. Script order decides what is
        # available, not the order things appear on screen (see the tabs rule in
        # CLAUDE.md), so this has to sit above the first of the two. Calling
        # weekly_to_date() twice would work and is worse: the two panels would
        # be free to disagree about which regions are withheld, which is exactly
        # the class of bug where both numbers are defensible and nothing raises.
        wtd = weekly_to_date(daily_vol, last_trade)

        st.markdown(
            f'<div class="sec-header" style="border-left-color:{FOB_COLOR};margin-top:6px;">'
            f'Latest trading day &mdash; {last_trade.strftime("%A, %b %d, %Y")} '
            f'($/cwt)</div>',
            unsafe_allow_html=True)

        if _quiet:
            # "No trade in any region" is a claim about EVERY region, so it has
            # to exclude the ones USDA is withholding. On a day where the
            # reporting regions are quiet and the others are suppressed, the old
            # wording asserted a silent Texas that is in fact trading.
            #
            # All four withheld gets its own sentence rather than a subtraction:
            # the region list would be empty and the sentence would read "no
            # confirmed negotiated trade in ." It is reachable -- _quiet means
            # nothing priced, which is exactly what four withheld regions look
            # like -- so it is written out rather than guarded against.
            _held_q = [r for r in DAILY_REGIONS
                       if (wtd.get(r) or {}).get("suppressed")] if wtd else []
            _open_q = [r for r in DAILY_REGIONS if r not in _held_q]
            _last_p = f'The last day that priced was <b>{_priced.strftime("%A, %b %d, %Y")}</b>.'
            if not _held_q:
                _msg = f'USDA published this day with no confirmed negotiated trade in any region. {_last_p}'
            elif not _open_q:
                _msg = (f'USDA is withholding every region for confidentiality on this day, so '
                        f'there is no published price anywhere. {_last_p}')
            else:
                _msg = (f'USDA published this day with no confirmed negotiated trade in '
                        f'{and_list(_open_q)}. It is withholding {and_list(_held_q)} for '
                        f'confidentiality, so '
                        f'{"those regions are" if len(_held_q) > 1 else "that region is"} '
                        f'not part of that statement. {_last_p}')
            st.markdown(
                f'<div class="note" style="margin:-6px 0 12px;">{_msg}</div>',
                unsafe_allow_html=True)

        # One tile per region: the final print where USDA has closed the day
        # out, otherwise the 1:30 pm cut, labelled so the two are never
        # confused. The decision is daily_price_state() at module level, where
        # a test can reach it -- this block only renders what it returns.
        #
        # THREE WAYS TO HAVE NO PRICE, AND THEY ARE DIFFERENT NEWS. "Undefined"
        # is USDA's own market test and is right on a quiet day; it is wrong for
        # a region whose trade USDA is withholding, which is what Kansas and
        # TX/OK/NM have been doing since 08/14 and 06/26/2026. The captions stay
        # short because .tile-delta-neu is nowrap and four tiles share the row;
        # the reason goes in the footnote, which has space for it.
        _PRICE_BLANK = {
            "withheld":    ("—", "withheld by USDA"),
            "undefined":   ("Undefined", "no confirmed trade"),
            "unpublished": ("—", "not published"),
        }
        cols = st.columns(len(DAILY_REGIONS))
        for col, region in zip(cols, DAILY_REGIONS):
            _entry = wtd.get(region) if wtd else None
            state, row = daily_price_state(
                day[day["region"] == region],
                daily_df[(daily_df["trade_date"] == last_trade)
                         & (daily_df["region"] == region)],
                suppressed=bool(_entry and _entry["suppressed"]),
            )
            with col:
                if row is None:
                    _val, _why = _PRICE_BLANK[state]
                    st.markdown(
                        tile(region, _val,
                             f'<div class="tile-delta-neu">{_why}</div>',
                             "tile-neu"),
                        unsafe_allow_html=True)
                else:
                    basis_short = "Live FOB" if row["basis"] == "Live FOB" else "Dressed"
                    st.markdown(
                        tile(region, fmt_price(row["price"]),
                             f'<div class="tile-delta-neu">{fmt_hd(row["head"])} '
                             f'&middot; {basis_short}, {DAILY_CUT_LABEL[row["cut"]]}</div>',
                             "tile-fob" if row["basis"] == "Live FOB" else "tile-del"),
                        unsafe_allow_html=True)

        # ── Both cuts, side by side ──────────────────────────────────────────
        st.markdown(
            '<div class="sec-header">Both cuts of the same trading day</div>',
            unsafe_allow_html=True)

        grid = []
        for region in DAILY_REGIONS:
            reg = day[day["region"] == region]
            entry = {"Region": region}
            for basis, short in (("Live FOB", "Live FOB"),
                                 ("Dressed Delivered", "Dressed")):
                for cut in ("afternoon", "morning"):
                    m = reg[(reg["basis"] == basis) & (reg["cut"] == cut)]
                    entry[f"{short} {DAILY_CUT_LABEL[cut]}"] = (
                        fmt_price(m.iloc[0]["price"]) if not m.empty else "—")
            # Head across BOTH bases, not Live FOB alone -- on a dressed-only
            # day (see _headline) a live-only count reads "—" for a region that
            # actually traded thousands of head.
            fin = reg[reg["cut"] == "morning"]
            entry["Head (final)"] = (
                fmt_hd(fin["head"].sum()) if not fin.empty else "—")
            grid.append(entry)
        st.dataframe(pd.DataFrame(grid), width="stretch", hide_index=True)

        # ── Week to date ─────────────────────────────────────────────────────
        # `wtd` is built above the price tiles, which share its suppressed flag.
        if wtd:
            st.markdown(
                f'<div class="sec-header" style="border-left-color:{CONF_COLOR};">'
                f'Negotiated cash volume, week to date &mdash; through '
                f'{last_trade.strftime("%A, %b %d")}</div>',
                unsafe_allow_html=True)

            # The 5-Area total leads as a line rather than a fifth tile. Five
            # tiles across is one too many: at a narrow window each is about
            # 80px, which is where the region labels start breaking mid-word.
            # Four also keeps this row the same shape as the price row above.
            _tot = wtd.get("_total")
            if _tot is not None:
                _cmp = ""
                if _tot["week_ago"] is not None:
                    _d = _tot["head"] - _tot["week_ago"]
                    _arrow = "▲" if _d > 0 else ("▼" if _d < 0 else "")
                    _col = POS if _d > 0 else (NEG if _d < 0 else MUTED)
                    _cmp = (f' <span style="color:{_col};font-weight:600;">{_arrow} '
                            f'{abs(_d):,.0f} hd</span> against {_tot["week_ago"]:,.0f} hd '
                            f'at the same point last week')
                # Name what the total is actually made of while a region is
                # withheld. The figure is still USDA's -- their 5-Area drops a
                # withheld region too -- but "5-Area" invites the reader to
                # assume five regions are in it, and right now two are not.
                _held = ""
                if _tot["withheld"]:
                    _held = (f' USDA is withholding {and_list(_tot["withheld"])} for '
                             f'confidentiality and leaves '
                             f'{"them" if len(_tot["withheld"]) > 1 else "it"} out of its '
                             f'own 5-Area figure as well, so this is '
                             f'{and_list(_tot["counted"])}.')
                st.markdown(
                    f'<div style="font-size:0.95rem;color:{JPSI_DARK};margin:-4px 0 12px;">'
                    f'<b>5-Area total {_tot["head"]:,.0f} head</b>{_cmp}.{_held}</div>',
                    unsafe_allow_html=True)

            cols = st.columns(len(DAILY_REGIONS))
            for col, region in zip(cols, DAILY_REGIONS):
                entry = wtd.get(region)
                with col:
                    if entry is None:
                        st.markdown(
                            tile(region, "—",
                                 '<div class="tile-delta-neu">not published</div>',
                                 "tile-neu"),
                            unsafe_allow_html=True)
                    elif entry["head"] is None:
                        # USDA published the file and left the volume blank.
                        # "0 head" here is a number USDA never prints and reads
                        # as "nobody traded" -- see weekly_to_date. Only a
                        # sustained blank is called withheld; a short one is
                        # indistinguishable from a quiet day and says so.
                        #
                        # Both captions are kept short enough not to overflow
                        # the tile at a narrow window, which the nowrap in
                        # .tile-delta-neu makes a real constraint. The reason a
                        # region is withheld goes on the 5-Area line above and
                        # in the footnote below, which have room for it.
                        _why = ("withheld by USDA"
                                if entry["suppressed"] else "no volume published")
                        st.markdown(
                            tile(region, "—",
                                 f'<div class="tile-delta-neu">{_why}</div>',
                                 "tile-neu"),
                            unsafe_allow_html=True)
                    else:
                        st.markdown(
                            tile(region, fmt_hd(entry["head"]),
                                 hd_delta_html(entry["head"], entry["week_ago"]),
                                 "tile-d14"),
                            unsafe_allow_html=True)

            st.markdown(
                '<div class="note" style="margin-top:6px;">Cumulative negotiated cash head '
                'from Monday through the trading day above, against the running total at the '
                'same point last week &mdash; USDA&rsquo;s own week-to-date line, not a sum computed '
                'here. <b>This counts more cattle than the prices above.</b> The averages are '
                'Steer and Heifer on Live FOB and Dressed Delivered only; this is every class '
                'and all four selling bases, so it is the size of the week&rsquo;s trade rather than '
                'the head behind those quotes. The 5-Area figure is the four regions added up, '
                'which reproduces USDA&rsquo;s own 5-Area total exactly. '
                '<b>A region shown as withheld is absent from that total</b> &mdash; USDA '
                'publishes the report with the head count blank when too few buyers reported '
                'to disclose it, and drops it from its own 5-Area figure the same way, so the '
                'total is the regions named above it and not the whole 5-Area trade. That '
                'cattle is still counted in the national confirmed negotiated figure on the '
                'Weekly tab, which is why the two have diverged.</div>',
                unsafe_allow_html=True)

        # ── Daily trend ──────────────────────────────────────────────────────
        st.markdown(
            '<div class="sec-header">Daily Live FOB by region &mdash; final prints</div>',
            unsafe_allow_html=True)

        # A local axis dict rather than the weekly tab's AXIS: that one is built
        # inside the weekly branch, which does not run when LM_CT150 is down.
        DAXIS = dict(gridcolor=BORDER, linecolor=BORDER, showgrid=True,
                     tickfont=dict(color=MUTED, size=11),
                     title_font=dict(color=MUTED, size=11), zeroline=False)

        line = (dcombo[(dcombo["basis"] == "Live FOB") & (dcombo["cut"] == "morning")]
                if not dcombo.empty else dcombo)
        if line.empty:
            st.info("No final Live FOB prints in this window.")
        else:
            fig_d = go.Figure()
            for region in DAILY_REGIONS:
                s = line[line["region"] == region].sort_values("trade_date")
                if s.empty:
                    continue
                fig_d.add_trace(go.Scatter(
                    x=s["trade_date"], y=s["price"], name=region,
                    mode="lines+markers",
                    line=dict(color=DAILY_REGION_COLORS.get(region, MUTED), width=2),
                    marker=dict(size=4),
                    hovertemplate=f"<b>{region}</b>: $%{{y:.2f}}<extra></extra>"))
            fig_d.add_layout_image(dict(
                source=JSA_LOGO, xref="paper", yref="paper", x=0.5, y=0.5,
                sizex=0.5, sizey=0.5, xanchor="center", yanchor="middle",
                sizing="contain", opacity=WATERMARK_OPACITY, layer="below"))
            fig_d.update_layout(
                paper_bgcolor="#ffffff", plot_bgcolor="#ffffff",
                font=dict(color=JPSI_DARK, size=11), hovermode="x unified",
                legend=dict(orientation="h", yanchor="bottom", y=1.02,
                            xanchor="right", x=1,
                            font=dict(color=JPSI_DARK, size=11),
                            bgcolor="rgba(0,0,0,0)"),
                margin=dict(l=55, r=20, t=15, b=40),
                xaxis=dict(**DAXIS, title="", type="date"),
                yaxis=dict(**DAXIS, title="$/cwt", tickprefix="$"),
                height=400)
            st.plotly_chart(fig_d, width="stretch")

        # ── Detail ───────────────────────────────────────────────────────────
        with st.expander("\U0001f4cb  Daily detail — every print in the window, both cuts"):
            if dcombo.empty:
                st.info("USDA published in this window but nothing priced.")
            else:
                det = dcombo.copy()
                det["Trading Day"] = det["trade_date"].dt.strftime("%Y-%m-%d")
                det["Cut"] = det["cut"].map(DAILY_CUT_LABEL)
                det = det.rename(columns={"region": "Region", "basis": "Basis",
                                          "head": "Head", "weight": "Avg Weight",
                                          "price": "Wtd Avg Price"})
                det = det[["Trading Day", "Region", "Basis", "Cut",
                           "Head", "Avg Weight", "Wtd Avg Price"]]
                st.dataframe(
                    det.sort_values(["Trading Day", "Region"], ascending=[False, True]),
                    width="stretch", hide_index=True)

    st.markdown(
        '<div class="note" style="margin-top:10px;">'
        '<b>Two files a day, one trading day apart.</b> USDA publishes each region twice: an '
        'afternoon file (~2:55 pm CT) carrying that day\'s trade as of the 1:30 pm cut, and a '
        'morning file (median 11:17 CT) that finalises the <i>previous</i> business day. The morning '
        'file is dated the day it is published, so this page shifts it back one business day &mdash; '
        '&ldquo;Final&rdquo; and &ldquo;1:30 pm cut&rdquo; above are the same trading day, not the '
        'same file.<br><br>'
        '<b>Colorado is not shown.</b> USDA discontinued the Colorado daily reports &mdash; the '
        'afternoon file (LM_CT133) last published 27 Jun 2023 and the summary (LM_CT134) 5 Jul 2024, '
        'and the API has returned nothing for either since. Colorado is still inside the 5-Area '
        'weekly average on the Weekly tab.<br><br>'
        '<b>Week to date</b> is USDA&rsquo;s own cumulative negotiated cash head from Monday, read from each report&rsquo;s Summary section. It counts every class and all four selling bases, so it is a wider count than the Steer/Heifer Live-FOB-and-Dressed averages above and will not tie to them. The 5-Area figure is the four regions summed, which reproduces USDA&rsquo;s own 5-Area week-to-date exactly.<br><br>'
        '<b>&ldquo;Undefined&rdquo;</b> is USDA\'s own state when a region has too little confirmed '
        'trade to publish a market test &mdash; a real answer, not a failed fetch. Regions are '
        'routinely undefined early in the week.<br><br>'
        '<b>&ldquo;Withheld by USDA&rdquo; is not the same thing</b>, and the difference is the '
        'whole market. A withheld region traded; USDA is publishing the report with the price '
        'and the head count left blank because too few buyers reported to disclose them under '
        'LMR confidentiality. An undefined region is one USDA is telling you was quiet. The '
        'report itself cannot say which &mdash; the field is empty either way and USDA never '
        'prints a literal zero &mdash; so this page reads the length of the blank run. A '
        'few quiet days in a row is an ordinary stretch; a run reaching '
        f'{SUPPRESSION_RUN_DAYS} trading days is a region that has gone dark. '
        '<b>TX/OK/NM has published no daily price since 26 Jun 2026 and Kansas '
        'none since 14 Aug 2026.</b> That cattle is still counted in the national confirmed '
        'negotiated figure on the Weekly tab, which is why the two have diverged.<br><br>'
        'Negotiated cash only, Steer and Heifer combined head-count-weighted, &ldquo;Total all '
        'grades&rdquo;. Sources: <b>LM_CT117/118</b> (TX/OK/NM), <b>LM_CT120/121</b> (Kansas), '
        '<b>LM_CT123/124</b> (Nebraska), <b>LM_CT136/137</b> (Iowa/Minnesota) — prices from each report&rsquo;s Detail section, week-to-date head from its Summary. Cached until USDA republishes, checked every 5 minutes.'
        '</div>',
        unsafe_allow_html=True)


# ── Monday Print Forecast ────────────────────────────────────────────────────
# The third tab answers one question: what will USDA print on Monday for last
# week's negotiated volume? It gets there in two steps, and keeping them
# visibly separate is the point -- they fail differently and a reader needs to
# know which half is shaky.
#
#   week-to-date now  ->  5-Area weekly (LM_CT150)  ->  national (LM_CT154)
#
# THIS TAB ADDS NO WEEKLY REQUESTS. Both weekly series ride on fetches the page
# already makes: the 5-Area head count is a header field on the LM_CT150
# History call behind the price panel, and the national count is vol_df. Its
# one request set is the daily /Summary year below, which is cheap for the
# reason FORECAST_CAL_DAYS documents.
with tab_fcst:
    st.markdown(
        '<div class="sec-header">Monday Print Forecast &mdash; negotiated cash volume</div>',
        unsafe_allow_html=True)

    with st.spinner("Loading USDA daily history for the forecast…"):
        try:
            _f_slugs = [sl for cuts in DAILY_REGIONS.values() for sl in cuts.values()]
            _f_stamps = stamps_for(_probe, _f_slugs)
            _f_end = datetime.now().date()
            _f_start = _f_end - timedelta(days=FORECAST_CAL_DAYS)
            fcst_vol = fetch_daily_volume(_f_start.strftime("%m/%d/%Y"),
                                          _f_end.strftime("%m/%d/%Y"), _f_stamps)
            fcst_err = ""
        except Exception as e:
            fcst_vol, fcst_err = pd.DataFrame(), str(e)

    head5 = weekly_5area_head(price_df)
    headn = weekly_national_head(vol_df)
    f5 = forecast_5area(fcst_vol, head5) if not fcst_vol.empty else {}
    fn = forecast_national(f5, head5, headn) if f5 else {}

    if fcst_err:
        st.warning("⏳ **USDA daily data unavailable** — the forecast needs the daily "
                   "regional reports. Use **Refresh now** in the sidebar to retry.")
        with st.expander("Technical details"):
            st.code(fcst_err)
    elif not f5 or not fn:
        st.info("Not enough published history yet to build a forecast.")
    else:
        _cp = f5["checkpoint"]
        _dow = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"][int(_cp["weekday"])]
        _cut = DAILY_CUT_LABEL[_cp["cut"]]
        _wk = pd.Timestamp(f5["week"])
        _print_day = (_wk + pd.Timedelta(days=7)).strftime("%A, %b %d")

        st.markdown(
            f'<div class="note" style="margin:-4px 0 12px;">Trading week of '
            f'<b>{_wk.strftime("%b %d")}&ndash;{(_wk + pd.Timedelta(days=4)).strftime("%b %d, %Y")}</b>. '
            f'USDA last published the <b>{_dow} {_cut}</b> figure; the weekly reports '
            f'print <b>{_print_day}</b>.</div>', unsafe_allow_html=True)

        # ── the two headline numbers, with where they came from ─────────────
        c1, c2, c3, c4 = st.columns(4)
        _last_wk = _wk - pd.Timedelta(days=7)
        _prev5 = head5.get(_last_wk)
        _prevn = headn.get(_last_wk)
        with c1:
            st.markdown(tile("5-Area &mdash; week to date",
                             fmt_hd(f5["wtd"]),
                             f'<div class="tile-delta-neu">{_dow} {_cut}, published</div>',
                             "tile-conf"), unsafe_allow_html=True)
        with c2:
            st.markdown(tile("5-Area &mdash; forecast print",
                             fmt_hd(f5["central"]),
                             hd_delta_html(f5["central"], _prev5),
                             "tile-d14"), unsafe_allow_html=True)
        with c3:
            st.markdown(tile("National &mdash; forecast print",
                             fmt_hd(fn["central"]),
                             hd_delta_html(fn["central"], _prevn),
                             "tile-del"), unsafe_allow_html=True)
        with c4:
            st.markdown(tile("National &mdash; last week printed",
                             fmt_hd(_prevn),
                             f'<div class="tile-delta-neu">'
                             f'{_last_wk.strftime("%b %d")} week, actual</div>',
                             "tile-neu"), unsafe_allow_html=True)

        _GRADE = {
            "final": (POS, "The week is closed", "Friday&rsquo;s final file has landed, so the "
                      "5-Area figure below is not an estimate &mdash; it is the number."),
            "firm": (POS, "Firm", "The week has traded about as much as a normal week already, "
                     "which is the state this method is most reliable in: backtested over 52 "
                     "weeks, the busiest quarter of them land within a median 3% and the band "
                     "holds the answer 92% of the time."),
            "provisional": (D30_COLOR, "Provisional", "Roughly half to four-fifths of a normal "
                            "week is in. Comparable weeks land within a median 7&ndash;11%."),
            "weak": (NEG, "Weak &mdash; the week has not traded yet", "Only a small fraction of a "
                     "normal week is on the board, and most of the trade is still to come. "
                     "Comparable weeks were a median 36% out and the band held only 38% of the "
                     "time. Treat the number as a floor, not a forecast."),
            "unknown": (MUTED, "Unrated", "Not enough published weekly history to judge how far "
                        "through the week this is."),
        }
        _gc, _gl, _gt = _GRADE[f5["grade"]]
        _mat = f5.get("maturity")
        _mat_s = (f"{_mat:.0%} of a typical recent week ({fmt_hd(f5['typical'])})"
                  if _mat == _mat else "&mdash;")
        st.markdown(
            f'<div style="border-left:3px solid {_gc};background:#fafbfc;padding:8px 12px;'
            f'margin:4px 0 14px;font-size:0.8rem;line-height:1.55;color:{JPSI_DARK};">'
            f'<b style="color:{_gc};">Confidence: {_gl}.</b> {_gt}<br>'
            f'<span style="color:{MUTED};">Week to date is {_mat_s}.</span></div>',
            unsafe_allow_html=True)

        # ── step 1 ──────────────────────────────────────────────────────────
        st.markdown(
            f'<div class="sec-header" style="border-left-color:{CONF_COLOR};">'
            f'Step 1 &mdash; finishing the 5-Area week (LM_CT150)</div>',
            unsafe_allow_html=True)
        _front_s = f"{f5['front']:.0%}" if f5.get("front") is not None else "&mdash;"
        st.markdown(
            f'<div style="font-size:0.9rem;color:{JPSI_DARK};margin:-2px 0 4px;">'
            f'<b>{f5["wtd"]:,.0f} hd</b> confirmed through the {_dow} {_cut.lower()}, '
            f'plus an estimated <b>{f5["late_median"]:,.0f} hd</b> still to be reported '
            f'&rarr; <b>{f5["central"]:,.0f} hd</b>, with a likely range of '
            f'<b>{f5["low"]:,.0f}&ndash;{f5["high"]:,.0f} hd</b>.</div>',
            unsafe_allow_html=True)
        st.markdown(
            f'<div class="note" style="margin-bottom:14px;">The week-to-date is USDA&rsquo;s '
            f'own cumulative count, and the four daily regions summed at Friday&rsquo;s final '
            f'reproduce USDA&rsquo;s published 5-Area weekly figure <b>exactly</b> &mdash; checked '
            f'on every week the daily window covers. So the only unknown is trade reported '
            f'after the last cut, estimated from the <b>{f5["n"]}</b> past weeks standing at '
            f'the same point'
            + (f' with similar front-loading (the previous cut held {_front_s} of the current one)'
               if f5.get("narrowed") else ' in the week')
            + '.</div>', unsafe_allow_html=True)

        # ── step 2 ──────────────────────────────────────────────────────────
        st.markdown(
            f'<div class="sec-header" style="border-left-color:{DEL_COLOR};">'
            f'Step 2 &mdash; 5-Area across to national (LM_CT154)</div>',
            unsafe_allow_html=True)
        st.markdown(
            f'<div style="font-size:0.9rem;color:{JPSI_DARK};margin:-2px 0 4px;">'
            f'<b>{f5["central"]:,.0f} hd</b> plus the recent 5-Area-to-national gap of '
            f'<b>{fn["gap"]:,.0f} hd</b> &rarr; <b>{fn["central"]:,.0f} hd</b>, '
            f'range <b>{fn["low"]:,.0f}&ndash;{fn["high"]:,.0f} hd</b>.</div>',
            unsafe_allow_html=True)
        st.markdown(
            f'<div class="note" style="margin-bottom:14px;">The gap is negotiated trade outside '
            f'the five areas, plus any region USDA is currently withholding. It is taken as a '
            f'median over the last <b>{fn["n"]}</b> weeks and added, not scaled &mdash; neither '
            f'part of it grows with the 5-Area total, so a ratio drifts whenever the 5-Area '
            f'number is unusually high or low. Over the last {FORECAST_BAND_WEEKS} weeks the gap '
            f'ran {fn["gap_lo"]:,.0f}&ndash;{fn["gap_hi"]:,.0f} hd, which is what sets the range '
            f'above.</div>', unsafe_allow_html=True)

        # ── the two series, with the forecast on the end ────────────────────
        pair = fn["pair"].tail(52)
        if not pair.empty:
            st.markdown('<div class="sec-header">5-Area and national weekly negotiated volume</div>',
                        unsafe_allow_html=True)
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=pair.index, y=pair["nat"], name="National (LM_CT154)",
                mode="lines", line=dict(color=DEL_COLOR, width=2),
                hovertemplate="%{x|%b %d, %Y}<br>National %{y:,.0f} hd<extra></extra>"))
            fig.add_trace(go.Scatter(
                x=pair.index, y=pair["h5"], name="5-Area (LM_CT150)",
                mode="lines", line=dict(color=CONF_COLOR, width=2),
                hovertemplate="%{x|%b %d, %Y}<br>5-Area %{y:,.0f} hd<extra></extra>"))
            # The forecast as its own marked points, never joined to the line --
            # a dotted continuation reads as data at a glance.
            fig.add_trace(go.Scatter(
                x=[_wk], y=[fn["central"]], name="National forecast",
                mode="markers", marker=dict(color=DEL_COLOR, size=11, symbol="diamond",
                                            line=dict(color="#ffffff", width=1.5)),
                error_y=dict(type="data", symmetric=False,
                             array=[fn["high"] - fn["central"]],
                             arrayminus=[fn["central"] - fn["low"]],
                             color=DEL_COLOR, thickness=1.5, width=6),
                hovertemplate="%{x|%b %d, %Y}<br>National forecast %{y:,.0f} hd<extra></extra>"))
            fig.add_trace(go.Scatter(
                x=[_wk], y=[f5["central"]], name="5-Area forecast",
                mode="markers", marker=dict(color=CONF_COLOR, size=11, symbol="diamond",
                                            line=dict(color="#ffffff", width=1.5)),
                error_y=dict(type="data", symmetric=False,
                             array=[f5["high"] - f5["central"]],
                             arrayminus=[f5["central"] - f5["low"]],
                             color=CONF_COLOR, thickness=1.5, width=6),
                hovertemplate="%{x|%b %d, %Y}<br>5-Area forecast %{y:,.0f} hd<extra></extra>"))
            fig.update_layout(
                height=330, margin=dict(l=10, r=10, t=10, b=10),
                plot_bgcolor="#ffffff", paper_bgcolor="#ffffff",
                font=dict(family="Source Sans Pro, sans-serif", color=JPSI_DARK, size=12),
                hovermode="x unified",
                legend=dict(orientation="h", yanchor="bottom", y=1.0, xanchor="right", x=1),
                xaxis=dict(showgrid=False, linecolor=BORDER),
                yaxis=dict(title="head", gridcolor="#f0f2f4", linecolor=BORDER,
                           zeroline=False, tickformat=","))
            st.plotly_chart(fig, use_container_width=True,
                            config={"displayModeBar": False})

            recent = pair.tail(10).copy()
            recent.index = [d.strftime("%b %d") for d in recent.index]
            recent = recent.rename(columns={"h5": "5-Area", "nat": "National", "gap": "Gap"})
            st.dataframe(
                recent[["5-Area", "National", "Gap"]].iloc[::-1]
                      .style.format("{:,.0f}"),
                use_container_width=True)

        st.markdown(
            '<div class="note" style="margin-top:10px;">'
            '<b>What this is.</b> Both weekly reports print the Monday after the week they '
            'cover. The 5-Area step is close to arithmetic &mdash; USDA&rsquo;s own daily '
            'week-to-date already carries most of the answer, and only late-reported trade is '
            'estimated. The national step is the looser of the two, because the gap between '
            'the two reports moves with trade in states that have no daily report at all.<br><br>'
            '<b>The one thing that can move it a long way.</b> When USDA withholds a region&rsquo;s '
            'daily volume for confidentiality, that region drops out of the 5-Area figure but '
            '<b>stays in the national count</b>, so the gap widens and the national forecast is '
            'the half that suffers. Check the week-to-date tiles on the Daily tab: a region '
            'sitting at zero across a whole week is the signal.<br><br>'
            '<b>Neither number is USDA&rsquo;s.</b> They are estimates built from USDA&rsquo;s '
            'published daily reports, and they carry no official standing until the Monday '
            'release.</div>', unsafe_allow_html=True)


# ── Sidebar ──────────────────────────────────────────────────────────────────

with st.sidebar:
    st.image(JSA_LOGO, width="stretch")
    st.markdown("<hr>", unsafe_allow_html=True)

    st.markdown('<div class="sec-header" style="margin-top:0;">Data refresh</div>', unsafe_allow_html=True)
    auto_refresh = st.toggle("Auto-refresh (30 min)", value=False)
    if st.button("↺  Refresh now", width="stretch"):
        st.cache_data.clear()
        st.rerun()

    st.markdown("<hr>", unsafe_allow_html=True)
    st.markdown(
        '<div class="note">'
        '<b>Cash Cattle Prices</b> — USDA AMS LMR, 5 Area Weekly Weighted Average Direct Slaughter Cattle '
        '(<b>LM_CT150</b>), Texas/Oklahoma/New Mexico, Kansas, Nebraska, Colorado, Iowa/Minnesota. '
        'Combined Live FOB and Dressed Delivered figures are a simple head-count-weighted average of USDA\'s '
        'own published Steer and Heifer weekly weighted averages. Published weekly (Mondays).<br><br>'
        '<b>Negotiated Cash Trade Volume</b> — USDA AMS LMR, National Weekly Direct Slaughter Cattle - '
        'Negotiated Purchases (<b>LM_CT154</b>). USDA does not publish a year-ago figure for the 1-14 day '
        'or 15-30 day delivery windows, only for total confirmed trade.<br><br>'
        '<b>Daily Cash Trade</b> — USDA AMS LMR daily negotiated purchases by region: <b>LM_CT117/118</b> (TX/OK/NM), <b>LM_CT120/121</b> (Kansas), <b>LM_CT123/124</b> (Nebraska), <b>LM_CT136/137</b> (Iowa/Minnesota). Each region publishes twice daily; the morning file finalises the PREVIOUS business day and is shifted back one day so both cuts line up on the trading day. Colorado no longer publishes a daily report (ended 2023/2024) and is weekly-only. The daily figures refresh on USDA\'s own <i>published_date</i> stamp rather than on a timer, because AMS publishes no release schedule — it has released LMR data in real time since May 2020. Over 180 days the morning file has landed between 10:52 and 16:18 Central (median 11:17) and the afternoon between 14:49 and 16:49 (median 15:08), so no fixed refresh time would do.<br><br>'
        'Full available history is always loaded — LM_CT150 back to 2004, LM_CT154 back to 2001. Weekly cache: 1 hr.'
        '</div>',
        unsafe_allow_html=True,
    )


# ── Legal Disclaimer Footer ───────────────────────────────────────────────────

_disclaimer_year = datetime.now().year
st.markdown("<hr style='border-color:#3a3a3a;margin-top:32px;margin-bottom:16px'>", unsafe_allow_html=True)
st.markdown(
    f'<div style="font-family:inherit;color:#888;font-size:inherit;line-height:1.6;text-align:center;padding:0 24px 24px;">'
    f'Trading commodity futures, options on futures, cash commodities, and over-the-counter derivative products involves substantial risk of loss and may not be suitable for all investors. '
    f'This communication is provided for informational purposes only and does not constitute investment advice, a recommendation, or an offer or solicitation to buy or sell any futures, options, cash commodities, or derivative products. '
    f'John Stewart &amp; Associates, Inc. does not accept orders to buy or sell any financial instruments via email. '
    f'The information contained herein has been obtained from sources believed to be reliable; however, its accuracy and completeness are not guaranteed. '
    f'Any opinions expressed are solely those of the author, are subject to change without notice, and should not be relied upon as a basis for investment decisions. '
    f'Past performance is not indicative of future results. '
    f'This message may contain confidential or proprietary information intended solely for the use of the designated recipient. '
    f'&copy; John Stewart &amp; Associates, Inc. {_disclaimer_year}'
    f'</div>',
    unsafe_allow_html=True,
)

# ── Auto-refresh ─────────────────────────────────────────────────────────────

if auto_refresh:
    time.sleep(1800)
    st.cache_data.clear()
    st.rerun()
