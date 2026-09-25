"""
US Cow Herd -- is the breeding herd expanding or liquidating?

The definitive answer is NASS January 1 inventory: beef cows and beef
replacement heifers, published once a year. For ten months of the year this
page therefore runs on a proxy, and the proxy is chosen to be a good one rather
than merely available: AMS replacement-cattle auction reports, weekly, priced
by the people actually buying and selling breeding females.

The headline is a RATIO, not a price. A bred female is worth either what a
neighbour will pay for her bred or what the packer will pay for her by the
pound, and the relationship between those two IS the retention decision. Both
sides roughly tripled from 2020 to 2026, so the dollar premium mostly tracks
the market level; the ratio controls for that and still rose from 1.21 to 1.44.

Analytics live in herd.py, which is import-safe (no requests) so this page
never pulls the ingest's HTTP stack into the Streamlit process. Ingest is
replacement_reports.py in the cme-feeder-cattle-index repo.
"""
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# Streamlit puts the MAIN script's directory on sys.path, never the page's, so
# a multipage app's own sibling modules are not importable without this. Same
# line the cme_feeder_cattle page carries, for the same reason.
sys.path.insert(0, str(Path(__file__).parent))

import snowflake_db as db
from herd import (BASELINE_YEARS, LEGACY_LAST_GOOD_WEEK, YTD_CUT, annual_ratio,
                  class_prices, decompose, heifer_share_annual,
                  heifer_share_rolling, heifer_share_summary, latest_date,
                  receipts_yoy)

# ── JSA Brand Colors (shared with the rest of the portal shell) ──────────────
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

JSA_LOGO = "https://www.jpsi.com/wp-content/themes/gate39media/img/logo-full.png"
DB_PATH = Path(__file__).parent / "data" / "mars_history.db"

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
  .tile-delta-pos {{ color:{POS}; font-size:0.82rem; font-weight:600; margin-top:4px; }}
  .tile-delta-neg {{ color:{NEG}; font-size:0.82rem; font-weight:600; margin-top:4px; }}
  .tile-delta-neu {{ color:{NEU}; font-size:0.82rem; font-weight:600; margin-top:4px; }}
  .sec-header {{
    color:{MUTED}; font-size:0.72rem; text-transform:uppercase;
    letter-spacing:0.1em; padding:8px 0 4px; border-bottom:1px solid {BORDER};
    margin-bottom:10px;
  }}
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


# ── Helpers ──────────────────────────────────────────────────────────────────

def tile(label, value, delta=""):
    return (f'<div class="tile"><div class="tile-label">{label}</div>'
            f'<div class="tile-value">{value}</div>{delta}</div>')


def pct_delta(val, suffix=""):
    if val is None or pd.isna(val):
        return '<div class="tile-delta-neu">—</div>'
    sign = "▲" if val > 0 else ("▼" if val < 0 else "")
    kind = "pos" if val > 0 else ("neg" if val < 0 else "neu")
    return f'<div class="tile-delta-{kind}">{sign} {abs(val):.1f}%{suffix}</div>'


def pt_delta(val, suffix=""):
    """Points, not percent -- the ratio moves in points and calling that a
    percentage change would overstate it by a factor of about four."""
    if val is None or pd.isna(val):
        return '<div class="tile-delta-neu">—</div>'
    sign = "▲" if val > 0 else ("▼" if val < 0 else "")
    kind = "pos" if val > 0 else ("neg" if val < 0 else "neu")
    return f'<div class="tile-delta-{kind}">{sign} {abs(val):.2f}{suffix}</div>'


# ── Data ─────────────────────────────────────────────────────────────────────

@st.cache_data(ttl=3600, show_spinner=False)
def load_all():
    """
    Everything the page needs, in one connection. Returns None on any failure
    so the page can say so plainly rather than half-rendering.
    """
    if not db.use_snowflake() and not DB_PATH.exists():
        return None
    conn = db.get_conn()
    try:
        return {
            "latest": latest_date(conn),
            "current": decompose(conn),
            "annual": annual_ratio(conn),
            "classes": class_prices(conn),
            "receipts": receipts_yoy(conn),
        }
    except Exception:
        return None
    finally:
        conn.close()


@st.cache_data(ttl=3600, show_spinner=False)
def load_heifer_share():
    """
    The receipts-mix section, loaded SEPARATELY from load_all() on purpose.

    It reads a different table (`feeder_receipts`, from feeder_sex_mix.py), and
    folding it into load_all's try/except would mean a missing or empty table
    there takes down the retention-incentive half of the page too -- which is
    fed by a different ingest and would be perfectly healthy. Returning None
    here costs one section instead.
    """
    if not db.use_snowflake() and not DB_PATH.exists():
        return None
    conn = db.get_conn()
    try:
        summary = heifer_share_summary(conn)
        if not summary:
            return None
        return {"summary": summary, "annual": heifer_share_annual(conn),
                "rolling": heifer_share_rolling(conn)}
    except Exception:
        return None
    finally:
        conn.close()


with st.spinner("Loading replacement-cattle reports…"):
    D = load_all()

if not D or not D.get("current"):
    st.error("Could not load the replacement-cattle data.")
    st.caption(
        "This page reads the `replacement_sales` table, populated by "
        "`replacement_reports.py` in the cme-feeder-cattle-index repo and "
        "pushed to Snowflake by that repo's daily job."
    )
    st.stop()

cur = D["current"]

# ── Header ───────────────────────────────────────────────────────────────────
col_title, col_date = st.columns([6, 2])
with col_title:
    st.markdown("## JSA — US Cow Herd")
    st.caption("Herd expansion vs liquidation · AMS replacement-cattle auction reports")
with col_date:
    st.markdown(
        f"<div style='text-align:right;color:{MUTED};font-size:0.75rem;padding-top:6px;'>"
        f"Latest sale date<br>"
        f"<span style='color:{JPSI_BLUE};font-size:1rem;font-weight:700;'>"
        f"{pd.Timestamp(D['latest']).strftime('%b %d, %Y')}</span></div>",
        unsafe_allow_html=True)

st.markdown("<hr style='margin:10px 0 18px;'>", unsafe_allow_html=True)


# ── Retention Incentive ──────────────────────────────────────────────────────
st.markdown('<div class="sec-header">Retention Incentive</div>', unsafe_allow_html=True)
st.caption(
    f"What a bred female is worth against what the packer would pay for the same "
    f"animal. Trailing **{cur['weeks']} weeks** ({cur['n_current']} sale dates, "
    f"{cur['bred_head']:,} bred head) — a single sale can swing the ratio 25 points "
    f"on quality mix alone, so the headline is a window rather than the latest print."
)

c = st.columns(4)
with c[0]:
    st.markdown(tile("Bred Female", f"${cur['bred']:,.0f}/hd",
                     pct_delta(cur.get("bred_yoy_pct"), " YoY")), unsafe_allow_html=True)
with c[1]:
    st.markdown(tile("Salvage Value", f"${cur['salvage']:,.0f}/hd",
                     pct_delta(cur.get("salvage_yoy_pct"), " YoY")), unsafe_allow_html=True)
with c[2]:
    st.markdown(tile("Premium", f"${cur['premium']:,.0f}/hd"), unsafe_allow_html=True)
with c[3]:
    st.markdown(tile("Ratio", f"{cur['ratio']:.2f}",
                     pt_delta(cur["ratio_vs_base"], " vs normal")), unsafe_allow_html=True)

st.caption(
    f"Normal for {BASELINE_YEARS[0]}–{BASELINE_YEARS[1]} is **{cur['base_ratio']:.2f}** "
    f"(n={cur['n_base']} sale dates). Salvage is converted to a per-head basis — bred "
    f"females trade per head, slaughter cows per hundredweight."
)

if cur.get("driver"):
    # A rising ratio means opposite things depending on which side moved, so
    # say which rather than leaving a reader to assume the flattering one.
    _up = cur["ratio_vs_base"] > 0
    st.info(
        f"**{'Retention pays more than normal' if _up else 'Retention pays less than normal'}** — "
        f"and it is {cur['driver']}: bred values {cur['bred_yoy_pct']:+.1f}% against "
        f"{cur['prior_year']} while salvage moved {cur['salvage_yoy_pct']:+.1f}%. "
        f"That distinction matters: the ratio rises either because producers are "
        f"bidding up breeding females or because packers stopped paying for cull cows, "
        f"and only the first is expansion."
    )


# ── Ratio Trend ──────────────────────────────────────────────────────────────
st.markdown("<div style='height:18px'></div>", unsafe_allow_html=True)
st.markdown('<div class="sec-header">Retention Incentive by Year</div>',
            unsafe_allow_html=True)

_ann = D["annual"]
_fig = go.Figure()
_fig.add_trace(go.Bar(
    x=[a[0] for a in _ann], y=[a[1] for a in _ann],
    marker_color=[JPSI_BLUE if a[0] == _ann[-1][0] else "#9fb8c8" for a in _ann],
    text=[f"{a[1]:.2f}" for a in _ann], textposition="outside",
    hovertemplate="%{x}<br>ratio %{y:.2f}<extra></extra>", name="ratio"))
_base_ratio = cur["base_ratio"]
_fig.add_hline(y=_base_ratio, line_dash="dot", line_color=MUTED,
               annotation_text=f"{BASELINE_YEARS[0]}–{BASELINE_YEARS[1]} normal "
                               f"{_base_ratio:.2f}",
               annotation_position="top left")
_fig.update_layout(height=300, margin=dict(l=0, r=0, t=24, b=0),
                   plot_bgcolor="white", paper_bgcolor="white",
                   yaxis_title="bred value ÷ salvage value", showlegend=False)
_fig.update_yaxes(showgrid=True, gridcolor="#f1f5f9", range=[1.0, max(a[1] for a in _ann) * 1.12])
st.plotly_chart(_fig, use_container_width=True)
st.caption(
    "Median of every sale date in the year. Flat through the liquidation years, "
    "then two consecutive rises. Note **2020 is not a comparable signal** — its "
    "ratio was high because salvage value was the lowest in the series, not "
    "because bred values were strong."
)

with st.expander("ℹ️  How to read the retention incentive"):
    st.markdown(f"""
**The question it answers.** A producer holding a cow can sell her bred to a
neighbour, or ship her to the packer. Whichever pays more is what tends to
happen, in aggregate, and that decision is what grows or shrinks the national
herd. This ratio prices that choice every week.

**Today:** a bred female brings **${cur['bred']:,.0f}** while the same animal's
salvage value is **${cur['salvage']:,.0f}** — a ratio of **{cur['ratio']:.2f}**
against a {BASELINE_YEARS[0]}–{BASELINE_YEARS[1]} normal of
**{cur['base_ratio']:.2f}**.

**Why the ratio and not the premium.** Both sides roughly tripled between 2020
and 2026, so the dollar premium mostly measures the bull market. The ratio
controls for the level — and still rose from 1.21 to 1.44, which is a real
change in the incentive rather than in the price of cattle.

**Why the driver matters.** The ratio rises when bred values climb *or* when
salvage falls, and those are opposite stories. In 2020 the ratio read 1.37
because cull-cow prices collapsed — packers retreating, not producers
expanding. The banner above always names which side moved.

**What it is not.** It is a price signal, not a head count. It tells you what
the incentive to retain looks like, not how many females were actually kept.
The NASS January 1 inventory is the only thing that measures that, and it
arrives once a year.
""")


# ── Breeding Female Prices ───────────────────────────────────────────────────
st.markdown("<div style='height:18px'></div>", unsafe_allow_html=True)
st.markdown('<div class="sec-header">Breeding Female Prices</div>',
            unsafe_allow_html=True)
st.caption(
    f"Trailing {cur['weeks']} weeks against the same weeks a year earlier (52 weeks "
    f"back, so the comparison lands on the same point in the sale calendar). "
    f"**Per-pair prices include the calf** and are shown on their own basis — "
    f"averaging them with single females would overstate the market."
)

_rows = []
for r in D["classes"]:
    if r["head"] < 5:
        continue           # a one-head lot is an anecdote, not a price
    _rows.append({
        "Class": r["class"],
        "Basis": r["basis"],
        "Price": f"${r['price']:,.0f}",
        "Head": f"{r['head']:,}",
        "Year Ago": f"${r['year_ago']:,.0f}" if r["year_ago"] else "—",
        "YoY": f"{r['yoy_pct']:+.1f}%" if r["yoy_pct"] is not None else "—",
    })
if _rows:
    with st.container(key="wm-classes"):
        st.dataframe(pd.DataFrame(_rows), use_container_width=True,
                     hide_index=True, height=min(300, 60 + 35 * len(_rows)))

# Bred heifers over bred cows is the sharper expansion signal: it is money paid
# specifically for a young female entering the herd rather than for one already
# in it.
_bh = next((r for r in D["classes"] if r["class"] == "Bred Heifers"), None)
_bc = next((r for r in D["classes"] if r["class"] == "Bred Cows"), None)
if _bh and _bc and _bh["head"] >= 5 and _bc["head"] >= 5:
    _gap = _bh["price"] - _bc["price"]
    st.caption(
        f"**Bred heifers are {'above' if _gap > 0 else 'below'} bred cows by "
        f"\\${abs(_gap):,.0f}/hd** (\\${_bh['price']:,.0f} against "
        f"\\${_bc['price']:,.0f}). Heifers are the sharper expansion signal — that is "
        f"money paid for a female *entering* the herd rather than one already in it."
    )


# ── Receipts ─────────────────────────────────────────────────────────────────
_rc = D.get("receipts")
if _rc:
    st.markdown("<div style='height:18px'></div>", unsafe_allow_html=True)
    st.markdown('<div class="sec-header">Replacement Auction Receipts</div>',
                unsafe_allow_html=True)
    r1, r2, r3 = st.columns(3)
    with r1:
        st.markdown(tile(f"Receipts, {_rc['weeks']} Wks", f"{_rc['receipts']:,}"),
                    unsafe_allow_html=True)
    with r2:
        st.markdown(tile("Year Ago", f"{_rc['year_ago']:,}",
                         pct_delta(_rc["pct"])), unsafe_allow_html=True)
    with r3:
        st.markdown(tile("Reports", f"{_rc['n_reports']:,}"), unsafe_allow_html=True)
    st.caption(
        "Total head through these auctions, using each report's OWN year-ago "
        "receipts figure rather than our stored history — so the comparison is "
        "AMS's like-for-like and holds even where our archive has a gap. Falling "
        "receipts alongside rising bred prices is the classic tight-supply "
        "signature: fewer females offered, bid harder."
    )


# ── Heifer Share of Feeder Receipts ──────────────────────────────────────────
# The volume-side read, and the counterpart to everything above it: the ratio
# section prices the retention DECISION, this shows what producers did about it.
HS = load_heifer_share()
if HS:
    _sum = HS["summary"]
    _cur, _lo, _hi = _sum["current"], _sum["low"], _sum["high"]

    st.markdown("<div style='height:18px'></div>", unsafe_allow_html=True)
    st.markdown('<div class="sec-header">Heifer Share of Feeder Receipts</div>',
                unsafe_allow_html=True)
    st.caption(
        f"Heifers as a share of steer + heifer feeder cattle sold at auction, "
        f"year-to-date through week {YTD_CUT} of every year. When "
        f"producers keep heifers back to breed, those heifers stop arriving at the "
        f"sale barn — so a **falling** share is retention. Unlike the ratio above, "
        f"this measures what was done rather than what it paid to do."
    )

    h = st.columns(4)
    with h[0]:
        _since = (f'<div class="tile-delta-pos">▼ lowest since {_sum["since"]}</div>'
                  if _sum["since"] else '<div class="tile-delta-neu">—</div>')
        st.markdown(tile(f"Heifer Share, {_cur['year']}", f"{_cur['share']:.1f}%", _since),
                    unsafe_allow_html=True)
    with h[1]:
        st.markdown(tile("Cycle Peak", f"{_hi['share']:.1f}%",
                         f'<div class="tile-delta-neu">{_hi["year"]}</div>'),
                    unsafe_allow_html=True)
    with h[2]:
        st.markdown(tile("Last Rebuild Low", f"{_lo['share']:.1f}%",
                         f'<div class="tile-delta-neu">{_lo["year"]}</div>'),
                    unsafe_allow_html=True)
    with h[3]:
        st.markdown(tile("Distance To That Low", f"{_sum['gap_to_low']:.2f} pts",
                         '<div class="tile-delta-pos">▼ closing</div>'),
                    unsafe_allow_html=True)

    _ann = HS["annual"]
    _yrs = [r["year"] for r in _ann]
    _shs = [r["share"] for r in _ann]
    # The spliced year is drawn in a muted colour rather than hidden: it is a
    # real reading, but it is the one point built from two archives.
    _colors = [POS if r["year"] == _cur["year"]
               else ("#9fb8c8" if r["src"] == "spliced" else JPSI_BLUE) for r in _ann]
    _sizes = [14 if r["year"] == _cur["year"]
              else (11 if r["year"] in (_hi["year"], _lo["year"]) else 7) for r in _ann]

    _f1 = go.Figure()
    _f1.add_trace(go.Scatter(x=_yrs, y=_shs, mode="lines", fill="tozeroy",
                             fillcolor="rgba(6,147,227,0.08)",
                             line=dict(color=JPSI_BLUE, width=2.5),
                             hovertemplate="%{x}<br>heifer share %{y:.2f}%<extra></extra>"))
    _f1.add_trace(go.Scatter(x=_yrs, y=_shs, mode="markers", hoverinfo="skip",
                             marker=dict(size=_sizes, color=_colors,
                                         line=dict(color="#ffffff", width=2))))
    _f1.add_hline(y=_lo["share"], line_dash="dot", line_color=POS)
    _f1.add_annotation(x=_hi["year"], y=_hi["share"], xanchor="left", ax=6, ay=-32,
                       text=f"<b>{_hi['share']:.1f}%</b> peak liquidation",
                       showarrow=True, arrowhead=0, arrowcolor=MUTED,
                       font=dict(size=12, color=TEXT))
    _f1.add_annotation(x=_lo["year"], y=_lo["share"], ax=0, ay=40,
                       text=f"<b>{_lo['share']:.1f}%</b> last rebuild",
                       showarrow=True, arrowhead=0, arrowcolor=MUTED,
                       font=dict(size=12, color=TEXT))
    _f1.add_annotation(x=_cur["year"], y=_cur["share"], ax=-14, ay=34,
                       text=f"<b>{_cur['share']:.1f}%</b>", showarrow=True,
                       arrowhead=0, arrowcolor=POS, font=dict(size=13, color=TEXT))
    _f1.update_layout(height=380, margin=dict(l=0, r=10, t=30, b=0),
                      plot_bgcolor="white", paper_bgcolor="white", showlegend=False,
                      yaxis_title="heifer share of steer + heifer receipts")
    _f1.update_yaxes(showgrid=True, gridcolor="#f1f5f9", ticksuffix="%",
                     range=[min(_shs) - 1.2, max(_shs) + 1.1])
    _f1.update_xaxes(showgrid=False, tickvals=[y for i, y in enumerate(_yrs)
                                               if i % 2 == 0 or y == _cur["year"]])
    with st.container(key="wm-heifer-annual"):
        st.plotly_chart(_f1, use_container_width=True)

    _chg = ""
    if _sum["heifer_chg"] is not None and _sum["steer_chg"] is not None:
        _dir = "up" if _sum["steer_chg"] > 0 else "down"
        _chg = (f" Against {_sum['chg_base_year']}, heifer receipts are down "
                f"**{abs(_sum['heifer_chg']):,}** head while steer receipts are "
                f"*{_dir}* **{abs(_sum['steer_chg']):,}** — the decline is females "
                f"only, which is what retention looks like and what a general "
                f"contraction in cattle numbers would not.")
    # Derived, not hard-coded: a deployment without the legacy archive loaded
    # has no spliced year at all, and the caption should not claim one.
    _spl = [r["year"] for r in _ann if r["src"] == "spliced"]
    _spl_txt = ""
    if _spl:
        _spl_txt = (
            f" **{_spl[0]} is spliced** — USDA retired the archive behind the early "
            f"years mid-year and stood up its replacement in the same weeks, so that "
            f"point takes the weeks through {LEGACY_LAST_GOOD_WEEK} from one and the "
            f"rest from the other; the two halves agree to within 0.26 points.")
    st.caption(
        f"Each point covers the same weeks of its year, across the same 20 states."
        f"{_spl_txt}{_chg}"
    )

    _roll = HS["rolling"]
    if len(_roll) > 8:
        _pk = max(_roll, key=lambda r: r["share"])
        _rc = _roll[-1]
        st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)
        st.markdown('<div class="sec-header">The Current Turn, Week By Week</div>',
                    unsafe_allow_html=True)
        _f2 = go.Figure()
        _f2.add_trace(go.Scatter(x=[r["week"] for r in _roll],
                                 y=[r["share"] for r in _roll], mode="lines",
                                 fill="tozeroy", fillcolor="rgba(6,147,227,0.09)",
                                 line=dict(color=JPSI_BLUE, width=2.5),
                                 hovertemplate="%{x|%b %Y}<br>%{y:.2f}%<extra></extra>"))
        _f2.add_trace(go.Scatter(x=[_pk["week"]], y=[_pk["share"]], mode="markers",
                                 hoverinfo="skip",
                                 marker=dict(size=11, color=MUTED,
                                             line=dict(color="#ffffff", width=2))))
        _f2.add_trace(go.Scatter(x=[_rc["week"]], y=[_rc["share"]], mode="markers",
                                 hoverinfo="skip",
                                 marker=dict(size=14, color=POS,
                                             line=dict(color="#ffffff", width=2))))
        _f2.add_annotation(x=_pk["week"], y=_pk["share"], ax=-2, ay=-32,
                           text=f"<b>peak {_pk['share']:.1f}%</b>", showarrow=True,
                           arrowhead=0, arrowcolor=MUTED, font=dict(size=12, color=TEXT))
        _f2.add_annotation(x=_rc["week"], y=_rc["share"], ax=0, ay=34,
                           text=f"<b>{_rc['share']:.1f}%</b>", showarrow=True,
                           arrowhead=0, arrowcolor=POS, font=dict(size=13, color=TEXT))
        _f2.update_layout(height=320, margin=dict(l=0, r=10, t=26, b=0),
                          plot_bgcolor="white", paper_bgcolor="white",
                          showlegend=False, yaxis_title="rolling 52-week heifer share")
        # An explicit range, because fill="tozeroy" otherwise drags the axis down
        # to 0% and squeezes a four-point move into a sliver at the top of the
        # chart. The fill is there to weight the area, not to imply a zero base.
        _rs = [r["share"] for r in _roll]
        _f2.update_yaxes(showgrid=True, gridcolor="#f1f5f9", ticksuffix="%",
                         range=[min(_rs) - 0.7, max(_rs) + 0.7])
        _f2.update_xaxes(showgrid=False)
        st.plotly_chart(_f2, use_container_width=True)
        st.caption(
            "A rolling 52-week window, which is seasonally neutral and so puts the "
            "turn on its actual date rather than in whichever annual bucket the "
            "calendar assigns it. It stays inside the current data source: a window "
            "spanning the 2019 handover would mix two archives mid-window, which the "
            "annual series above avoids by construction."
        )

    with st.expander("ℹ️  How to read the heifer share"):
        st.markdown(f"""
**What it measures.** Every feeder animal sold at auction is a steer or a heifer.
Steers have one destination — the feedlot. A heifer can go to the feedlot too, or
she can stay home and be bred. So the heifer share of feeder receipts is a direct
count of which choice was made, aggregated over {len(_ann)} years and 20 states.

**Falling is rebuilding.** A share of **{_cur['share']:.1f}%** in {_cur['year']}
against a peak of **{_hi['share']:.1f}%** in {_hi['year']} means heifers are being
withheld. The benchmark is **{_lo['share']:.1f}%** in {_lo['year']}, the last time
the national herd genuinely expanded — today sits **{_sum['gap_to_low']:.2f} points**
above it.

**Why it is not the same as the ratio above.** The retention incentive prices the
decision; this counts the outcome. They can disagree, and when they do the
disagreement is the story: an incentive nobody acts on is not a rebuild, and
retention in the face of a poor incentive says something about expectations.

**What it is not.** Auction receipts only — direct, video and internet sales are
not included, and roughly half the feeder cattle in the country change hands that
way. It is a large consistent sample, not a census, and the *level* matters less
than the direction and where it sits against {_lo['year']}.
""")


# ── Awaiting NASS ────────────────────────────────────────────────────────────
st.markdown("<div style='height:18px'></div>", unsafe_allow_html=True)
st.markdown('<div class="sec-header">Herd Inventory — Awaiting Data</div>',
            unsafe_allow_html=True)
st.warning(
    "**The inventory half of this page is still not wired up.** The receipts-mix "
    "section above is a volume signal — it counts heifers that went to the feedlot "
    "rather than pricing the choice — but neither it nor the ratio is a head count "
    "of the breeding herd, and auction receipts miss the direct and video trade "
    "entirely. The counts that measure it directly are USDA NASS January 1 "
    "inventory — **beef cows** and **beef replacement heifers ≥500 lb** — plus "
    "monthly **beef cow slaughter** for the culling side. Beef cows are already in "
    "the shared NASS cache; replacement heifers and class-level slaughter are not, "
    "and adding them means adding series to the `usda-nass-etl` job that holds the "
    "NASS key. Once they land, the ratio that belongs here is replacement heifers "
    "÷ beef cows — the standard expansion measure."
)

st.markdown(
    f"<div style='margin-top:22px;color:{MUTED};font-size:0.72rem;"
    f"border-top:1px solid {BORDER};padding-top:10px;'>"
    f"Source: USDA AMS replacement- and slaughter-cattle auction reports via the "
    f"MARS API, {len(D['annual'])} years of history. Provided for informational "
    f"purposes only; not investment advice. © John Stewart &amp; Associates "
    f"{datetime.now().year}.</div>",
    unsafe_allow_html=True)
