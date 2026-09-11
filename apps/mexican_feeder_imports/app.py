"""
Mexican Feeder Imports -- how much Mexican cattle is reaching US feedyards.

Mexico normally supplies about 1.25 million feeder cattle a year, roughly 4% of
the US calf crop and concentrated in the southern Plains. New World Screwworm
suspensions cut that to 214,394 head in 2025 and to zero for the first seven
months of 2026. Douglas, AZ reopened on 24 August 2026 -- one crossing of five.

THE PAGE IS BUILT AROUND A LAG. Census carries the head counts but runs about
six weeks behind; AMS carries the border status daily but publishes no numbers
at all (every one of its seven International Livestock reports returns empty
data fields through MARS). So the top of the page is AMS -- current to
yesterday, qualitative -- and the volume charts below are Census, clearly
labelled with what they are current to. In September 2026 a Census-only page
would have shown zero imports all year and said nothing about the reopening
three weeks earlier.

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
    st.caption("Border status from USDA AMS · head counts from Census trade data")
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
    f"**Two sources, two different lags.** Border status and crossing activity "
    f"are current to {fmt_date(F['ams_through'])}. Census head counts run about "
    f"six weeks behind and are current to **{fmt_month(F['census_through'])}**; "
    f"the last month with any volume was {fmt_month(F['census_last_volume'])}. "
    f"The charts below are Census, so a reopening shows up in the banner weeks "
    f"before it reaches them."
)

st.markdown("<div style='height:10px'></div>", unsafe_allow_html=True)

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
with st.container(key="wm-monthly"):
    st.markdown('<div class="sec-header">Monthly Imports, Feeder Cattle</div>',
                unsafe_allow_html=True)
    m = D["monthly"]
    if m:
        mx = [pd.Timestamp(str(p) + "-01") for p, _ in m]
        my = [h for _, h in m]
        fig = go.Figure()
        fig.add_bar(x=mx, y=my, marker_color=JPSI_BLUE, name="Head",
                    hovertemplate="%{x|%b %Y}<br>%{y:,.0f} head<extra></extra>")
        fig.update_layout(
            height=340, margin=dict(l=10, r=10, t=10, b=10),
            paper_bgcolor=CARD_BG, plot_bgcolor=CARD_BG,
            font=dict(color=TEXT, size=11), showlegend=False,
            xaxis=dict(gridcolor=BORDER, title=None),
            yaxis=dict(gridcolor=BORDER, title="Head", tickformat=","),
        )
        st.plotly_chart(fig, use_container_width=True)
        st.caption(
            f"**Not every decline here is the border.** The 2021–22 slide — from "
            f"1.44m head in 2020 to 869,630 in 2022 — was drought and herd "
            f"liquidation in northern Mexico, with the border open the whole "
            f"time; volume then recovered to about 1.24m in 2023 and 2024. Only "
            f"the collapse from December 2024 is New World Screwworm, and it came "
            f"in two closures: the first took November 2024's 102,751 head to "
            f"zero that December, then a partial reopening ran February–May 2025 "
            f"before closing again in June. "
            f"Census is current to {fmt_month(F['census_through'])}, so the "
            f"August 2026 reopening is not in this chart yet — it should first "
            f"appear in the August 2026 release, around early October."
        )
    else:
        st.info("No Census months stored yet.")

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
        "AMS's own words, newest first. This is the only place the weight ranges "
        "and trade tone appear at all — MARS returns no structured fields for "
        "these reports, so the narrative is the data."
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

- Report 3486, *Mexico to United States Feeder Cattle Import Summary* — the
  narrative log and crossing activity.
- Report 3629, *U.S. – Mexico Livestock Imports/Exports* — the weekly status
  note.
- Every one of AMS's seven International Livestock reports returns **zero
  structured data fields** through the MARS API. The published head counts exist
  only in the report body on mymarketnews, not in the API, which is why the
  volumes here come from Census instead.
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

- No price series. AMS quotes the border market in the narrative but publishes
  no structured prices for these reports, and Census value-per-head is a
  declared customs value that moves with both the market and the weight mix —
  useful as a level check, not as a quote.
""")

st.markdown("<hr style='margin:18px 0 8px;'>", unsafe_allow_html=True)
st.markdown(
    f'<div class="srcline">JSA · John Stewart &amp; Associates &nbsp;·&nbsp; '
    f'Border status USDA AMS Market News · Head counts US Census Bureau '
    f'International Trade &nbsp;·&nbsp; AMS through {fmt_date(F["ams_through"])} · '
    f'Census through {fmt_month(F["census_through"])}</div>',
    unsafe_allow_html=True)
