"""
JSA — Canadian Feeder Cattle.

The fifteenth dashboard, added 2026-10-12. Canadian-side feeder prices by
province and weight, and Canadian federally-inspected slaughter, from AMS 3213
(Weekly Canadian Livestock and Poultry Summary).

Arithmetic, parsing and every Snowflake read are in `ca_prices.py`; this file
is layout only -- the split `cof_recap`, `leverage`, `am_cutout` and
`mx_prices` all use.

**IT IS NOT THE MEXICAN PAGE'S SHAPE, AND CANNOT BE.** The Mexican Feeder
Imports page leads with head counts because AMS 3486 and 3629 publish daily
crossings. Neither has a Canadian counterpart, so this page leads with PRICE
and says so where a reader would look for a crossings tile.

**THE PRICES ARE ALREADY IN US DOLLARS.** AMS converts before publishing, so
nothing here touches an exchange rate -- which is the one thing that makes
these directly comparable to a US quote, and the opposite of the Mexican page
where the FX conversion is half the arithmetic.
"""

import sys
from datetime import date
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# Streamlit puts the MAIN script's directory on sys.path, never the page's, so a
# multipage app's own sibling modules are not importable without this.
sys.path.insert(0, str(Path(__file__).parent))

import ca_prices as cap


# ── JSA Brand Colors (shared with the rest of the portal shell) ─────────────
JPSI_DARK = "#32373c"
JPSI_BLUE = "#0693e3"
BG        = "#f6f8f7"
CARD_BG   = "#ffffff"
SURFACE2  = "#eef3f0"
BORDER    = "#d7e2dc"
MUTED     = "#5f7267"
TEXT      = "#32373c"
POS       = "#16a34a"
NEG       = "#dc2626"
NEU       = "#5f7267"
AMBER     = "#d97706"

JSA_LOGO = "https://www.jpsi.com/wp-content/themes/gate39media/img/logo-full.png"

st.markdown(f"""
<style>
  html, body, [data-testid="stAppViewContainer"] {{
    background-color:{BG}; color:{TEXT};
  }}
  [data-testid="stSidebar"] {{
    background-color:{SURFACE2}; border-right:1px solid {BORDER};
  }}
  .tile {{
    background:{CARD_BG}; border:1px solid {BORDER};
    border-top:3px solid {JPSI_BLUE}; border-radius:10px;
    padding:16px 20px; text-align:center; height:100%;
    box-shadow: 0 1px 2px rgba(0,0,0,0.04);
  }}
  .tile-label {{
    color:{MUTED}; font-size:0.68rem; text-transform:uppercase;
    letter-spacing:0.09em; margin-bottom:6px;
  }}
  .tile-value {{
    color:{TEXT}; font-size:1.7rem; font-weight:700; line-height:1.1;
  }}
  /* Scenario tiles carry an amber rule instead of the blue one. Every other
     tile on this page is a measurement or a projection anchored to one; these
     describe a year that has not started and must not read as either. */
  .tile-scen {{ border-top-color:{AMBER}; }}
  .tile-sub {{ color:{MUTED}; font-size:0.72rem; margin-top:5px; }}
  .tile-delta-pos {{ color:{POS}; font-size:0.82rem; font-weight:600; margin-top:4px; }}
  .tile-delta-neg {{ color:{NEG}; font-size:0.82rem; font-weight:600; margin-top:4px; }}
  .tile-delta-neu {{ color:{NEU}; font-size:0.82rem; font-weight:600; margin-top:4px; }}
  .sec-header {{
    color:{MUTED}; font-size:0.72rem; text-transform:uppercase;
    letter-spacing:0.1em; padding:8px 0 4px; border-bottom:1px solid {BORDER};
    margin-bottom:10px;
  }}
  /* Status banner. Colour carries the verdict, so the text still has to say it
     in words -- a reader on a projector or with a colour deficiency gets the
     same answer. */
  .banner {{
    border-radius:10px; padding:16px 20px; margin-bottom:6px;
    border:1px solid {BORDER}; border-left:5px solid {MUTED};
    background:{CARD_BG};
  }}
  .banner-open   {{ border-left-color:{POS}; }}
  .banner-idle   {{ border-left-color:{AMBER}; }}
  .banner-closed {{ border-left-color:{NEG}; }}
  .banner-state {{ font-size:1.15rem; font-weight:700; line-height:1.2; }}
  .banner-detail {{ color:{MUTED}; font-size:0.82rem; margin-top:6px; line-height:1.5; }}
  .banner-quote {{
    color:{TEXT}; font-size:0.78rem; margin-top:9px; padding:8px 11px;
    background:{SURFACE2}; border-radius:6px; font-family:ui-monospace,monospace;
  }}
  .srcline {{ color:{MUTED}; font-size:0.72rem; line-height:1.6; }}
  hr {{ border-color:{BORDER}; }}
  #MainMenu, footer {{ visibility:hidden; }}
  .stDeployButton {{ display:none; }}
  div[class*="st-key-wm-"] {{ position:relative; }}
  div[class*="st-key-wm-"]::after {{
    content:"";
    position:absolute; inset:0; margin:auto;
    width:50%; height:110px; max-width:320px;
    background-image:url('{JSA_LOGO}');
    background-size:contain; background-repeat:no-repeat; background-position:center;
    opacity:0.05; pointer-events:none; z-index:3;
  }}
</style>
""", unsafe_allow_html=True)


# ── Helpers ─────────────────────────────────────────────────────────────────

def tile(label, value, extra="", cls=""):
    return (f'<div class="tile {cls}"><div class="tile-label">{label}</div>'
            f'<div class="tile-value">{value}</div>{extra}</div>')


def sub(text):
    return f'<div class="tile-sub">{text}</div>'


def pct_delta(val, suffix=""):
    if val is None or pd.isna(val):
        return '<div class="tile-delta-neu">—</div>'
    sign = "▲" if val > 0 else ("▼" if val < 0 else "")
    kind = "pos" if val > 0 else ("neg" if val < 0 else "neu")
    return f'<div class="tile-delta-{kind}">{sign} {abs(val):.1f}%{suffix}</div>'


def fmt_date(d, fmt="%b %d, %Y"):
    if not d:
        return "—"
    return pd.Timestamp(str(d)).strftime(fmt)


def fmt_month(p):
    if not p:
        return "—"
    return pd.Timestamp(str(p) + "-01").strftime("%b %Y")



# Module level on purpose — CLAUDE.md records the letter page's tab split
# having to hoist every multi-line string above it, and that being the only
# reason indenting the rest was safe.
_CA_METHOD = """
**Source.** USDA AMS report **3213**, *Weekly Canadian Livestock and Poultry
Summary*, read from `marsapi.ams.usda.gov` by `deploy/ca_livestock.py` into
`JSA.CME_FEEDER_CATTLE.CA_LIVESTOCK_PRICES` and `.CA_SLAUGHTER`. The page only
ever reads Snowflake: that host rejects Streamlit Community Cloud's IPs, the
same constraint that moved the Beef Trimmings import side to a droplet job.

**The prices are already US dollars per hundredweight.** AMS converts before
publishing. Nothing on this page applies an exchange rate, which is what makes
these directly comparable with a US quote — and the opposite of the Mexican
Feeder Imports page, where converting pesos is half the arithmetic.

**There is no US–Canada crossings report, so this page cannot lead with head
counts.** The Mexican page leads with daily crossings because AMS 3486 and
3629 publish them. A sweep of the MARS catalogue and the LMR datamart found no
Canadian counterpart. Monthly head counts exist only in Census trade data, at
roughly a six-week lag.

**A week is identified by its ISO week, not by a 7-day step.** The series
contains one Sunday `week_ending`, and a date-arithmetic step across it finds
nothing and reports no change on a week that has one. Changes are therefore
measured a fixed number of ISO weeks back, and never across a hole — the rule
`letter/sources.fetch_futures` follows for settlements.

**The year-end closure is two ISO weeks, not one.** AMS publishes no week 52
and no week 1, so a missing-week check that excludes only week 1 reports the
annual shutdown as a data gap every January. Flagging a closure as missing
data trains a reader to ignore the gap that is not one.

**Staleness is measured against the feed's own publication lag**, nine to
seventeen days, rather than against its weekly cadence. A rule written from
"it is weekly" marks this feed stale every single week on current data.
"""


# ── Data ────────────────────────────────────────────────────────────────────

#: The rung this page headlines. 701-800 lb is the weight the CME feeder index
#: tracks and the weight the Mexican page quotes at Douglas, so it is the one
#: rung a reader can carry between the three without converting anything.
HEADLINE_WEIGHT = "701-800"
HEADLINE_REGION = "Alberta"


@st.cache_data(ttl=1800, show_spinner=False)
def load_ca(schema: int = cap.SCHEMA):
    """Prices and slaughter in one connection. None on any failure.

    `schema` is hashed into the cache key and MUST be passed by the caller.
    st.cache_data keys on this function's own code and arguments and never on
    the modules it calls, and an argument sitting at its default is not part of
    the key at all -- both halves of the trap CLAUDE.md records, which was
    inert in nineteen loaders before it was found. No leading underscore, and
    the call site passes it.
    """
    if not cap.enabled():
        return None
    try:
        prices = cap.read_prices()
        slaughter = cap.read_slaughter()
        if not prices:
            return None
        return {"prices": prices, "slaughter": slaughter}
    except Exception as e:
        st.session_state["_ca_error"] = f"{type(e).__name__}: {e}"
        return None


with st.spinner("Loading AMS 3213 — Canadian livestock…"):
    D = load_ca(cap.SCHEMA)

# ── Header ──────────────────────────────────────────────────────────────────
col_title, col_date = st.columns([6, 2])
with col_title:
    st.markdown("## JSA — Canadian Feeder Cattle")
    st.caption("Feeder and slaughter cattle prices by province, and Canadian "
               "federally-inspected slaughter · USDA AMS 3213")

if not D:
    with col_date:
        st.markdown("")
    st.error("Could not load the Canadian livestock data.")
    st.caption(
        "This page reads `JSA.CME_FEEDER_CATTLE.CA_LIVESTOCK_PRICES` and "
        "`.CA_SLAUGHTER`, written by `deploy/ca_livestock.py`. AMS 3213 is "
        "fetched from `marsapi.ams.usda.gov`, which rejects Streamlit "
        "Community Cloud's IPs — so the page can only ever read Snowflake and "
        "the job has to run elsewhere."
    )
    if st.session_state.get("_ca_error"):
        st.caption(f"Detail: `{st.session_state['_ca_error']}`")
    st.stop()

PRICES, KILL = D["prices"], D["slaughter"]
_week, _behind, _stale = cap.staleness(PRICES, date.today())

with col_date:
    st.markdown(
        f"<div style='text-align:right;color:{MUTED};font-size:0.75rem;"
        f"padding-top:6px;'>Week ending<br>"
        f"<span style='color:{JPSI_BLUE};font-size:1rem;font-weight:700;'>"
        f"{fmt_date(_week)}</span></div>",
        unsafe_allow_html=True)

st.markdown("<hr style='margin:10px 0 18px;'>", unsafe_allow_html=True)

# THE STALENESS RULE COMES FROM THE FEED'S MEASURED LAG, not from its cadence.
# AMS publishes 3213 nine to seventeen days after the week it covers, so a
# banner keyed on "it is weekly" fires every week on perfectly current data --
# the defect CLAUDE.md records for the board suppressing its own tension every
# Thursday. cap.MAX_AGE_DAYS carries the measured figure.
if _stale:
    st.warning(
        f"**AMS 3213 has not published since the week ending "
        f"{fmt_date(_week)}** — {_behind} days ago, past the "
        f"{cap.MAX_AGE_DAYS}-day limit this feed normally runs inside. The "
        f"figures below are real and simply old; the recording job may have "
        f"stopped."
    )

tab_prices, tab_kill = st.tabs(
    ["Feeder Prices", "Canadian Slaughter"])

# ── Feeder prices ───────────────────────────────────────────────────────────
with tab_prices:
    st.markdown('<div class="sec-header">Feeder Cattle, by Province</div>',
                unsafe_allow_html=True)

    # EVERY FIGURE ON THIS PAGE IS ALREADY US DOLLARS. AMS converts before
    # publishing, which is why nothing here touches an exchange rate and why
    # these sit directly beside a US quote. Said in the open rather than in a
    # footnote, because a reader who assumes Canadian dollars is out by about
    # a third and nothing on the page would look wrong.
    st.caption(
        "AMS publishes 3213 **already converted to US dollars per "
        "hundredweight**, so these compare directly with a US quote and no "
        "exchange rate is applied anywhere on this page."
    )

    _lat, _pri, _chg = cap.price_change(
        PRICES, HEADLINE_REGION, "Steers", HEADLINE_WEIGHT)
    _on_lat, _, _ = cap.price_change(
        PRICES, "Ontario", "Steers", HEADLINE_WEIGHT)
    _hf_lat, _, _ = cap.price_change(
        PRICES, HEADLINE_REGION, "Heifers", HEADLINE_WEIGHT)

    c = st.columns(4)
    with c[0]:
        st.markdown(tile(
            f"Alberta {HEADLINE_WEIGHT} lb Steers",
            f"${_lat:,.2f}" if _lat else "—",
            sub("US$/cwt · the CME index weight")), unsafe_allow_html=True)
    with c[1]:
        # THE LEVEL IT MOVED FROM, on its own line. The standing rule in
        # CLAUDE.md, in Ross's words: "you have to do the math in your head".
        _chg_extra = (
            f'<div class="tile-delta-{"pos" if _chg > 0 else ("neg" if _chg < 0 else "neu")}">'
            f'{"▲" if _chg > 0 else ("▼" if _chg < 0 else "")} ${abs(_chg):,.2f}</div>'
            + sub(f"a week ago ${_pri:,.2f}") if _chg is not None else sub("no prior week"))
        st.markdown(tile(
            "Alberta Steers, Week Change",
            f"${_lat:,.2f}" if _lat else "—",
            _chg_extra), unsafe_allow_html=True)
    with c[2]:
        _spread = (_lat - _on_lat) if (_lat and _on_lat) else None
        st.markdown(tile(
            "Alberta minus Ontario",
            f"${_spread:,.2f}" if _spread is not None else "—",
            sub(f"same rung · Ontario ${_on_lat:,.2f}" if _on_lat
                else "Ontario not quoted")), unsafe_allow_html=True)
    with c[3]:
        _gap = (_lat - _hf_lat) if (_lat and _hf_lat) else None
        st.markdown(tile(
            "Steer minus Heifer",
            f"${_gap:,.2f}" if _gap is not None else "—",
            sub(f"Alberta {HEADLINE_WEIGHT} lb · heifers ${_hf_lat:,.2f}"
                if _hf_lat else "heifers not quoted")), unsafe_allow_html=True)

    st.markdown("<div style='height:10px'></div>", unsafe_allow_html=True)

    t_ladder, t_trend, t_method = st.tabs(
        ["This week's ladder", "Over time", "How this is built"])

    with t_ladder:
        rows = []
        for region in cap.REGIONS:
            for rung in cap.feeder_ladder(PRICES, region, _week):
                rows.append({
                    "Province": region,
                    "Weight (lb)": rung["weight_group"],
                    "Steers US$/cwt": (f"${rung['Steers']:,.2f}"
                                       if rung["Steers"] else "—"),
                    "Heifers US$/cwt": (f"${rung['Heifers']:,.2f}"
                                        if rung["Heifers"] else "—"),
                })
        st.dataframe(pd.DataFrame(rows), use_container_width=True,
                     hide_index=True)
        st.caption(
            f"Week ending **{fmt_date(_week)}**. A rung that did not trade is "
            f"shown as a dash rather than dropped — a ladder that stops and a "
            f"ladder with a hole in it are different statements, and only one "
            f"of them means the heavy end went unsold."
        )

    with t_trend:
        _sex = st.radio("Class", ["Steers", "Heifers"], horizontal=True,
                        key="ca_trend_sex")
        fig = go.Figure()
        for region, colour in zip(cap.REGIONS,
                                  (JPSI_BLUE, "#B07A2A", "#16a34a")):
            series = sorted(
                ((r["week_ending"], r["price"]) for r in PRICES
                 if r["commodity"] == cap.FEEDER and r["region"] == region
                 and r["sex"] == _sex
                 and r["weight_group"] == HEADLINE_WEIGHT and r["price"]),
                key=lambda t: t[0])
            if not series:
                continue
            fig.add_trace(go.Scatter(
                x=[pd.Timestamp(str(d)) for d, _p in series],
                y=[p for _d, p in series],
                mode="lines", name=region,
                line=dict(color=colour, width=2)))
        fig.update_layout(
            height=360, margin=dict(l=10, r=10, t=30, b=10),
            yaxis_title="US$/cwt", xaxis_title=None, plot_bgcolor="white",
            legend=dict(orientation="h", y=1.14, x=0))
        st.plotly_chart(fig, use_container_width=True)
        st.caption(
            f"{HEADLINE_WEIGHT} lb {_sex.lower()}, the rung the tiles above "
            f"quote. Saskatchewan reports fewer weeks than the other two, so "
            f"its line is shorter rather than flat."
        )

        _holes = cap.missing_weeks(PRICES)
        if _holes:
            st.caption(
                f"**{len(_holes)} week(s) missing from the series**, beyond "
                f"the annual year-end closure which is excluded: "
                + ", ".join(f"{y}-W{w:02d}" for y, w in _holes[:8])
                + ("…" if len(_holes) > 8 else "")
            )

    with t_method:
        st.markdown(_CA_METHOD)

# ── Canadian slaughter ──────────────────────────────────────────────────────
with tab_kill:
    st.markdown('<div class="sec-header">Canadian Federally-Inspected '
                'Slaughter</div>', unsafe_allow_html=True)

    k = st.columns(4)
    _cattle = cap.slaughter_summary(KILL, "Cattle", _week)
    _calves = cap.slaughter_summary(KILL, "Calves", _week)

    with k[0]:
        st.markdown(tile(
            "Canadian FI Cattle, This Week",
            f"{_cattle.get('head'):,.0f}" if _cattle.get("head") else "—",
            sub(f"head · week ending {fmt_date(_week)}")),
            unsafe_allow_html=True)
    with k[1]:
        # USDA'S OWN YTD PERCENTAGE, passed through rather than recomputed.
        # head-against-head_year_ago is a WEEKLY comparison and this is a
        # year-to-date one; both render as "percent change" and they are not
        # the same question. ca_prices.slaughter_summary says so too.
        _p = _cattle.get("pct_change")
        st.markdown(tile(
            "Cattle YTD vs Year Ago",
            f"{_p:+.1f}%" if _p is not None else "—",
            sub(f"{_cattle.get('ytd'):,.0f} vs {_cattle.get('ytd_prior'):,.0f} head"
                if _cattle.get("ytd") and _cattle.get("ytd_prior")
                else "USDA's own year-to-date figure")),
            unsafe_allow_html=True)
    with k[2]:
        st.markdown(tile(
            "Canadian FI Calves, This Week",
            f"{_calves.get('head'):,.0f}" if _calves.get("head") else "—",
            sub(f"head · week ending {fmt_date(_week)}")),
            unsafe_allow_html=True)
    with k[3]:
        _pc = _calves.get("pct_change")
        st.markdown(tile(
            "Calves YTD vs Year Ago",
            f"{_pc:+.1f}%" if _pc is not None else "—",
            sub(f"{_calves.get('ytd'):,.0f} vs {_calves.get('ytd_prior'):,.0f} head"
                if _calves.get("ytd") and _calves.get("ytd_prior")
                else "USDA's own year-to-date figure")),
            unsafe_allow_html=True)

    st.caption(
        "**Year-to-date percentages are USDA's own**, read off the report "
        "rather than computed here. They answer a different question from the "
        "weekly head counts beside them, and both would render as \"percent "
        "change\" — so the page prints USDA's figure for the year and leaves "
        "the week as a head count."
    )

    _hist = sorted(((r["week_ending"], r["head"]) for r in KILL
                    if r["species"] == "Cattle" and r.get("head")),
                   key=lambda t: t[0])
    if len(_hist) > 1:
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=[pd.Timestamp(str(d)) for d, _h in _hist],
            y=[h for _d, h in _hist],
            mode="lines", name="FI cattle",
            line=dict(color=JPSI_BLUE, width=2)))
        fig.update_layout(
            height=320, margin=dict(l=10, r=10, t=30, b=10),
            yaxis_title="head per week", xaxis_title=None,
            plot_bgcolor="white", showlegend=False)
        st.plotly_chart(fig, use_container_width=True)
        st.caption(
            "The annual year-end closure is a real two-week gap in the series, "
            "not missing data — AMS publishes no week 52 or week 1."
        )

st.markdown("<hr style='margin:18px 0 8px;'>", unsafe_allow_html=True)
st.markdown(
    f'<div class="srcline">JSA · John Stewart &amp; Associates &nbsp;·&nbsp; '
    f'USDA AMS 3213, Weekly Canadian Livestock and Poultry Summary '
    f'&nbsp;·&nbsp; week ending {fmt_date(_week)}</div>',
    unsafe_allow_html=True)
