"""
Cattle Cycles — where this run sits against every one since 1913.

STAFF ONLY, AND UNLISTED. `portal_auth.require_admin()` is the first thing that
runs, and `Home.py` registers this under `TOOLS` rather than `DASHBOARDS`, the
same treatment the letter tool and the Market Board get: no home-grid tile, no
nav entry, no route at all for a client. Signing in reveals all three together.

IT NEEDS NO SECRET, AND SNOWFLAKE IS A PREFERENCE RATHER THAN A DEPENDENCY.
Both feeds behind this page are keyless — USDA NASS monthly price received and
BLS CPI-U, stored as published — and the committed seed in
`data/cattle_cycles.json` is enough to draw every figure on the page. What the
seed cannot do is advance: it only moves when somebody regenerates it. So
`deploy/refresh_cattle_cycles.py` keeps JSA.CME_FEEDER_CATTLE.CATTLE_CYCLE_PRICES
current from the droplet and `cycles.load()` prefers that table, falling back
to the file whenever it is empty, short or unreachable. No outage can blank
this page; one can only stop it advancing. Because it degrades that quietly,
the caption names which of the two it is reading, and the as-of month is
printed at the top rather than left to be inferred.

THE ARITHMETIC IS NOT IN THIS FILE. `cycles.py` dates the turning points and
owns every judgement about what counts as a phase; this file renders. That
split is the `cof_recap` / `leverage` / `am_cutout` shape, and it is what lets
`tests/test_cattle_cycles.py` pin the dating without rendering anything.

WHAT THE DEFAULT VIEW IS FOR. "How much is left in this one" is the staff
question, so the page opens on the current run overlaid on every completed one
— not on the long record, which is a click away. The overlay is indexed rather
than levelled because the 1930s traded at a fifth of today's real price and on
a shared axis the SHAPE, which is the whole question, disappears.
"""

import importlib.util
import sys
from pathlib import Path

import streamlit as st

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO))

import portal_auth  # noqa: E402

portal_auth.require_admin("Cattle Cycles")

import numpy as np   # noqa: E402
import plotly.graph_objects as go  # noqa: E402

import cycles  # noqa: E402


def _load_db():
    """apps/us_cow_herd/snowflake_db.py, under a PRIVATE module name.

    `snowflake_db` exists FIVE times in this repo and several pages import it
    by bare name, so whichever page loads first decides which copy every other
    page gets. A page running against another page's connection logic raises
    nothing and gives no clue which copy it got. "_cyc_page_db" can never join
    that collision — the same trick letter/draft_store.py uses, and reusing the
    file rather than copying its key-pair logic means there is no sixth copy of
    that to drift either.
    """
    path = REPO / "apps" / "us_cow_herd" / "snowflake_db.py"
    spec = importlib.util.spec_from_file_location("_cyc_page_db", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_cyc_page_db"] = mod
    spec.loader.exec_module(mod)
    return mod


_DB = _load_db()

# -- palette -----------------------------------------------------------------
# No shared palette module exists; every page declares its own. This is the DM_
# family, used whole rather than mixed with the unprefixed one. DM_ reads as
# "dark mode" and is not — .streamlit/config.toml pins the app to light.
JSA_GREEN = "#5e7164"
JSA_GREEN_LT = "#8db89a"
DM_BG = "#f6f8f7"
DM_SURFACE = "#ffffff"
DM_SURFACE2 = "#eef3f0"
DM_BORDER = "#d7e2dc"
DM_TEXT = "#32373c"
DM_MUTED = "#5f7267"
COL_NEU = "#5f7267"
BULL_BAND = "rgba(141,184,154,0.18)"
BEAR_BAND = "rgba(120,113,108,0.13)"
PAST_LINE = "rgba(95,114,103,0.33)"

# At module level with the other style constants, never beside the first chart
# that uses it — apps/beef_cutout/app.py records a NameError that fired only for
# the reader who opened a different view.
# The overlay chart's plot box: 430 tall less its 10px margins and roughly
# 45px of x-axis furniture. Used only to turn index units into screen pixels
# for label decluttering, so an approximation is fine -- being a few pixels
# out means slightly more or less separation, never an overlap.
CHART_PX = 430
PLOT_PX = CHART_PX - 10 - 10 - 45
LABEL_PX = 19          # a label measures 14px tall; this is that plus room

AXIS = dict(
    gridcolor=DM_BORDER, linecolor=DM_BORDER, showgrid=True,
    tickfont=dict(color=DM_MUTED, size=11),
    title_font=dict(color=DM_MUTED, size=11), zeroline=False,
)

# Five tiles share this row. At 1440px a fifth tile is 128px wide, and 20px of
# side padding leaves an 86px content box — narrower than "$229" at 1.65rem, at
# which point the value breaks between characters and renders as two lines.
_CSS = """
<style>
.cyc-tiles { display:flex; gap:10px; margin:6px 0 18px 0; }
.cyc-tile { flex:1 1 0; background:#ffffff; border:1px solid #d7e2dc;
            border-radius:6px; padding:16px 10px; min-width:0; }
.cyc-label { color:#5f7267; font-size:0.74rem; letter-spacing:0.02em;
             text-transform:uppercase; margin-bottom:6px; }
.cyc-value { color:#32373c; font-size:1.45rem; font-weight:600;
             white-space:nowrap; }
.cyc-delta { font-size:0.80rem; margin-top:4px; white-space:nowrap; }
.cyc-sub   { color:#5f7267; font-size:0.74rem; margin-top:4px; line-height:1.35; }
.cyc-note  { background:#eef3f0; border:1px solid #d7e2dc; border-left:3px solid #5e7164;
             border-radius:4px; padding:10px 13px; color:#32373c; font-size:0.86rem;
             line-height:1.5; margin:4px 0 16px 0; }
</style>
"""
st.html(_CSS)


def money_md(text: str) -> str:
    """Escape dollar signs for markdown.

    A PAIR of unescaped dollar signs opens an inline LaTeX span: Streamlit
    swallows everything between them, the signs vanish and any bold markers
    inside come out as literal asterisks. One is safe; two is the bug, and it
    has shipped on this portal three times.
    """
    return text.replace("$", r"\$")


def tile(label: str, value: str, delta: str = "", sub: str = "") -> str:
    d = f'<div class="cyc-delta" style="color:{COL_NEU};">{delta}</div>' if delta else ""
    s = f'<div class="cyc-sub">{sub}</div>' if sub else ""
    return (f'<div class="cyc-tile"><div class="cyc-label">{label}</div>'
            f'<div class="cyc-value">{value}</div>{d}{s}</div>')


def yrs(months: int) -> str:
    return f"{months / 12:.1f} years"


def label_offsets(runs: list, y_span: float, x_span: float) -> dict:
    """Vertical pixel offsets that stop end-of-line labels sitting on each other.

    Thirteen runs end wherever they end, and four of them finish within a few
    months and a few index points of one another — on the first build
    1923-1929 sat on top of 1945-1951, and 1967-1973 sat on top of the current
    run, which is the one label on the chart nobody can afford to lose.

    Plotly does not declutter annotations, so this does: labels are placed
    from the top down, and one that would land on an already-placed label
    sharing its stretch of the x-axis is pushed below it. The anchor stays
    on the true endpoint and a leader is drawn to it, so a nudged label
    still says exactly which line it belongs to.

    Tolerances are fractions of the plotted span rather than fixed numbers, so
    they keep meaning if the series grows or the user changes the minimum
    phase and the runs move.

    THE CHECK IS AGAINST WHERE LABELS LAND, NOT WHERE THEY STARTED. The first
    version counted how many earlier endpoints were nearby and offset by a
    fixed step per neighbour, which does not separate anything: two labels
    offset by different amounts can still coincide, and a label nudged up can
    land on one that never moved. It left two pairs overlapping and made one
    of them worse. Greedy placement against the running list of FINAL
    positions is the fix.
    """
    if not runs or y_span <= 0:
        return {}
    # Screen pixels per index unit, from the plot box this figure actually
    # asks for: 430 tall less its margins and the x-axis furniture, over the
    # range plotly will show (it pads a little beyond the data).
    px_per_unit = PLOT_PX / (y_span * 1.1)
    x_tol = x_span * 0.09
    ordered = sorted(runs, key=lambda r: r["y"][-1], reverse=True)
    out, placed = {}, []          # placed: (x_end, final screen y in px)
    for run in ordered:
        x, y = run["x"][-1], run["y"][-1]
        home = -y * px_per_unit   # screen y grows downward, index grows up
        cand, moved = home, True
        while moved:
            moved = False
            for px_end, py_final in placed:
                if abs(px_end - x) <= x_tol and abs(py_final - cand) < LABEL_PX:
                    cand, moved = py_final + LABEL_PX, True
        # ay is POSITIVE-DOWN here, measured rather than read off the docs,
        # whose "arrow pointing from bottom to top" wording supports either
        # reading. Flipping it piles every label into the one above instead.
        out[id(run)] = round(cand - home)
        placed.append((x, cand))
    return out


def span_label(run: dict) -> str:
    """The years a run covers, for labelling its line on the overlay.

    BOTH YEARS IN FULL. "1998-01" is four characters shorter and asks the
    reader to decide whether it ended in 2001 or 1901, which is exactly the
    kind of label this page is not allowed to print. A run that opens and
    closes inside one year gets that year alone rather than "1933-1933".
    """
    a, b = run["start"], run["end"]
    if run.get("running"):
        return f"{a:%Y}–now"
    return f"{a:%Y}" if a.year == b.year else f"{a:%Y}–{b:%Y}"


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def load_summary(schema: int = cycles.SCHEMA, key: str = cycles.DEFAULT_SERIES,
                 real: bool = True, min_phase: int = cycles.MIN_PHASE_MONTHS):
    """Dating is cheap but not free, and the result is a pure function of these four.

    `schema` is in the signature AND passed at the call site. A default alone is
    not part of the cache key — st.cache_data hashes the arguments it is CALLED
    with — and a leading underscore would ask Streamlit to drop it outright.
    Both halves, or the guard is inert.
    """
    # ONLY CONNECT WHEN SNOWFLAKE IS THE BACKEND. get_conn() hands back SQLite
    # when USE_SNOWFLAKE is unset, which would mean opening (and creating)
    # another page's local database file to run a query that cannot succeed
    # against it. cycles.load(None) reads the committed seed, which is the
    # right answer on a developer machine.
    conn = None
    if _DB.use_snowflake():
        try:
            conn = _DB.get_conn()
        except Exception:
            conn = None          # the seed still renders the whole page
    try:
        seed = cycles.load(conn)
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
    if not seed:
        return None
    return cycles.summary(seed, key=key, real=real, min_phase=min_phase)


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def load_herd(schema: int = cycles.SCHEMA, key: str = cycles.DEFAULT_INVENTORY,
              window: int = cycles.HERD_WINDOW_YEARS):
    """The herd view's own loader, keyed the same way as the price one.

    SEPARATE FROM load_summary ON PURPOSE. They read different series, return
    different shapes and are selected by different controls; sharing one cache
    entry would mean changing the price basis silently refetched the inventory.
    """
    conn = None
    if _DB.use_snowflake():
        try:
            conn = _DB.get_conn()
        except Exception:
            conn = None
    try:
        seed = cycles.load(conn)
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
    if not seed:
        return None
    return cycles.herd_summary(seed, key=key, window=window)


st.title("Cattle Cycles")

# One definition each, used by the switch and by the branches below. Spelled
# out twice they drift, and a branch comparing against a string that no longer
# matches simply renders nothing.
VIEW_CTX = "This cycle in context"
VIEW_LONG = "The long record"
VIEW_HERD = "Herd cycle"

view = st.segmented_control(
    "View", [VIEW_CTX, VIEW_LONG, VIEW_HERD],
    default=VIEW_CTX, label_visibility="collapsed",
)

# -- the herd cycle view ------------------------------------------------------
#
# IT RENDERS AND STOPS, above every price control. The two price views share a
# series picker, a basis toggle and a minimum-phase selector, none of which
# mean anything here: this view reads an annual head count, not a deflated
# monthly price. Branching here and calling st.stop() leaves the price path
# below untouched rather than wrapping a thousand lines in an else.
if view == VIEW_HERD:
    h1, h2 = st.columns([2, 1])
    with h1:
        herd_label = st.selectbox(
            "Inventory series", [cycles.INVENTORY[k] for k in cycles.INVENTORY],
            index=list(cycles.INVENTORY).index(cycles.DEFAULT_INVENTORY),
            help="USDA NASS January 1 inventory, national. Beef cows are the "
                 "productive base that makes the next calf crop; all cattle and "
                 "calves is the headline number and carries the consequence of "
                 "breeding decisions already made.",
        )
        herd_key = next(k for k, v in cycles.INVENTORY.items() if v == herd_label)
    with h2:
        herd_window = st.selectbox(
            "Turn window", cycles.HERD_WINDOW_CHOICES,
            index=list(cycles.HERD_WINDOW_CHOICES).index(cycles.HERD_WINDOW_YEARS),
            format_func=lambda y: f"{y} years",
            help="How many years either side a year must beat to count as a peak "
                 "or a trough. Annual data is sparse, so this does the job the "
                 "minimum phase does for price — a control, not a constant.",
        )

    H = load_herd(cycles.SCHEMA, herd_key, herd_window)
    if not H or H["context"] is None:
        st.error("The herd cycle view could not read its inventory data.")
        st.caption("The seed ships with the page; a miss here means the file is "
                   "incomplete rather than the series having stopped.")
        st.stop()

    hc = H["context"]
    h_source = ("the live table" if H.get("source") == "snowflake"
                else "the committed seed, which does not advance on its own")
    st.caption(
        f"USDA NASS January 1 inventory, {H['label'].lower()} · head · "
        f"{H['first']} to {H['last']} · turns dated on a {H['window']}-year "
        f"window · read from {h_source}"
    )

    # THE BANNER IS THE WHOLE HONESTY OF THIS VIEW. A trough at the end of the
    # record is the lowest year SO FAR, never a dated bottom -- the window that
    # found it is truncated. Both series are still falling as of Jan 1 2026, so
    # every figure below describes a liquidation in progress.
    if hc["provisional"]:
        falling = ("and it is still falling" if hc["still_falling"]
                   else "though the latest year did not make a new low")
        st.html(
            f'<div class="cyc-note"><b>This liquidation has not bottomed.</b> '
            f'January {hc["year"]} is the lowest reading so far {falling}, which is '
            f'not the same as a trough: a bottom is only datable once the herd has '
            f'turned away from it for long enough to rule out another leg down. '
            f'Every figure here is therefore <b>so far</b>, and the run in progress '
            f'is excluded from the medians and the ranks below so it is never '
            f'compared against itself.</div>'
        )

    last_y, last_v = hc["recent_yoy"][-1] if hc["recent_yoy"] else (hc["year"], 0.0)
    tiles = [
        tile(f"Decline so far, from the {hc['peak']} peak", f"{hc['drop']:.1%}",
             sub=f"{H['label'].lower()}, Jan {hc['peak']} to Jan {hc['year']}"),
        tile(f"Years since the {hc['peak']} peak", f"{hc['years']} years",
             sub=f"median completed liquidation ran {hc['median_years']:.0f}"),
        tile("Median completed liquidation",
             f"{hc['median_drop']:.1%}" if hc["median_drop"] is not None else "—",
             sub=f"across {hc['n_peers']} of them, peak to trough"),
        tile("Completed liquidations that went deeper",
             f"{hc['deeper']} of {hc['n_peers']}",
             sub=f"the other {hc['n_peers'] - hc['deeper']} stopped short of "
                 f"{abs(hc['drop']):.1%}"),
        tile(f"Head change, Jan {last_y - 1} to Jan {last_y}", f"{last_v:+.2%}",
             sub=f"{hc['head']:,.0f} head on Jan 1 {hc['year']}"),
    ]
    st.html(f'<div class="cyc-tiles">{"".join(tiles)}</div>')

    # -- the overlay ----------------------------------------------------------
    st.subheader("This liquidation against every completed one")
    hfig = go.Figure()
    _hy = [v for r in H["overlay"] for v in r["y"]]
    _hx = [v for r in H["overlay"] for v in r["x"]]
    hoff = label_offsets(H["overlay"], max(_hy) - min(_hy), max(_hx) - min(_hx))
    for run in H["overlay"]:
        live = run["running"]
        hfig.add_trace(go.Scatter(
            x=run["x"], y=run["y"], mode="lines",
            name=run["label"], showlegend=False,
            line=dict(color=JSA_GREEN if live else PAST_LINE,
                      width=3.2 if live else 1.4),
            hovertemplate=f"<b>{run['label']} peak</b><br>year %{{x}} after the peak"
                          f"<br>%{{y:.1f}} vs 100 at the peak<extra></extra>",
        ))
        _ay = hoff[id(run)]
        hfig.add_annotation(
            x=run["x"][-1], y=run["y"][-1],
            text=f"<b>{run['label']}</b>" if live else run["label"],
            xanchor="left", yanchor="middle", ax=8, ay=_ay,
            showarrow=bool(_ay), arrowhead=0, arrowsize=1, arrowwidth=1,
            arrowcolor=JSA_GREEN if live else PAST_LINE,
            xshift=0 if _ay else 4,
            font=dict(size=10 if live else 9,
                      color=JSA_GREEN if live else DM_MUTED),
        )
    hfig.add_hline(y=100, line=dict(color=DM_BORDER, width=1), layer="below")
    hfig.update_layout(
        height=CHART_PX, margin=dict(l=10, r=70, t=10, b=10),
        paper_bgcolor=DM_SURFACE, plot_bgcolor=DM_SURFACE,
        hovermode="closest", showlegend=False,
        xaxis={**AXIS, "title": "years from the peak"},
        yaxis={**AXIS, "title": "head, indexed to 100 at the peak"},
    )
    st.plotly_chart(hfig, use_container_width=True)
    st.caption(
        f"Every completed liquidation since {H['first']} in grey, each indexed to "
        f"100 at its own peak; the one in progress in green. Indexed at the PEAK "
        f"rather than the trough because what is being compared is how far the "
        f"herd fell — the price overlay indexes at the trough for the mirror "
        f"reason, and the two are not the same chart."
    )

    st.subheader("Every liquidation, peak to trough")
    rows = []
    for q in H["liquidations"]:
        live = hc["provisional"] and q["peak"] == hc["peak"]
        rows.append({
            "Peak": f"Jan {q['peak']}",
            "Trough": (f"Jan {q['trough']} (so far)" if live else f"Jan {q['trough']}"),
            "Years": q["years"],
            "Decline": f"{q['drop']:.1%}",
            # GROUPED AS STRINGS, which costs numeric sorting and is worth it
            # here. st.column_config.NumberColumn has no thousands separator
            # that is safe across the Streamlit versions this app runs on, and
            # a head count reading 31640700 is one a reader has to count the
            # digits of. CLAUDE.md rejects TextColumn for a numeric column on
            # the Cattle on Feed page because sorting matters there; this
            # table is six rows, fixed most-recent-first, and nobody sorts it.
            "Peak head": f"{q['from']:,.0f}",
            "Trough head": f"{q['to']:,.0f}",
        })
    st.dataframe(list(reversed(rows)), use_container_width=True, hide_index=True)
    st.caption(
        f"Most recent first. The top row is the liquidation in progress and its "
        f"trough is the lowest year so far, not a dated bottom — it is left out "
        f"of every median and rank above. Declines are not coloured: a shrinking "
        f"herd is bullish for the man selling cattle and bearish for the man "
        f"buying them, and this page does not know which one is reading it."
    )

    st.caption(
        f"The herd cycle is not the price cycle. This view dates peaks and troughs "
        f"in head; the other two date phases in price, and they run roughly inverse "
        f"— cows going to town is liquidation and is price-bullish. US Cow Herd "
        f"answers whether the signals called each turn; this answers how far the "
        f"herd fell."
    )
    st.stop()


c1, c2, c3 = st.columns([2, 1, 1])
with c1:
    series_label = st.selectbox(
        "Price series", [cycles.SERIES[k] for k in cycles.SERIES],
        index=list(cycles.SERIES).index(cycles.DEFAULT_SERIES),
        help="USDA NASS price received, national, monthly. Cows start in 1953; "
             "the other two reach back to 1909.",
    )
    series_key = next(k for k, v in cycles.SERIES.items() if v == series_label)
with c2:
    basis = st.radio("Price basis", ["Real", "Nominal"], horizontal=True,
                     help="Real deflates by CPI-U. Phases are dated on real price "
                          "either way — in nominal dollars the 1970s look like a "
                          "non-event and every cycle looks bigger than the last.")
with c3:
    min_phase = st.selectbox(
        "Shortest phase", cycles.MIN_PHASE_CHOICES,
        index=list(cycles.MIN_PHASE_CHOICES).index(cycles.MIN_PHASE_MONTHS),
        format_func=lambda m: f"{m} months",
        help="The shortest run the dating will call a phase. It changes how many "
             "cycles there are, so it is a control rather than a constant.",
    )

D = load_summary(cycles.SCHEMA, series_key, basis == "Real", min_phase)

if not D or D["context"] is None:
    st.error("Cattle Cycles could not read its data file, so nothing below can be shown.")
    st.caption(
        f"Neither {cycles.TABLE} nor the committed {cycles.DATA.name} under "
        f"apps/cattle_cycles/data/ could be read.")
    st.stop()

ctx = D["context"]
tt = D["trough_to_trough"]
# Defined ONCE, above every use. The provisional banner below renders before
# either view branch, so a per-branch definition would NameError there -- the
# script-order trap CLAUDE.md records for the WASDE panel.
basis_word = "Real" if D["real"] else "Nominal"

# WHICH SOURCE, NAMED ON THE PAGE. The committed seed renders every figure
# here perfectly well — it just stops advancing — so a refresh job that has
# died looks exactly like one that has nothing to do. There is no visual tell
# at all, which is why the caption carries one. Derived from the load, never
# typed, and defined ONCE above its use like basis_word above it.
source_word = ("the live table" if D.get("source") == "snowflake"
               else "the committed seed, which does not advance on its own")
st.caption(
    f"USDA NASS price received, {series_label.lower()} · {D['units']} · "
    f"{D['first']:%b %Y} to {D['last']:%b %Y} · phases dated at a "
    f"{min_phase}-month minimum · read from {source_word}"
)

# -- the provisional turn ----------------------------------------------------
#
# This banner is the single most important thing on the page. A peak is only
# knowable once price has fallen away from it for long enough to rule out a
# pause, so the dating refuses to call one inside six months of the last
# observation. Without saying so, the page would be quietly asserting that the
# run is still going on exactly the months where that is least certain.
if ctx["provisional"]:
    p = ctx["provisional"][0]
    st.html(
        f'<div class="cyc-note"><b>A turn may have happened and cannot be dated yet.</b> '
        f'The highest {basis_word.lower()} price of this run was {p["date"]:%B %Y}, '
        f'and price is '
        f'{abs(ctx["off_best"]):.1%} below it as of {D["last"]:%B %Y}. That is '
        f'consistent with a peak and equally consistent with a pause — a peak is '
        f'only datable once enough months have passed to tell them apart, so it is '
        f'excluded from every figure below.</div>',
    )

if view == VIEW_CTX:
    kind = ctx["kind"]
    alive = ctx["still_running_at_age"]
    tiles = [
        tile("Current run, age", yrs(ctx["age_months"]),
             sub=f"{kind} market in {basis_word.lower()} price, from {ctx['start']:%b %Y}"),
        tile(f"{basis_word} price, {D['last']:%b %Y}", f"${ctx['level']:,.0f}",
             delta=f"{ctx['off_best']:+.1%} vs its {ctx['best_at']:%b %Y} high",
             sub=D["units"]),
        tile(f"Price change over this {kind} run", f"{ctx['change']:+.0%}",
             sub=f"${ctx['start_level']:,.0f} in {ctx['start']:%b %Y} to "
                 f"${ctx['level']:,.0f} now, {basis_word.lower()}"),
        tile(f"Age rank among {kind} runs",
             f"#{ctx['rank_duration']} of {ctx['n_peers'] + 1}",
             sub=f"longest first, {D['first']:%Y} to now"),
        tile(f"Past {kind} runs still going at {ctx['age_months']} months",
             f"{len(alive)} of {ctx['n_peers']}",
             sub=f"the other {ctx['n_peers'] - len(alive)} had already ended by "
                 f"this age"),
    ]
    st.html(f'<div class="cyc-tiles">{"".join(tiles)}</div>')

    # -- the overlay ---------------------------------------------------------
    st.subheader(f"This {kind} run against every completed one")
    fig = go.Figure()
    _ys = [v for r in D["overlay"] for v in r["y"]]
    _xs = [v for r in D["overlay"] for v in r["x"]]
    offsets = label_offsets(D["overlay"], max(_ys) - min(_ys), max(_xs) - min(_xs))
    for run in D["overlay"]:
        if run["running"]:
            continue
        fig.add_trace(go.Scatter(
            x=run["x"], y=run["y"], mode="lines", name=span_label(run),
            line=dict(color=PAST_LINE, width=1.4), showlegend=False,
            hovertemplate=f"<b>{span_label(run)}</b><br>month %{{x}} of that run"
                          f"<br>%{{y:.0f}} vs 100 at its trough<extra></extra>",
        ))
        # EACH LINE CARRIES ITS OWN YEARS, at the end of the line rather than in
        # a legend. Thirteen identical grey swatches in a legend name the runs
        # without identifying any of them -- the colour cannot be matched back
        # to a line. The label sits where the line stops, which is also the
        # fact worth reading: how long that run lasted.
        _ay = offsets[id(run)]
        fig.add_annotation(
            x=run["x"][-1], y=run["y"][-1], text=span_label(run),
            xanchor="left", yanchor="middle", ax=8, ay=_ay,
            showarrow=bool(_ay), arrowhead=0, arrowsize=1, arrowwidth=1,
            arrowcolor=PAST_LINE, xshift=0 if _ay else 4,
            font=dict(size=9, color=DM_MUTED),
        )
    live = next((r for r in D["overlay"] if r["running"]), None)
    if live:
        fig.add_trace(go.Scatter(
            x=live["x"], y=live["y"], mode="lines", name=span_label(live),
            line=dict(color=JSA_GREEN, width=3.2),
            hovertemplate=f"<b>{span_label(live)}</b><br>month %{{x}} of this run"
                          f"<br>%{{y:.0f}} vs 100 at the trough<extra></extra>",
        ))
        _ay = offsets[id(live)]
        fig.add_annotation(
            x=live["x"][-1], y=live["y"][-1], text=f"<b>{span_label(live)}</b>",
            xanchor="left", yanchor="middle", ax=8, ay=_ay,
            showarrow=bool(_ay), arrowhead=0, arrowsize=1, arrowwidth=1,
            arrowcolor=JSA_GREEN, xshift=0 if _ay else 4,
            font=dict(size=10, color=JSA_GREEN),
        )
    fig.add_hline(y=100, line=dict(color=DM_BORDER, width=1), layer="below")
    fig.update_layout(
        # CLOSEST, NOT "x unified", AND THIS CHART IS THE EXCEPTION. Everywhere
        # else on the portal a shared x is the comparison. Here fourteen runs
        # share an x origin that means a different decade for each, so a unified
        # box stacks fourteen numbers and names none of them readably. Closest
        # lets one line answer at a time, which is the question being asked.
        height=CHART_PX, margin=dict(l=10, r=70, t=10, b=10),
        paper_bgcolor=DM_SURFACE, plot_bgcolor=DM_SURFACE,
        hovermode="closest", showlegend=False,
        xaxis={**AXIS, "title": "months from the start of the run"},
        yaxis={**AXIS, "title": "indexed to 100 at the trough"},
    )
    st.plotly_chart(fig, use_container_width=True)
    st.caption(money_md(
        f"Every completed {kind} run since {D['first']:%Y} in grey, each indexed to "
        f"100 at its own trough; this one in green. "
        # WHAT 100 MEANS, asked by Ross looking at the chart. The axis title
        # says "indexed to 100 at the trough" and that still leaves the
        # question, because the obvious reading of a chart like this is price.
        # Each line's 100 is a DIFFERENT dollar figure -- $84 for the 1933 run
        # against $210 for the 1945 one -- so height is proportional gain and
        # two lines level with each other are nowhere near the same price.
        # That is the cost of indexing and it is not self-evident from the
        # picture, so it is stated rather than left to be inferred.
        f"Each line's 100 is its own trough price, this one's being "
        f"${ctx['start_level']:,.0f}, so a line's height is how far that run "
        f"has come in percent rather than how dear it is: two lines level "
        f"with each other are up by the same proportion from different "
        f"prices. Indexed rather than priced "
        # THE LOW, NOT THE FIRST VALUE. The claim is that the series spans too
        # wide a range to share a price axis, so it needs the widest gap in it.
        # De-hardcoding an earlier "$80" to series.iloc[0] quietly swapped the
        # 1933 low for January 1913, and the sentence then argued for indexing
        # off a $196-to-$232 spread, which argues for the opposite.
        f"because {D['series'].idxmin():%Y} traded near "
        f"${D['series'].min():,.0f} and today near ${ctx['level']:,.0f} in the "
        f"same dollars — on a shared price axis the shape would be invisible."
    ))

    # -- what happened from here --------------------------------------------
    st.subheader(f"What happened from month {ctx['age_months']} in the runs that got this far")
    if not alive:
        st.html(
            f'<div class="cyc-note">No completed {kind} run on record reached '
            f'{ctx["age_months"]} months. This one is already longer than every '
            f'one of the {ctx["n_peers"]} before it, so there is no precedent to '
            f'read a remaining duration off — which is itself the finding.</div>',
        )
    else:
        rows = "".join(
            f"<li><b>{a['label']}</b> ran {a['months']} months in all — past this "
            f"age it added <b>{a['extra_months']} more months</b> and "
            f"<b>{a['extra_change']:+.0%}</b>.</li>" for a in alive
        )
        st.html(
            f'<div class="cyc-note"><b>{len(alive)} of {ctx["n_peers"]}</b> past '
            f'{kind} runs were still going at {ctx["age_months"]} months.'
            f'<ul style="margin:8px 0 0 0;">{rows}</ul>'
            f'<div style="margin-top:9px;">That is a sample of {len(alive)}, not a '
            f'distribution. It says what the one comparable run did next; it does '
            f'not say what this one will do, and no median fitted to it would mean '
            f'anything.</div></div>',
        )

    med_t = int(np.median(tt)) if tt else None
    if med_t:
        st.caption(
            f"For reference, the median completed cycle on this series is "
            f"{med_t / 12:.1f} years trough to trough across {len(tt)} of them, "
            f"ranging {min(tt) / 12:.1f} to {max(tt) / 12:.1f}. The received "
            f"ten-year figure describes the January 1 herd inventory, which turns "
            f"on a slower clock than price does."
        )

else:
    # -- the long record -----------------------------------------------------
    #
    # EVERY BASIS WORD ON THIS PAGE IS DERIVED, NEVER TYPED. Written out, the
    # headings and captions said "real" while the Nominal toggle was selected
    # -- a label contradicting the figure directly under it, which is the one
    # thing the standing headline rule forbids. One variable, used everywhere.
    s = D["series"]
    st.subheader(f"{basis_word} cattle price and its phases, "
                 f"{D['first']:%Y} to {D['last']:%Y}")
    fig = go.Figure()
    for p in D["phases"]:
        fig.add_vrect(x0=p["start"], x1=p["end"], layer="below", line_width=0,
                      fillcolor=BULL_BAND if p["phase"] == "bull" else BEAR_BAND)
    # THE RUNNING PHASE IS BANDED TOO, AND DIFFERENTLY. It is not a completed
    # phase and never enters a median, but leaving it blank made the last six
    # years read as a series that had stopped rather than one still going —
    # which is the opposite of what the page is about. Dashed edges and a
    # lighter fill say "open" where a solid band says "measured".
    fig.add_vrect(
        x0=ctx["start"], x1=s.index[-1], layer="below",
        fillcolor=BULL_BAND if ctx["kind"] == "bull" else BEAR_BAND,
        opacity=0.55, line=dict(color=JSA_GREEN_LT, width=1, dash="dot"),
    )
    fig.add_trace(go.Scatter(
        x=list(s.index), y=list(s.values), mode="lines", name="price",
        line=dict(color=JSA_GREEN, width=1.6),
        hovertemplate="%{x|%b %Y}<br>$%{y:.0f}/cwt<extra></extra>",
    ))
    fig.update_layout(
        height=430, margin=dict(l=10, r=10, t=10, b=10),
        paper_bgcolor=DM_SURFACE, plot_bgcolor=DM_SURFACE,
        hovermode="x unified", showlegend=False,
        xaxis={**AXIS}, yaxis={**AXIS, "title": D["units"]},
    )
    st.plotly_chart(fig, use_container_width=True)
    # The closing clause belongs to the real view alone: on the nominal view the
    # high is a recent month and "the comparison nominal dollars cannot show"
    # would be printed over exactly the dollars that cannot show it.
    tail = (" — the comparison nominal dollars cannot show" if D["real"] else
            ", which in nominal dollars says little: every rising series sets "
            "its record near the end")
    st.caption(money_md(
        f"Green bands are rising-price phases, grey falling; the dotted band at "
        f"the right is the run still going, which is shown but never counted. "
        f"The {basis_word.lower()} high is ${s.max():,.0f} in {s.idxmax():%B %Y}; "
        f"today is {s.iloc[-1] / s.max() - 1:.0%} against it{tail}."
    ))

    pp = D["peak_to_peak"]
    bulls = [p for p in D["phases"] if p["phase"] == "bull"]
    bears = [p for p in D["phases"] if p["phase"] == "bear"]
    stat = [
        tile("Completed cycles", f"{len(tt)}",
             sub=f"trough to trough, {D['first']:%Y} to {D['last']:%Y}"),
        tile("Median cycle, trough to trough",
             f"{np.median(tt) / 12:.1f} years" if tt else "—",
             sub=f"range {min(tt) / 12:.1f} to {max(tt) / 12:.1f} years" if tt else ""),
        tile("Median cycle, peak to peak",
             f"{np.median(pp) / 12:.1f} years" if pp else "—",
             sub=f"range {min(pp) / 12:.1f} to {max(pp) / 12:.1f} years" if pp else ""),
        tile("Median rising phase",
             f"{np.median([p['months'] for p in bulls]) / 12:.1f} years" if bulls else "—",
             sub=f"median move {np.median([p['change'] for p in bulls]):+.0%} {basis_word.lower()}" if bulls else ""),
        tile("Median falling phase",
             f"{np.median([p['months'] for p in bears]) / 12:.1f} years" if bears else "—",
             sub=f"median move {np.median([p['change'] for p in bears]):+.0%} {basis_word.lower()}" if bears else ""),
    ]
    st.html(f'<div class="cyc-tiles">{"".join(stat)}</div>')

    st.html(
        f'<div class="cyc-note"><b>The cycle count is a choice, not a reading.</b> '
        f'These figures are dated at a {min_phase}-month minimum phase. Shortening '
        f'it finds more and briefer cycles, lengthening it absorbs genuine breaks into '
        f'the runs either side of them — at an 18-month minimum the 1990 peak and '
        f'the 1991 trough disappear and a 22-month break becomes part of a rally. '
        f'The control is above the chart because a single median presented as fact '
        f'would be hiding the setting that produced it.</div>',
    )

    st.subheader("Every dated phase")
    tbl = [{
        "Phase": p["phase"].title(),
        "From": f"{p['start']:%b %Y}", "To": f"{p['end']:%b %Y}",
        "Years": round(p["months"] / 12, 1),
        "Change": f"{p['change']:+.0%}",
        "Start $": round(p["from"]), "End $": round(p["to"]),
    } for p in reversed(D["phases"])]
    st.dataframe(tbl, use_container_width=True, hide_index=True)
    st.caption(
        f"Most recent first. Change is {basis_word.lower()} and is signed in both "
        "directions — a "
        "rising cattle price suits the seller and not the buyer, and this page "
        "does not know which one is reading it, so nothing here is coloured."
    )
