"""
Mexican Feeder Imports -- how much Mexican cattle is reaching US feedyards.

Mexico normally supplies about 1.25 million feeder cattle a year, roughly 4% of
the US calf crop and concentrated in the southern Plains. New World Screwworm
suspensions cut that to 214,394 head in 2025 and to zero for the first seven
months of 2026. Douglas, AZ reopened on 24 August 2026 -- one crossing of five.

THE PAGE IS BUILT AROUND A LAG. AMS publishes daily head counts by crossing
point, current to yesterday, plus exact weekly totals with its own year-to-date
a week behind that. Census is the official customs count with seven years of
history but runs about six weeks late. So AMS answers "what is crossing now"
and Census answers "how does that compare to a normal year". In September 2026
a Census-only page would have shown zero imports for the whole year and said
nothing about the border reopening three weeks earlier.

A CORRECTION WORTH KEEPING. The first version of this page asserted that AMS
published no numbers at all and showed crossing DAYS as a proxy for volume.
That was wrong. MARS reports are split into SECTIONS addressed as PATH segments
(/reports/3486/Report%20Volume); requesting a report without one returns just
its header -- narrative and dates, nothing numeric -- which looks exactly like
a report with no data. The section list was in the response's `reportSections`
key all along.

DIRECTION MATTERS. AMS's status report covers both directions, and its standing
September 2026 note is about EXPORTS to Mexico being suspended while imports
were flowing. The import verdict here is computed from import-side crossing
activity only; the export note is shown separately and labelled. See
border.note_segments().

Analytics live in border.py, which is import-safe (no requests). Ingest is
border_reports.py and census_imports.py in the cme-feeder-cattle-index repo.
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

import snowflake_db as db
import border as bd

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

def tile(label, value, extra=""):
    return (f'<div class="tile"><div class="tile-label">{label}</div>'
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


# ── Data ────────────────────────────────────────────────────────────────────

@st.cache_data(ttl=1800, show_spinner=False)
def load_all():
    """
    Everything the page needs, in one connection. None on any failure.

    get_conn() is INSIDE the try on purpose: connecting is the step most likely
    to fail (a missing SNOWFLAKE_ACCOUNT, an expired key, a paused warehouse),
    and with it outside, that failure escaped as a raw traceback on the page
    instead of the handled message below -- the one case the error handling
    exists for.
    """
    if not db.use_snowflake() and not DB_PATH.exists():
        return None
    conn = None
    try:
        conn = db.get_conn()
        ytd, through = bd.ytd_compare(conn)
        annual, _ = bd.annual_head(conn)
        bands, band_year = bd.band_shares(conn)
        kinds, kind_year = bd.kind_totals(conn, band_year)
        monthly, _ = bd.monthly_head(conn)
        return {
            "status": bd.import_status(conn),
            "export_note": bd.current_status(conn),
            "crossings": bd.crossing_days(conn),
            "ports": bd.ports_by_year(conn),
            "commentary": bd.recent_commentary(conn, 15),
            "timeline": bd.status_history(conn),
            "monthly": monthly,
            "annual": annual,
            "ytd": ytd,
            "census_through": through,
            "bands": bands,
            "band_year": band_year,
            "kinds": kinds,
            "kind_year": kind_year,
            "vph": bd.value_per_head(conn),
            "fresh": bd.data_freshness(conn),
            "daily": bd.daily_receipts(conn, since=f"{date.today().year}-01-01"),
            "daily_all": bd.daily_receipts(conn),
            "by_year": bd.receipts_by_year(conn),
            "by_crossing": bd.receipts_by_crossing(conn,
                                                   since=f"{date.today().year}-01-01"),
            "ytd_ams": bd.ytd_actuals(conn),
            "since_open": bd.since_reopening(conn),
            "weekly": bd.weekly_volumes(conn),
            "price_grid": bd.price_grid(conn),
            "price_series": bd.price_series(conn, grade=bd.INDEX_GRADE),
            "spread": bd.index_spread(conn),
            "spread_yr": bd.spread_by_year(conn),
            "price_cov": bd.price_coverage(conn),
        }
    except Exception as e:
        st.session_state["_mfi_error"] = f"{type(e).__name__}: {e}"
        return None
    finally:
        if conn is not None:
            conn.close()


with st.spinner("Loading border reports and Census trade data…"):
    D = load_all()

if not D:
    st.error("Could not load the Mexican import data.")
    st.caption(
        "This page reads the `border_reports` and `census_cattle_imports` "
        "tables, populated by `border_reports.py` and `census_imports.py` in "
        "the cme-feeder-cattle-index repo and pushed to Snowflake by that "
        "repo's daily job."
    )
    if st.session_state.get("_mfi_error"):
        st.caption(f"Detail: `{st.session_state['_mfi_error']}`")
    st.stop()

S = D["status"]
F = D["fresh"]

# ── Header ──────────────────────────────────────────────────────────────────
col_title, col_date = st.columns([6, 2])
with col_title:
    st.markdown("## JSA — Mexican Feeder Imports")
    st.caption("Daily head counts and border status from USDA AMS · historical customs counts from US Census trade data")
with col_date:
    st.markdown(
        f"<div style='text-align:right;color:{MUTED};font-size:0.75rem;padding-top:6px;'>"
        f"Latest border report<br>"
        f"<span style='color:{JPSI_BLUE};font-size:1rem;font-weight:700;'>"
        f"{fmt_date(F['ams_through'])}</span></div>",
        unsafe_allow_html=True)

st.markdown("<hr style='margin:10px 0 18px;'>", unsafe_allow_html=True)

# ── Status banner ───────────────────────────────────────────────────────────
# The single most important fact on the page and the one Census cannot answer.
state = S["state"]
reop = S.get("reopening") or {}
words = {
    "open": ("IMPORTS FLOWING",
             "Cattle have crossed within the last few reporting days."),
    "idle": ("PORT OPEN, NOTHING CROSSING",
             "AMS is still publishing, but the recent reports say no cattle crossed."),
    "closed": ("IMPORTS SUSPENDED",
               "No crossings reported, and no current border report."),
}
headline, explain = words.get(state, ("STATUS UNKNOWN", ""))
ports_txt = ", ".join(S.get("active_ports") or []) or "none"

# The comparison is against the busiest year on record, not against every port
# that has ever appeared: Laredo reported in 2023 and never again, so "of 6
# ever" and "5 were active in 2024" are both true and reading them together
# looks like an inconsistency. Derive one number and use it in both places.
_pyears = sorted({y for d in D["ports"].values() for y in d})
_open_by_year = {y: sum(1 for d in D["ports"].values() if d.get(y))
                 for y in _pyears}
peak_open_year = max(_open_by_year, key=_open_by_year.get) if _open_by_year else "—"
peak_open_n = _open_by_year.get(peak_open_year, 0)

detail = (f"{explain}<br>"
          f"<b>Active crossings:</b> {ports_txt} "
          f"({len(S.get('active_ports') or [])} of the {peak_open_n} open in "
          f"{peak_open_year}) &nbsp;·&nbsp; "
          f"<b>Last crossing:</b> {fmt_date(S.get('last_crossing'))}")
if reop.get("date"):
    detail += (f"<br><b>Reopened:</b> {fmt_date(reop['date'])} — "
               f"{reop['days_since']} days ago, after a "
               f"{reop['gap_days']}-day closure "
               f"(previous crossing {fmt_date(reop['previous_crossing'])})")

st.markdown(
    f'<div class="banner banner-{state}">'
    f'<div class="banner-state">{headline}</div>'
    f'<div class="banner-detail">{detail}</div>'
    + (f'<div class="banner-quote">AMS, {fmt_date(reop["date"])}: '
       f'{reop["note"]}</div>' if reop.get("note") else "")
    + '</div>',
    unsafe_allow_html=True)

# The export-direction note, kept visually separate. Merging it into the banner
# above is the mistake this page is built to avoid.
en = D.get("export_note") or {}
ex_segs = [s for s, d in bd.note_segments(en.get("notes") or "") if d == "export"]
if ex_segs:
    st.caption(
        f"Separately, on the **export** side (US cattle going *to* Mexico), AMS's "
        f"note for the week ending {fmt_date(en.get('end') or en.get('date'))} reads: "
        f"*{' '.join(ex_segs)}* — this does not describe imports."
    )

# ── Data currency ───────────────────────────────────────────────────────────
st.caption(
    f"**Two sources, two different lags.** AMS publishes head counts daily and "
    f"is current to {fmt_date(F['ams_through'])}, with exact weekly totals a "
    f"week behind that. Census is the official customs count with seven years "
    f"of history, but runs about six weeks late — currently through "
    f"**{fmt_month(F['census_through'])}**. So AMS answers *what is crossing "
    f"now* and Census answers *how this compares to a normal year*."
)

st.markdown("<div style='height:10px'></div>", unsafe_allow_html=True)

# ── Year to date ────────────────────────────────────────────────────────────
# The question the page exists to answer once the border reopens: how much has
# actually crossed this year, and against what.
Y = D.get("ytd_ams")
SO = D.get("since_open")
this_yr = date.today().year

st.markdown(f'<div class="sec-header">{this_yr} Year to Date</div>',
            unsafe_allow_html=True)

# Reads left to right from most immediate to broadest context: what crossed on
# the last reporting day, what that adds up to since the border reopened, the
# official year to date, and the same point last year.
daily = D.get("daily") or []
last_day = daily[-1] if daily else None

c = st.columns(4)
with c[0]:
    st.markdown(tile("Daily Head Crossings",
                     f"{last_day[1]:,}" if last_day else "—",
                     sub(f"est., {fmt_date(last_day[0])}" if last_day
                         else "no reporting day yet")), unsafe_allow_html=True)
with c[1]:
    # Summed over the whole YEAR, not from the reopening date. The two are the
    # same number today because nothing crossed before 24 August -- but the
    # label says 2026, so the figure has to be 2026 by construction. Computing
    # it from the reopening and calling it the year total would quietly become
    # wrong the moment AMS backfills an earlier date.
    yr_est = sum(v for _d, v, _w in daily) if daily else None
    st.markdown(tile(f"{this_yr} Estimated Total Crossings",
                     f"~{yr_est:,}" if yr_est is not None else "—",
                     sub(f"est., {fmt_date(daily[0][0])} – "
                         f"{fmt_date(daily[-1][0])}" if daily else "")),
                unsafe_allow_html=True)
with c[2]:
    st.markdown(tile(f"{this_yr} YTD Head",
                     f"{Y['ytd']:,}" if Y else "—",
                     pct_delta(Y.get("pct") if Y else None,
                               f" vs {Y['prior_year']}" if Y else "")
                     + sub(f"AMS actual, through {fmt_date(Y['week_end'])}"
                           if Y else "no YTD published")),
                unsafe_allow_html=True)
with c[3]:
    st.markdown(tile(f"{Y['prior_year']} YTD Head" if Y else "Prior YTD",
                     f"{Y['prior_ytd']:,}" if Y and Y.get("prior_ytd") else "—",
                     sub("same point last year")), unsafe_allow_html=True)

if Y:
    # Derived, not hardcoded: the estimate-vs-actual gap moves every week, and a
    # literal here would quietly go stale while still reading as a measurement.
    est_to_date = sum(v for d, v, _w in daily if str(d) <= str(Y["week_end"]))
    gap = ((est_to_date / Y["ytd"] - 1) * 100) if Y.get("ytd") else None
    st.caption(
        f"**The first two boxes are estimates; the last two are actuals.** The "
        f"daily figures AMS publishes are rounded to the nearest hundred head, "
        f"so the {this_yr} total is approximate and current to "
        f"{fmt_date(SO['latest']) if SO else 'the latest report'}. The YTD is "
        f"AMS's own count, exact but a week behind — and it is AMS's cut-off, "
        f"not one computed here, so a partial year cannot be measured against a "
        f"full one by accident. Over the same span the estimates sum to "
        f"{est_to_date:,} against an actual {Y['ytd']:,}"
        + (f", a {gap:+.1f}% rounding gap" if gap is not None else "")
        + ", which is why the boxes do not tie exactly."
    )

st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)

# ── Import volumes: one chart, monthly or weekly ────────────────────────────
# ONE chart with a toggle rather than two stacked charts: these answer the same
# question at two resolutions, and showing both at once invites reading a
# monthly bar against a weekly one.
with st.container(key="wm-volumes"):
    st.markdown('<div class="sec-header">Import Volumes</div>',
                unsafe_allow_html=True)

    gran = st.radio("Resolution", ["Monthly", "Weekly"], horizontal=True,
                    label_visibility="collapsed", key="vol_gran")

    if gran == "Monthly":
        pts = [(pd.Timestamp(str(pp) + "-01"), h) for pp, h in (D["monthly"] or [])]
        hover = "%{x|%b %Y}<br>%{y:,.0f} head<extra></extra>"
        src_note = (
            f"**US Census**, the official customs count, monthly back to 2019 "
            f"and current to {fmt_month(F['census_through'])}."
        )
    else:
        pts = [(pd.Timestamp(w), h) for w, h in (D.get("weekly") or [])]
        hover = "week of %{x|%b %d, %Y}<br>%{y:,.0f} head<extra></extra>"
        src_note = (
            "**USDA AMS**, weekly actuals. This series **starts in 2023** — AMS "
            "does not publish it any earlier, and Census, which does reach 2019, "
            "publishes monthly only. Splitting Census months into weeks would "
            "invent data, so the weekly view simply starts where the weekly data "
            "does. Switch to Monthly for the longer history."
        )

    if pts:
        xs = [x for x, _h in pts]
        ys = [h for _x, h in pts]
        srt = sorted(ys)
        n = len(srt)
        med = srt[n // 2] if n % 2 else (srt[n // 2 - 1] + srt[n // 2]) / 2
        zeros = sum(1 for v in ys if v == 0)

        fig = go.Figure()
        fig.add_bar(x=xs, y=ys, marker_color=JPSI_BLUE, name="Head",
                    hovertemplate=hover)
        # Right, not left: at "top left" the label lands on top of the y-axis
        # tick numbers and neither can be read. The right end of both charts is
        # the closure period, so it is empty space. The solid background and
        # border keep it legible if a tall bar ever does reach under it.
        fig.add_hline(
            y=med, line_width=1.6, line_dash="dash", line_color=AMBER,
            annotation_text=f"median {med:,.0f}",
            annotation_position="top right",
            annotation_font=dict(color=AMBER, size=11),
            annotation_bgcolor=CARD_BG,
            annotation_bordercolor=AMBER,
            annotation_borderwidth=1,
            annotation_borderpad=3)
        fig.update_layout(
            height=340, margin=dict(l=10, r=24, t=10, b=10),
            paper_bgcolor=CARD_BG, plot_bgcolor=CARD_BG,
            font=dict(color=TEXT, size=11), showlegend=False,
            xaxis=dict(gridcolor=BORDER, title=None),
            yaxis=dict(gridcolor=BORDER, title="Head", tickformat=","),
        )
        st.plotly_chart(fig, use_container_width=True)

        st.markdown(
            f"<div style='color:{MUTED};font-size:0.8rem;margin:-4px 0 6px;'>"
            f"Median <b style='color:{AMBER}'>{med:,.0f} head</b> per "
            f"{'month' if gran == 'Monthly' else 'week'} across "
            f"{n:,} {'months' if gran == 'Monthly' else 'weeks'}"
            f"{f', {zeros} of them zero' if zeros else ''}."
            f"</div>", unsafe_allow_html=True)

        # Say WHAT the median is computed over, not how far it sits from
        # "normal" -- an earlier draft called it "well below a normal trading
        # month", which the numbers do not support: 92,865 against typical
        # months of 100-120k is somewhat below, not dramatically.
        unit = "month" if gran == "Monthly" else "week"
        st.caption(
            src_note
            + (f" The median is taken over **everything plotted, including the "
               f"{zeros} closed {unit}s at zero**, so it sits below a typical "
               f"trading {unit} rather than describing one." if zeros else "")
        )

        if gran == "Monthly":
            st.caption(
                f"**Not every decline here is the border.** The 2021–22 slide — "
                f"from 1.44m head in 2020 to 869,630 in 2022 — was drought and "
                f"herd liquidation in northern Mexico, with the border open the "
                f"whole time; volume then recovered to about 1.24m in 2023 and "
                f"2024. Only the collapse from December 2024 is New World "
                f"Screwworm, and it came in two closures: the first took "
                f"November 2024's 102,751 head to zero that December, then a "
                f"partial reopening ran February–May 2025 before closing again "
                f"in June. Census is current to "
                f"{fmt_month(F['census_through'])}, so the August 2026 "
                f"reopening is not in this chart yet — it should first appear "
                f"in the August 2026 release, around early October."
            )
        else:
            st.caption(
                "The weekly view shows the reopening that the monthly Census "
                "chart cannot yet: the week of 24 August 2026 is the first "
                "non-zero week since July 2025."
            )
    else:
        st.info("No volume data stored for this resolution yet.")

st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)

# ── Daily crossings ─────────────────────────────────────────────────────────
st.markdown('<div class="sec-header">Daily Crossings</div>',
            unsafe_allow_html=True)

# daily was bound above, for the year-to-date boxes.
if daily:
    t_day, t_wtd, t_port, t_hist = st.tabs(
        ["Per day", "Week to date", "By crossing", "Against prior years"])

    with t_day:
        dx = [pd.Timestamp(d) for d, _v, _w in daily]
        dy = [v for _d, v, _w in daily]
        fig = go.Figure()
        fig.add_bar(x=dx, y=dy, marker_color=JPSI_BLUE,
                    hovertemplate="%{x|%a %b %d}<br>%{y:,.0f} head<extra></extra>")
        if SO and SO.get("from"):
            fig.add_vline(x=pd.Timestamp(SO["from"]), line_width=1.5,
                          line_dash="dot", line_color=POS)
            fig.add_annotation(x=pd.Timestamp(SO["from"]), y=1, yref="paper",
                               text="reopened", showarrow=False, yanchor="bottom",
                               font=dict(size=10, color=POS))
        fig.update_layout(
            height=320, margin=dict(l=10, r=10, t=24, b=10),
            paper_bgcolor=CARD_BG, plot_bgcolor=CARD_BG,
            font=dict(color=TEXT, size=11), showlegend=False,
            xaxis=dict(gridcolor=BORDER, title=None),
            yaxis=dict(gridcolor=BORDER, title="Head", tickformat=","))
        st.plotly_chart(fig, use_container_width=True)
        zero = sum(1 for _d, v, _w in daily if v == 0)
        st.caption(
            f"Every reporting day in {this_yr}: {len(daily)} days, "
            f"{len(daily) - zero} with cattle and {zero} published with none. "
            f"Head counts are AMS estimates, rounded to the nearest hundred."
        )
        st.dataframe(
            pd.DataFrame([{"Date": d, "Head": v, "Week to date": w}
                          for d, v, w in reversed(daily)]),
            use_container_width=True, hide_index=True)

    with t_wtd:
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=[pd.Timestamp(d) for d, _v, w in daily],
            y=[w for _d, _v, w in daily], mode="lines+markers",
            line=dict(color=AMBER, width=2), marker=dict(size=6),
            hovertemplate="%{x|%a %b %d}<br>%{y:,.0f} head WTD<extra></extra>"))
        fig.update_layout(
            height=320, margin=dict(l=10, r=10, t=10, b=10),
            paper_bgcolor=CARD_BG, plot_bgcolor=CARD_BG,
            font=dict(color=TEXT, size=11), showlegend=False,
            xaxis=dict(gridcolor=BORDER, title=None),
            yaxis=dict(gridcolor=BORDER, title="Head, week to date",
                       tickformat=","))
        st.plotly_chart(fig, use_container_width=True)
        st.caption(
            "AMS's running week-to-date total, which **resets each Monday** — "
            "the sawtooth is the reset, not a collapse in trade. Shown because "
            "it is how the AMS report itself presents the week."
        )

    with t_port:
        bc = D.get("by_crossing") or []
        if bc:
            st.dataframe(
                pd.DataFrame([{"Crossing": p, "State": s, f"{this_yr} head": v}
                              for p, s, v in bc]),
                use_container_width=True, hide_index=True)
            st.caption(
                "Per-crossing detail. These are a **breakdown, not an exact "
                "decomposition** — AMS's per-crossing rows disagreed with its "
                "own published total on 19 of 463 days measured, so the "
                "headline figures above use AMS's total row rather than a sum "
                "of these."
            )
        else:
            st.info(f"No per-crossing detail reported yet in {this_yr}.")

    with t_hist:
        by = D.get("by_year") or {}
        if by:
            years = sorted(by)
            fig = go.Figure()
            fig.add_bar(x=years, y=[by[y]["head"] for y in years],
                        marker_color=JPSI_BLUE, name="Head",
                        hovertemplate="%{x}<br>%{y:,.0f} head<extra></extra>")
            fig.update_layout(
                height=300, margin=dict(l=10, r=10, t=10, b=10),
                paper_bgcolor=CARD_BG, plot_bgcolor=CARD_BG,
                font=dict(color=TEXT, size=11), showlegend=False,
                xaxis=dict(gridcolor=BORDER, title=None, type="category"),
                yaxis=dict(gridcolor=BORDER, title="Head", tickformat=","))
            st.plotly_chart(fig, use_container_width=True)
            st.dataframe(
                pd.DataFrame([{"Year": y, "Head (AMS est.)": by[y]["head"],
                               "Reporting days": by[y]["days"],
                               "Head per reporting day":
                                   round(by[y]["head"] / by[y]["days"])
                                   if by[y]["days"] else 0}
                              for y in years]),
                use_container_width=True, hide_index=True)
            st.caption(
                "Whole-year totals from the same daily series. **2023 is "
                "incomplete** — AMS's daily volume section only runs from part "
                "way through that year (156 reporting days against 225 in "
                "2024), so its total is not comparable. 2024 and 2025 tie to "
                "Census within about 3%, which is the cross-check that the "
                "estimates are sound."
            )
else:
    st.info("No daily receipts stored for this year yet.")

st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)

# ── Border prices ───────────────────────────────────────────────────────────
# The border quote is on the SAME basis as the index -- $/cwt, F.O.B., Medium
# and Large, #1-2 steers -- which is what makes subtracting the two legitimate.
st.markdown('<div class="sec-header">Border Prices</div>', unsafe_allow_html=True)

grid, grid_date = D.get("price_grid", ([], None))
spread = D.get("spread") or []
spread_yr = D.get("spread_yr") or {}
cov = D.get("price_cov") or {}

if grid:
    latest = spread[-1] if spread else None
    cur_yr_s = spread_yr.get(str(this_yr))
    prev_yr_s = spread_yr.get(str(this_yr - 1))

    c = st.columns(4)
    with c[0]:
        st.markdown(tile("700–800 lb #1-2 Steers",
                         f"${latest[1]:,.2f}" if latest else "—",
                         sub(f"Douglas, {fmt_date(latest[0])}" if latest
                             else "not quoted")), unsafe_allow_html=True)
    with c[1]:
        st.markdown(tile("CME Feeder Index",
                         f"${latest[2]:,.2f}" if latest else "—",
                         sub("same day, 12-state 700–899 lb")),
                    unsafe_allow_html=True)
    with c[2]:
        st.markdown(tile("Border Basis",
                         f"${latest[3]:,.2f}" if latest else "—",
                         sub("border minus index, $/cwt")), unsafe_allow_html=True)
    with c[3]:
        st.markdown(tile(f"{this_yr} Avg Basis",
                         f"${cur_yr_s['mean']:,.2f}" if cur_yr_s else "—",
                         sub(f"vs ${prev_yr_s['mean']:,.2f} in {this_yr - 1}"
                             f" · n={cur_yr_s['n']}" if cur_yr_s and prev_yr_s
                             else "")), unsafe_allow_html=True)

    if cur_yr_s and prev_yr_s:
        # Dollar signs MUST be escaped in st.caption. Two unescaped ones in the
        # same string make Streamlit treat everything between them as LaTeX
        # math, and this caption rendered as a wall of italic variables before
        # the escapes went in. The tiles above are exempt because they are raw
        # HTML. Escape in prose, never inside a code fence.
        st.caption(
            f"**The border discount has roughly halved.** Mexican cattle at "
            f"Douglas averaged **\\${prev_yr_s['mean']:,.2f}/cwt** under the "
            f"index in {this_yr - 1} and **\\${cur_yr_s['mean']:,.2f}** in "
            f"{this_yr} — consistent with scarcity, since the few head crossing "
            f"are bid much closer to the US market. Read the {this_yr} figure "
            f"with care: it rests on **{cur_yr_s['n']} quoted days** against "
            f"{prev_yr_s['n']} last year."
        )

    t_now, t_wt, t_sp = st.tabs(
        ["Latest quotes", "By weight bracket", "vs CME index"])

    with t_now:
        st.dataframe(
            pd.DataFrame([{
                "Class": c_, "Weight": f"{wl}–{wh} lb" if wh else f"{wl}+ lb",
                "Grade": g or "—", "Low": lo, "High": hi, "Mid": mid,
                "Crossing": cp,
            } for c_, wl, wh, g, lo, hi, mid, cp in grid]),
            use_container_width=True, hide_index=True)
        st.caption(
            f"AMS quotes for **{fmt_date(grid_date)}**, $/cwt F.O.B. Prices are "
            f"published only when enough head sell to establish a trend, so a "
            f"day can report cattle crossing and carry no quote at all — in "
            f"{this_yr} there were "
            f"{cov.get(str(this_yr), {}).get('price_days', 0)} quoted days "
            f"against {len(daily)} reporting days."
        )

    with t_wt:
        ser = D.get("price_series") or {}
        if ser:
            fig = go.Figure()
            for label, pts in sorted(ser.items(),
                                     key=lambda kv: int(kv[0].split("-")[0])):
                fig.add_trace(go.Scatter(
                    x=[pd.Timestamp(d) for d, _p in pts],
                    y=[p for _d, p in pts], mode="lines", name=label,
                    hovertemplate=f"{label}<br>%{{x|%b %d, %Y}}"
                                  "<br>$%{y:,.2f}/cwt<extra></extra>"))
            fig.update_layout(
                height=340, margin=dict(l=10, r=10, t=10, b=10),
                paper_bgcolor=CARD_BG, plot_bgcolor=CARD_BG,
                font=dict(color=TEXT, size=11),
                legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
                xaxis=dict(gridcolor=BORDER, title=None),
                yaxis=dict(gridcolor=BORDER, title="$/cwt F.O.B."))
            st.plotly_chart(fig, use_container_width=True)
            st.caption(
                "#1-2 Medium & Large steers, one line per weight bracket. "
                "**Kept separate on purpose:** AMS's brackets moved between 2024 "
                "and 2025 — it quoted 300–400/400–500/500–600 through 2024 and "
                "500–600/600–700/700–800 from 2025 — so a single blended "
                "\"border price\" line would fold that change straight into the "
                "trend and show a jump that is pure mix. The 700–800 lb bracket "
                "simply does not exist before February 2025."
            )

    with t_sp:
        if spread:
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=[pd.Timestamp(d) for d, _b, _f, _s in spread],
                y=[b for _d, b, _f, _s in spread], mode="lines+markers",
                name="Border, 700–800 #1-2", line=dict(color=AMBER, width=2),
                marker=dict(size=5)))
            fig.add_trace(go.Scatter(
                x=[pd.Timestamp(d) for d, _b, _f, _s in spread],
                y=[f for _d, _b, f, _s in spread], mode="lines+markers",
                name="CME Feeder Index", line=dict(color=JPSI_BLUE, width=2),
                marker=dict(size=5)))
            fig.update_layout(
                height=320, margin=dict(l=10, r=10, t=10, b=10),
                paper_bgcolor=CARD_BG, plot_bgcolor=CARD_BG,
                font=dict(color=TEXT, size=11),
                legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
                xaxis=dict(gridcolor=BORDER, title=None),
                yaxis=dict(gridcolor=BORDER, title="$/cwt"))
            st.plotly_chart(fig, use_container_width=True)

            st.dataframe(
                pd.DataFrame([{"Year": y, "Quoted days": d["n"],
                               "Mean basis": round(d["mean"], 2),
                               "Median basis": round(d["median"], 2)}
                              for y, d in spread_yr.items()]),
                use_container_width=True, hide_index=True)
            st.caption(
                "Both series are **$/cwt F.O.B.**, which is what makes "
                "subtracting them meaningful — verified across all 10,401 price "
                "rows, every one of which is Per Cwt and F.O.B. The comparison "
                "is not exact: the border quote is 700–800 lb Mexican-origin "
                "cattle at one crossing, the index is 700–899 lb US cattle sold "
                "at auction and direct across 12 states. The gap is a real "
                "market relationship — origin, quality, freight and who is "
                "buying — not a mispricing. The index value used is JSA's "
                "same-day reconstruction rather than CME's published file, "
                "which runs 1–3 days behind; a spread against a stale index "
                "would mostly measure the staleness."
            )
        else:
            st.info("No overlapping days between border quotes and the index.")
else:
    st.info("No border price quotes stored yet.")

st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)

# ── Tiles ───────────────────────────────────────────────────────────────────
st.markdown('<div class="sec-header">Current Activity</div>', unsafe_allow_html=True)

this_year = str(date.today().year)
last_year = str(date.today().year - 1)
cy = D["crossings"].get(this_year, {"crossings": 0, "zero": 0, "reports": 0})
ly = D["crossings"].get(last_year, {"crossings": 0, "zero": 0, "reports": 0})

c = st.columns(4)
with c[0]:
    st.markdown(tile("Import Status", headline.split(",")[0].title(),
                     sub(f"as of {fmt_date(S.get('latest_report'))}")),
                unsafe_allow_html=True)
with c[1]:
    st.markdown(tile(f"Crossing Days {this_year}", f"{cy['crossings']:,}",
                     sub(f"{cy['zero']} published days with no cattle")),
                unsafe_allow_html=True)
with c[2]:
    st.markdown(tile(f"Crossing Days {last_year}", f"{ly['crossings']:,}",
                     sub("same measure, full year")), unsafe_allow_html=True)
with c[3]:
    st.markdown(tile("Days Since Reopening",
                     f"{reop['days_since']:,}" if reop.get("days_since") is not None else "—",
                     sub(f"reopened {fmt_date(reop.get('date'))}"
                         if reop.get("date") else "no reopening on record")),
                unsafe_allow_html=True)

st.caption(
    "Crossing days count report days on which cattle actually crossed. AMS began "
    "publishing on zero-crossing days in 2026, so counting reports instead would "
    f"read {cy['reports']} for {this_year} and understate the closure. It is a "
    "proxy for activity, not a head count — a crossing day covers whatever "
    "crossed that day, at whatever size."
)

st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)

# ── Volume tiles ────────────────────────────────────────────────────────────
st.markdown('<div class="sec-header">Head Counts — Census</div>', unsafe_allow_html=True)

ann = D["annual"]
yrs = sorted(ann)
prev_full = [y for y in yrs if ann[y] > 0]
c = st.columns(4)
for i, y in enumerate(yrs[-3:]):
    d = D["ytd"].get(y, {})
    with c[i]:
        st.markdown(tile(f"{y} Feeder Head", f"{ann[y]:,}",
                         pct_delta(d.get("pct"), " vs prior YTD")
                         + sub(f"{len(d.get('months', []))} months on file")),
                    unsafe_allow_html=True)
with c[3]:
    peak = max(ann.values()) if ann else 0
    latest = ann[yrs[-1]] if yrs else 0
    drop = (latest / peak - 1) * 100 if peak else None
    st.markdown(tile("vs Peak Year", f"{drop:+.0f}%" if drop is not None else "—",
                     sub(f"{max(ann, key=ann.get)} peak of {peak:,} head"
                         if ann else "")), unsafe_allow_html=True)

# ── Monthly series ──────────────────────────────────────────────────────────
# ── Annual + crossing days, the two sources side by side ────────────────────
st.markdown('<div class="sec-header">Both Sources, By Year</div>',
            unsafe_allow_html=True)
years_all = sorted(set(list(map(str, ann.keys())) + list(D["crossings"].keys())))
fig = go.Figure()
fig.add_bar(x=years_all, y=[ann.get(int(y), 0) for y in years_all],
            marker_color=JPSI_BLUE, name="Census head",
            hovertemplate="%{x}<br>%{y:,.0f} head<extra></extra>")
fig.add_trace(go.Scatter(
    x=years_all,
    y=[D["crossings"].get(y, {}).get("crossings", 0) for y in years_all],
    yaxis="y2", mode="lines+markers", name="Crossing days",
    line=dict(color=AMBER, width=2.5), marker=dict(size=8),
    hovertemplate="%{x}<br>%{y:,.0f} crossing days<extra></extra>"))
fig.update_layout(
    height=320, margin=dict(l=10, r=10, t=10, b=10),
    paper_bgcolor=CARD_BG, plot_bgcolor=CARD_BG,
    font=dict(color=TEXT, size=11),
    legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
    xaxis=dict(gridcolor=BORDER, title=None, type="category"),
    yaxis=dict(gridcolor=BORDER, title="Census head", tickformat=","),
    yaxis2=dict(overlaying="y", side="right", title="Crossing days",
                showgrid=False),
)
st.plotly_chart(fig, use_container_width=True)
st.caption(
    "The two independent sources track each other, which is the point of "
    f"showing them together — where they diverge, the AMS line leads. "
    f"{this_year} has {cy['crossings']} crossing days against a Census bar of "
    "zero, because the reopening has not reached Census yet."
)

# ── Ports ───────────────────────────────────────────────────────────────────
st.markdown('<div class="sec-header">Which Crossings Are Open</div>',
            unsafe_allow_html=True)
if D["ports"]:
    pyears = sorted({y for d in D["ports"].values() for y in d})
    prows = []
    for p, d in D["ports"].items():
        row = {"Crossing": bd.title_port(p)}
        for y in pyears:
            row[y] = d.get(y, 0)
        prows.append(row)
    st.dataframe(pd.DataFrame(prows), use_container_width=True, hide_index=True)
    st.caption(
        f"Crossing days per year, per port of entry. {peak_open_n} crossings "
        f"were active in {peak_open_year}; the reopening has restarted "
        f"{len(S.get('active_ports') or [])} of them. Zero-crossing days are "
        "excluded, so a port publishing “no cattle crossed” does not count as "
        "open here."
    )

# ── Weight composition ──────────────────────────────────────────────────────
st.markdown('<div class="sec-header">What Crosses — Weight Composition</div>',
            unsafe_allow_html=True)
if D["bands"]:
    bands = D["bands"]
    fig = go.Figure()
    fig.add_bar(x=[h for _, h, _ in bands], y=[b for b, _, _ in bands],
                orientation="h", marker_color=JPSI_BLUE,
                text=[f"{s:.1f}%" for _, _, s in bands], textposition="outside",
                hovertemplate="%{y}<br>%{x:,.0f} head<extra></extra>")
    fig.update_layout(
        height=250, margin=dict(l=10, r=40, t=10, b=10),
        paper_bgcolor=CARD_BG, plot_bgcolor=CARD_BG,
        font=dict(color=TEXT, size=11), showlegend=False,
        xaxis=dict(gridcolor=BORDER, title="Head", tickformat=","),
        yaxis=dict(gridcolor=BORDER, title=None,
                   categoryorder="array",
                   categoryarray=[b for b, _, _ in bands][::-1]),
    )
    st.plotly_chart(fig, use_container_width=True)
    st.caption(
        f"Latest year with volume: **{D['band_year']}**. Census's top band is "
        "“320 kg or more”, and 320 kg is 705 lb — the very bottom of the CME "
        "index's 700–899 lb window. So nearly all Mexican cattle cross *below* "
        "index weight and only reach it after months on US feed. **An import cut "
        "moves the index with a lag, through supply — it never shows up in the "
        "index's own composition.** Imported cattle mostly go straight to "
        "feedyards under retained ownership and never sell through a "
        "USDA-reported auction, so they are not index-eligible."
    )

    if D["kinds"]:
        kt = D["kinds"]
        parts = " · ".join(f"{k}: {v:,}" for k, v in
                           sorted(kt.items(), key=lambda t: -t[1]))
        st.caption(
            f"{D['kind_year']} by entry type — {parts}. Only the feeder bucket "
            "is charted above: cattle entered for immediate slaughter, breeding "
            "stock and dairy cows answer different questions."
        )

# ── Commentary log ──────────────────────────────────────────────────────────
st.markdown('<div class="sec-header">Border Market Commentary</div>',
            unsafe_allow_html=True)
if D["commentary"]:
    crows = [{"Date": c["date"],
              "Crossed": "Yes" if c["crossed"] else "No",
              "Crossing": c["port"] or "—",
              "Report": c["text"]}
             for c in D["commentary"]]
    st.dataframe(pd.DataFrame(crows), use_container_width=True, hide_index=True,
                 column_config={"Report": st.column_config.TextColumn(width="large")})
    st.caption(
        "AMS's own words, newest first — trade tone, demand, and what the supply "
        "consisted of. The head counts above come from the same report's volume "
        "section; this is the colour that no number carries."
    )

# ── Suspension timeline ─────────────────────────────────────────────────────
with st.expander("Suspension timeline, in AMS's own words"):
    st.caption(
        "Import-relevant announcements only. AMS's status report covers both "
        "directions and its notes are classified by direction before being "
        "shown here — the September 2026 standing note is about **exports** to "
        "Mexico and is deliberately excluded from this list."
    )
    tl = D["timeline"]
    if tl:
        # Collapse consecutive identical announcements to their date range: the
        # same "IMPORTS ARE SUSPENDED" line repeats weekly for months, and 40
        # identical rows hide the handful of dates where something changed.
        collapsed, run = [], None
        for end, segs in tl:
            key = " | ".join(segs)
            if run and run["key"] == key:
                run["from"] = end
            else:
                if run:
                    collapsed.append(run)
                run = {"key": key, "from": end, "to": end, "segs": segs}
        if run:
            collapsed.append(run)
        for r in collapsed:
            span = (fmt_date(r["to"]) if r["from"] == r["to"]
                    else f"{fmt_date(r['from'])} – {fmt_date(r['to'])}")
            st.markdown(f"**{span}** — {' '.join(r['segs'])}")
    else:
        st.info("No status announcements stored.")

# ── Method ──────────────────────────────────────────────────────────────────
with st.expander("Sources and method"):
    st.markdown(f"""
**AMS (USDA Market News), current to {fmt_date(F['ams_through'])}**

- Report 3486, *Mexico to United States Feeder Cattle Import Summary* —
  section **Report Volume** gives daily receipts by crossing point
  (`receipts_current_est`, rounded to the nearest hundred head) and the
  week-to-date running total; section **Report Header** gives the narrative log.
- Report 3629, *U.S. – Mexico Livestock Imports/Exports* — section **Report
  Volume** gives exact weekly volumes with AMS's own year-to-date and
  prior-year-to-date; **Report Header** gives the weekly status note.
- MARS sections are **path** segments (`/reports/3486/Report%20Volume`). Passing
  `section` as a query parameter is accepted and silently ignored, returning the
  header — which is how this source was first mistaken for having no data.
- Daily figures are AMS **estimates**; weekly and YTD figures are **actuals**.
  Through 2026-09-04 the daily estimates summed to ~2,600 against an actual
  2,557 — a 1.7% rounding gap.
- Head counts use AMS's own "All Crossing Points / All Crossing States" row.
  The per-crossing rows are hierarchical rollups that triple-count if summed,
  and they disagreed with the published total on 19 of 463 days measured.
- Crossing days exclude days AMS published but reported no cattle crossing. AMS
  only began publishing those in 2026, so the raw report count understates the
  closure.

**Census (International Trade API), current to {fmt_month(F['census_through'])}**

- Live bovine animals, HS 0102, from Mexico (country code 2010), monthly,
  general imports, at the ten-digit commodity level.
- Quantity is Census's `UNIT_QY1`, checked on ingest to be “NO.” (number of
  head) rather than assumed.
- The HS10 code list is **discovered, not hardcoded** — the ten-digit breakouts
  get renumbered, and a code carrying all the volume one year can be empty the
  next. Entry types are classified at read time from the description, splitting
  off the “OTHER THAN PUREBRED BREEDING AND/OR DAIRY” exclusion clause first.
- Census publishes about six weeks after month end, so this series cannot
  answer what crossed last week. That is what the AMS status above is for.

**Not shown, and why**

- No price series **yet**. Report 3486's *Report Detail Current* section does
  carry structured prices, weight breaks, frame and muscle grade — it is simply
  not ingested here, and is the obvious next addition. Census value-per-head is
  a declared customs value that moves with both the market and the weight mix,
  so it is a level check rather than a quote.
""")

st.markdown("<hr style='margin:18px 0 8px;'>", unsafe_allow_html=True)
st.markdown(
    f'<div class="srcline">JSA · John Stewart &amp; Associates &nbsp;·&nbsp; '
    f'Border status USDA AMS Market News · Head counts US Census Bureau '
    f'International Trade &nbsp;·&nbsp; AMS through {fmt_date(F["ams_through"])} · '
    f'Census through {fmt_month(F["census_through"])}</div>',
    unsafe_allow_html=True)
