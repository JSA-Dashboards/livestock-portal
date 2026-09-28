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
from dairy_mix import (ASSUMED_DAIRY_NOW, ASSUMED_DAIRY_THEN,
                       ASSUMED_HEIFER_FRAC)
from dairy_mix import adjust as dm_adjust
from inventory import inventory_summary
from on_feed import on_feed_summary

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
def load_inventory():
    """The head counts. Same contract as load_on_feed: reason up, never a bare None."""
    try:
        return {"ok": inventory_summary()}
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}


@st.cache_data(ttl=3600, show_spinner=False)
def load_on_feed():
    """
    The feedlot-side read, from the shared NASS cache rather than Snowflake's
    CME_FEEDER_CATTLE schema. Loaded on its own for the same reason the receipts
    section is: a different backend, and a failure here should cost one panel
    rather than the page.

    Returns {"ok": summary} or {"error": reason}. The reason is carried up rather
    than swallowed: nass_cache_client raises on a genuine backend failure
    precisely so a misconfigured secret is loud, and catching that to a bare None
    would delete this panel with no explanation. That is not hypothetical -- it
    is how the SNOWFLAKE_PRIVATE_KEY_PWD name mismatch hid itself the first time.
    An empty cache is different, and stays quiet.
    """
    try:
        return {"ok": on_feed_summary()}
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}


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
        # The basis is in the label, not a footnote. This number says the herd is
        # within a point of the last rebuild, and the feedlot survey two sections
        # below disagrees by nearly four -- so the qualifier has to travel with
        # the figure. A footnote gets separated from it the moment someone
        # screenshots the tiles.
        st.markdown(tile(f"Distance To {_lo['year']} — Receipts Basis",
                         f"{_sum['gap_to_low']:.2f} pts",
                         '<div class="tile-delta-neu">feedlot survey reads '
                         'further</div>'), unsafe_allow_html=True)

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
    # The basis is named on both charts' peaks and axes. Without it the two
    # sections read as disagreeing about the same number: this one peaks at
    # 47.5% and the rolling one at 46.6%, because heifer share runs about three
    # points lighter in the autumn run and a trailing-year window always
    # contains one while a January-September window never does.
    _f1.add_annotation(x=_hi["year"], y=_hi["share"], xanchor="left", ax=6, ay=-32,
                       text=f"<b>{_hi['share']:.1f}%</b> peak liquidation (Jan–Sep)",
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
                      yaxis_title=f"heifer share, Jan–mid-Sep (weeks 1–{YTD_CUT})")
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
                           text=f"<b>peak {_pk['share']:.1f}%</b> (12-month)",
                           showarrow=True, arrowhead=0, arrowcolor=MUTED,
                           font=dict(size=12, color=TEXT))
        _f2.add_annotation(x=_rc["week"], y=_rc["share"], ax=0, ay=34,
                           text=f"<b>{_rc['share']:.1f}%</b>", showarrow=True,
                           arrowhead=0, arrowcolor=POS, font=dict(size=13, color=TEXT))
        _f2.update_layout(height=320, margin=dict(l=0, r=10, t=26, b=0),
                          plot_bgcolor="white", paper_bgcolor="white",
                          showlegend=False,
                          yaxis_title="heifer share, trailing 52 weeks")
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
above it *on this measure*.

**Do not read that gap as settled.** It is the sale-barn view. The NASS feedlot
survey further down reads considerably further from {_lo['year']} — and stays
further even after allowing for dairy-origin cattle, which is the obvious
explanation and does not stretch far enough to cover it. Two independent datasets
agree the herd is retaining and disagree about how close that is to a rebuild.
Set the year selector in that panel to {_lo['year']} to see the size of it.

**Why it is not the same as the ratio above.** The retention incentive prices the
decision; this counts the outcome. They can disagree, and when they do the
disagreement is the story: an incentive nobody acts on is not a rebuild, and
retention in the face of a poor incentive says something about expectations.

**Why the two charts peak at different numbers.** The first reads January to
mid-September; the second reads a trailing twelve months. Heifer share runs about
three points lighter in the autumn run, so any twelve-month window sits below a
January–September one. Both peak in 2023 — it is the same market through two
windows, not a disagreement. The annual basis is the only one comparable across
the 2019 source handover; the trailing one is the only one free of seasonality.

**What it is not.** Auction receipts only — direct, video and internet sales are
not included, and roughly half the feeder cattle in the country change hands that
way. It is a large consistent sample, not a census, and the *level* matters less
than the direction and where it sits against {_lo['year']}.
""")


# ── Heifers On Feed ──────────────────────────────────────────────────────────
# The same decision measured from the opposite end, by someone else. Receipts
# count heifers arriving at auction (AMS, barn-level); this counts heifers
# standing in feedlots (NASS, a survey of feedyards). Two datasets with
# different failure modes agreeing is worth more than either on its own.
_OF = load_on_feed() or {}
if _OF.get("error"):
    st.markdown("<div style='height:18px'></div>", unsafe_allow_html=True)
    st.markdown('<div class="sec-header">Heifers On Feed — The Feedlot Side</div>',
                unsafe_allow_html=True)
    st.warning(
        f"**The feedlot panel could not read the NASS cache.** Everything above is "
        f"unaffected — it comes from a different backend. `{_OF['error']}`"
    )
OF = _OF.get("ok")
if OF:
    _ocur, _ohi, _olo = OF["current"], OF["high"], OF["low"]
    _orows = [r for r in OF["rows"] if r["trailing"] is not None]

    st.markdown("<div style='height:18px'></div>", unsafe_allow_html=True)
    st.markdown('<div class="sec-header">Heifers On Feed — The Feedlot Side</div>',
                unsafe_allow_html=True)
    st.caption(
        "Heifers as a share of the steers and heifers standing in US feedlots — "
        "USDA NASS's quarterly survey of feedyards, an entirely separate "
        "measurement from the auction receipts above. A heifer on feed is a heifer "
        "that was **not** kept back to breed, so this falls when producers retain, "
        "the same direction as the receipts share. Plotted as a trailing "
        "four-quarter mean, because April runs about 1.3 points below the other "
        "quarters every year."
    )

    o = st.columns(4)
    with o[0]:
        _yoy = (f'<div class="tile-delta-{"pos" if OF["yoy_pts"] < 0 else "neg"}">'
                f'{"▼" if OF["yoy_pts"] < 0 else "▲"} {abs(OF["yoy_pts"]):.2f} pts YoY</div>'
                if OF["yoy_pts"] is not None else '<div class="tile-delta-neu">—</div>')
        st.markdown(tile(f"On Feed, {_ocur['label']}", f"{_ocur['share']:.1f}%", _yoy),
                    unsafe_allow_html=True)
    with o[1]:
        st.markdown(tile("Trailing 4-Qtr", f"{_ocur['trailing']:.1f}%",
                         f'<div class="tile-delta-neu">seasonally neutral</div>'),
                    unsafe_allow_html=True)
    with o[2]:
        st.markdown(tile("Series Peak", f"{_ohi['trailing']:.1f}%",
                         f'<div class="tile-delta-neu">{_ohi["label"]}</div>'),
                    unsafe_allow_html=True)
    with o[3]:
        st.markdown(tile("Rebuild Low", f"{_olo['trailing']:.1f}%",
                         f'<div class="tile-delta-neu">{_olo["label"]}</div>'),
                    unsafe_allow_html=True)

    _ox = [f"{r['year']}-Q{r['quarter']}" for r in _orows]
    _oy = [r["trailing"] for r in _orows]
    _f3 = go.Figure()
    _f3.add_trace(go.Scatter(x=_ox, y=_oy, mode="lines", fill="tozeroy",
                             fillcolor="rgba(217,119,6,0.09)",
                             line=dict(color="#d97706", width=2.5),
                             hovertemplate="%{x}<br>%{y:.2f}%<extra></extra>"))
    for _r, _c, _sz in ((_ohi, MUTED, 11), (_olo, MUTED, 11), (_orows[-1], POS, 14)):
        _f3.add_trace(go.Scatter(x=[f"{_r['year']}-Q{_r['quarter']}"],
                                 y=[_r["trailing"]], mode="markers", hoverinfo="skip",
                                 marker=dict(size=_sz, color=_c,
                                             line=dict(color="#ffffff", width=2))))
    _f3.add_hline(y=_olo["trailing"], line_dash="dot", line_color=POS)
    _f3.add_annotation(x=f"{_ohi['year']}-Q{_ohi['quarter']}", y=_ohi["trailing"],
                       ax=0, ay=-30, text=f"<b>{_ohi['trailing']:.1f}%</b> {_ohi['year']}",
                       showarrow=True, arrowhead=0, arrowcolor=MUTED,
                       font=dict(size=12, color=TEXT))
    _f3.add_annotation(x=f"{_olo['year']}-Q{_olo['quarter']}", y=_olo["trailing"],
                       ax=0, ay=36, text=f"<b>{_olo['trailing']:.1f}%</b> last rebuild",
                       showarrow=True, arrowhead=0, arrowcolor=MUTED,
                       font=dict(size=12, color=TEXT))
    _f3.add_annotation(x=_ox[-1], y=_oy[-1], ax=-18, ay=-30,
                       text=f"<b>{_oy[-1]:.1f}%</b>", showarrow=True, arrowhead=0,
                       arrowcolor=POS, font=dict(size=13, color=TEXT))
    _f3.update_layout(height=340, margin=dict(l=0, r=10, t=30, b=0),
                      plot_bgcolor="white", paper_bgcolor="white", showlegend=False,
                      yaxis_title="heifer share on feed, trailing 4 quarters")
    _f3.update_yaxes(showgrid=True, gridcolor="#f1f5f9", ticksuffix="%",
                     range=[min(_oy) - 1.0, max(_oy) + 1.2])
    _f3.update_xaxes(showgrid=False,
                     tickvals=[f"{y}-Q1" for y in range(1998, _ocur["year"] + 1, 4)])
    with st.container(key="wm-on-feed"):
        st.plotly_chart(_f3, use_container_width=True)

    st.caption(
        f"**The two measures agree on direction and differ on distance, and there "
        f"are two reasons for that, not one.** Both peaked in 2023 and both are "
        f"falling, but the receipts share sits within a point of its rebuild low "
        f"while this one is still **{_ocur['trailing'] - _olo['trailing']:.1f} "
        f"points** above {_olo['year']}'s.\n\n"
        f"**Timing.** Receipts are a *flow* — what is being sold this week. Cattle "
        f"on feed are a *stock*, and heifers already placed stay on feed for months, "
        f"so the feedlot number lags the sale barn by roughly a feeding period.\n\n"
        f"**Mix.** This series counts every heifer in a feedlot, including "
        f"dairy-origin ones that were never a beef-herd retention decision. The "
        f"receipts series excludes them by construction — AMS reports Dairy and "
        f"Beef/Dairy as their own classes — but NASS publishes no breed split for "
        f"cattle on feed, so they cannot be removed here. That composition has "
        f"changed since {_olo['year']} in both directions, which is why the *level* "
        f"is less comparable across a decade than the direction is within recent "
        f"years. The panel below puts numbers on how much it would take to matter."
    )

    # Not a correction -- there is no breed split to correct WITH. The inverse
    # question: the receipts series IS breed-clean, so ask how much dairy there
    # would have to be for the two measures to be telling the same story.
    with st.expander("⚖️  Compare with an earlier year, with dairy cattle taken out"):
        # The benchmark year is the reader's to choose. It defaults to the receipts
        # peak so the panel opens on the comparison the caption above just made,
        # but 2015-16 is the more interesting one -- that is the last genuine
        # rebuild, and whether today has matched it is the actual question.
        _years = sorted({r["year"] for r in _orows
                         if 2010 <= r["year"] < _ocur["year"]})
        _bench = None
        _rdrop = None
        _rec_then = None
        if _years:
            _def = HS["summary"]["high"]["year"] if HS else _years[-1]
            if _def not in _years:
                _def = _years[-1]
            _by = st.selectbox("Compare against", _years, index=_years.index(_def),
                               key="dm_year",
                               help="On-feed data runs to 1996; receipts only to "
                                    "2011, so the receipts row drops out below that.")
            # Same quarter as the current reading -- this series is seasonal, and
            # April sits about 1.3 points under the rest every year.
            _same_q = [r for r in _orows
                       if r["year"] == _by and r["quarter"] == _ocur["quarter"]]
            _bench = (_same_q or [r for r in _orows if r["year"] == _by])[-1]
            if HS:
                _rec_then = next((r for r in HS["annual"] if r["year"] == _by), None)
                if _rec_then:
                    _rdrop = HS["summary"]["current"]["share"] - _rec_then["share"]

        st.markdown("""
This series counts **every** heifer in a feedlot, including straight Holstein
heifers and beef-on-dairy crossbreds. Neither was a female a rancher chose not to
keep, so neither belongs in a retention signal — but they cannot be removed from
the data, because **NASS publishes no breed split for cattle on feed**.

What follows takes an assumed dairy stream out of both years, so the two are
comparable on beef-herd terms. The assumption is stated, not adjustable: nobody
knows this figure, and a control would only let a reader dial in the answer they
came for.
""")

        _gap_rep = _ocur["trailing"] - _bench["trailing"]
        _adj_then = dm_adjust(_bench["trailing"], ASSUMED_DAIRY_THEN, ASSUMED_HEIFER_FRAC)
        _adj_now = dm_adjust(_ocur["trailing"], ASSUMED_DAIRY_NOW, ASSUMED_HEIFER_FRAC)
        _gap_adj = (_adj_now - _adj_then) if (_adj_then is not None
                                             and _adj_now is not None) else None

        _rows = [("On feed, as reported", "every heifer in a feedlot",
                  _bench["trailing"], _ocur["trailing"], _gap_rep, False)]
        if _gap_adj is not None:
            _rows.append(
                ("On feed, beef-only",
                 f"assumes {ASSUMED_DAIRY_NOW:.0f}% dairy today, none in "
                 f"{_bench['year']}, that stream {ASSUMED_HEIFER_FRAC:.0f}% heifers",
                 _adj_then, _adj_now, _gap_adj, True))
        if _rec_then and _rdrop is not None:
            _rows.append(("At the sale barn", "receipts — excludes dairy already",
                          _rec_then["share"], HS["summary"]["current"]["share"],
                          _rdrop, False))

        _t = ['<table style="width:100%;border-collapse:collapse;font-size:0.9rem;">',
              f'<tr style="color:{MUTED};font-size:0.7rem;text-transform:uppercase;'
              f'letter-spacing:0.08em;text-align:right;">'
              f'<th style="text-align:left;padding:6px 8px;">Heifer share</th>'
              f'<th style="padding:6px 8px;">{_bench["year"]}</th>'
              f'<th style="padding:6px 8px;">{_ocur["year"]}</th>'
              f'<th style="padding:6px 8px;">Change</th></tr>']
        for _lbl, _sub, _a, _b, _c, _hi in _rows:
            _bg = f"background:{SURFACE2};" if _hi else ""
            _w = "700" if _hi else "400"
            _t.append(
                f'<tr style="{_bg}border-top:1px solid {BORDER};text-align:right;">'
                f'<td style="text-align:left;padding:8px;font-weight:{_w};">{_lbl}'
                f'<div style="color:{MUTED};font-size:0.72rem;font-weight:400;">{_sub}</div></td>'
                f'<td style="padding:8px;">{_a:.1f}%</td>'
                f'<td style="padding:8px;font-weight:{_w};">{_b:.1f}%</td>'
                f'<td style="padding:8px;font-weight:700;color:{POS if _c < 0 else NEG};">'
                f'{_c:+.1f} pts</td></tr>')
        _t.append("</table>")
        st.markdown("".join(_t), unsafe_allow_html=True)

        # One plain sentence. Earlier versions of this panel showed the dairy share
        # that WOULD BE needed to reconcile the two series -- true, and unreadable:
        # a column of percentages whose meaning depended on holding a gap in your
        # head from a caption above it. The question a reader has is whether today
        # resembles the benchmark year, so answer that.
        if _gap_adj is None or _rdrop is None:
            st.caption("The sale-barn series does not reach "
                       f"{_bench['year']}, so there is nothing breed-clean to set "
                       "the feedlot reading against.")
        else:
            _closed = abs(_gap_adj - _rdrop) < abs(_gap_rep - _rdrop)
            _verdict = (
                f"That takes most of the disagreement out — what is left "
                f"({abs(_gap_adj - _rdrop):.1f} pts) is the feeding-period lag, or "
                f"something neither series shows."
                if _closed else
                f"That does not close the disagreement, so dairy mix is not what "
                f"is driving it.")
            st.info(
                f"**Same measure, dairy taken out of both ends.** Against "
                f"{_bench['year']}, the feedlot reading goes from **{_gap_rep:+.1f} "
                f"pts** as reported to **{_gap_adj:+.1f} pts** beef-only. The sale "
                f"barn, which never counted dairy cattle, moved **{_rdrop:+.1f} pts** "
                f"over the same span. {_verdict}"
            )

        st.caption(
            "**Why the direction across a decade is genuinely unknown.** Straight "
            "Holstein heifers used to be scarce in feedlots — the legacy AMS archive "
            "carries Feeder Holstein *steers* and no Holstein heifer class at all, "
            "because those heifers became dairy replacements. Sexed semen then "
            "produced a surplus that did go on feed, peaking around the same years "
            "this page uses as its rebuild benchmark, before beef-on-dairy displaced "
            "it. Our own auction data shows that changeover: straight-Holstein "
            "heifers were 100% of dairy-class heifers through 2023 and are 69% now. "
            "So the benchmark year may carry its own dairy inflation. The two "
            "effects partly offset, neither is measurable, and anyone who tells you "
            "the net sign with confidence is guessing."
        )


# ── Herd Inventory ───────────────────────────────────────────────────────────
# The head counts. Everything above measures the retention decision or what
# producers did about it at the sale barn; this measures the herd itself.
_IV = load_inventory() or {}
if _IV.get("error"):
    st.markdown("<div style='height:18px'></div>", unsafe_allow_html=True)
    st.markdown('<div class="sec-header">Herd Inventory</div>', unsafe_allow_html=True)
    st.warning(
        f"**The inventory panel could not read the NASS cache.** Everything above is "
        f"unaffected — different backend. `{_IV['error']}`"
    )
IV = _IV.get("ok")
if IV:
    _ic, _ip = IV["current"], IV["prev"]
    _ihi, _ilo = IV["recent_high"], IV["recent_low"]
    _sl, _ypk = IV["slaughter"], IV["slaughter_peak"]
    _yc, _yp = IV["ytd_current"], IV["ytd_prev"]
    _sla = IV["slaughter_annual_latest"]

    st.markdown("<div style='height:18px'></div>", unsafe_allow_html=True)
    st.markdown('<div class="sec-header">Herd Inventory — The Head Count</div>',
                unsafe_allow_html=True)
    st.caption(
        "USDA NASS January 1 inventory and monthly commercial slaughter. "
        "**Replacement heifers ÷ beef cows** is the standard expansion measure — "
        "females entering the herd against females already in it — and beef cow "
        "slaughter is the culling side of the same ledger. These are counts of the "
        "herd, not prices or receipts, and they are the only thing here that "
        "measures the rebuild directly."
    )

    i = st.columns(4)
    with i[0]:
        _arrow = ("▲" if IV["turned_up"] else "▼")
        _kind = "pos" if IV["turned_up"] else "neg"
        st.markdown(tile(f"Replacement Ratio, {_ic['year']}", f"{_ic['ratio']:.1f}%",
                         f'<div class="tile-delta-{_kind}">{_arrow} '
                         f'{abs(_ic["ratio"] - _ip["ratio"]):.2f} pts vs {_ip["year"]}</div>'),
                    unsafe_allow_html=True)
    with i[1]:
        st.markdown(tile(f"Beef Cows, {_ic['year']}", f"{_ic['cows'] / 1e6:.2f}M",
                         f'<div class="tile-delta-neu">{_ic["heifers"] / 1e6:.2f}M '
                         f'replacements</div>'), unsafe_allow_html=True)
    with i[2]:
        _spct = 100.0 * (_sla["head"] - _ypk["head"]) / _ypk["head"]
        st.markdown(tile(f"Cow Slaughter, {_sla['year']}", f"{_sla['head'] / 1e6:.2f}M",
                         f'<div class="tile-delta-pos">▼ {abs(_spct):.0f}% vs '
                         f'{_ypk["year"]} peak</div>'), unsafe_allow_html=True)
    with i[3]:
        _ypct = 100.0 * (_yc["head"] - _yp["head"]) / _yp["head"]
        st.markdown(tile(f"Slaughter YTD thru {_yc['through'].title()}",
                         f"{_yc['head'] / 1e6:.2f}M",
                         f'<div class="tile-delta-{"pos" if _ypct < 0 else "neg"}">'
                         f'{"▼" if _ypct < 0 else "▲"} {abs(_ypct):.1f}% vs '
                         f'{_yp["year"]}</div>'), unsafe_allow_html=True)

    # Five decades rather than the full 107 years the series carries: enough to
    # show four cattle cycles without compressing the current turn to nothing.
    _rr = [r for r in IV["ratio"] if r["year"] >= _ic["year"] - 55]
    _f4 = go.Figure()
    _f4.add_trace(go.Scatter(x=[r["year"] for r in _rr], y=[r["ratio"] for r in _rr],
                             mode="lines", fill="tozeroy",
                             fillcolor="rgba(6,147,227,0.09)",
                             line=dict(color=JPSI_BLUE, width=2.5),
                             hovertemplate="%{x}<br>%{y:.2f}%<extra></extra>"))
    _f4.add_trace(go.Scatter(x=[_ic["year"]], y=[_ic["ratio"]], mode="markers",
                             hoverinfo="skip",
                             marker=dict(size=14, color=POS,
                                         line=dict(color="#ffffff", width=2))))
    _f4.add_annotation(x=_ihi["year"], y=_ihi["ratio"], ax=0, ay=-30,
                       text=f"<b>{_ihi['ratio']:.1f}%</b> {_ihi['year']} rebuild",
                       showarrow=True, arrowhead=0, arrowcolor=MUTED,
                       font=dict(size=12, color=TEXT))
    _f4.add_annotation(x=_ic["year"], y=_ic["ratio"], ax=-20, ay=34,
                       text=f"<b>{_ic['ratio']:.1f}%</b>", showarrow=True, arrowhead=0,
                       arrowcolor=POS, font=dict(size=13, color=TEXT))
    _f4.update_layout(height=330, margin=dict(l=0, r=10, t=30, b=0),
                      plot_bgcolor="white", paper_bgcolor="white", showlegend=False,
                      yaxis_title="replacement heifers ÷ beef cows")
    # Explicit range: fill="tozeroy" otherwise drags the axis to 0% and squashes
    # a four-point spread into the top quarter of the chart. The fill weights the
    # area; it is not a claim that zero is meaningful here. (The slaughter bars
    # below DO baseline at zero, correctly -- bar length encodes magnitude.)
    _rv = [r["ratio"] for r in _rr]
    _f4.update_yaxes(showgrid=True, gridcolor="#f1f5f9", ticksuffix="%",
                     range=[min(_rv) - 0.8, max(_rv) + 1.0])
    _f4.update_xaxes(showgrid=False)
    with st.container(key="wm-repl-ratio"):
        st.plotly_chart(_f4, use_container_width=True)

    _sa = [r for r in _sl["annual"] if r["year"] >= _ic["year"] - 26]
    _f5 = go.Figure()
    _f5.add_trace(go.Bar(x=[r["year"] for r in _sa], y=[r["head"] / 1e6 for r in _sa],
                         marker_color=[NEG if r["year"] == _ypk["year"]
                                       else ("#9fb8c8" if r["year"] != _sla["year"]
                                             else POS) for r in _sa],
                         hovertemplate="%{x}<br>%{y:.2f}M head<extra></extra>"))
    _f5.update_layout(height=270, margin=dict(l=0, r=10, t=24, b=0),
                      plot_bgcolor="white", paper_bgcolor="white", showlegend=False,
                      yaxis_title="beef cow slaughter, million head")
    _f5.update_yaxes(showgrid=True, gridcolor="#f1f5f9")
    _f5.update_xaxes(showgrid=False)
    st.plotly_chart(_f5, use_container_width=True)

    _turn = ("**turned up in "
             f"{_ic['year']} — the first rise since {_ihi['year']}**"
             if IV["turned_up"] else "has not yet turned up")
    st.info(
        f"**The flows have turned; the herd has not — which is the order a rebuild "
        f"happens in.** Beef cow slaughter is down **{abs(_spct):.0f}%** from its "
        f"{_ypk['year']} peak and still falling this year, and the replacement ratio "
        f"{_turn}. But beef cows themselves are **{_ic['cows'] / 1e6:.2f}M**, still "
        f"the smallest in decades. That is not a contradiction: culling stops and "
        f"heifers start being held while the herd is still shrinking, because those "
        f"heifers do not add a calf for the better part of two years. Slaughter "
        f"falls first, the ratio turns second, and beef cow inventory bottoms last."
    )

st.markdown(
    f"<div style='margin-top:22px;color:{MUTED};font-size:0.72rem;"
    f"border-top:1px solid {BORDER};padding-top:10px;'>"
    f"Sources: USDA AMS replacement- and slaughter-cattle auction reports via the "
    f"MARS API ({len(D['annual'])} years), AMS state auction summaries and USDA's "
    f"legacy auction archive for the receipts mix, and USDA NASS via the shared "
    f"cache for cattle on feed and the January 1 head counts. Provided for informational "
    f"purposes only; not investment advice. © John Stewart &amp; Associates "
    f"{datetime.now().year}.</div>",
    unsafe_allow_html=True)
