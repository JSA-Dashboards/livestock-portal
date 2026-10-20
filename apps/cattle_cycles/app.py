"""
Cattle Cycles — where this run sits against every one since 1913.

STAFF ONLY, AND UNLISTED. `portal_auth.require_admin()` is the first thing that
runs, and `Home.py` registers this under `TOOLS` rather than `DASHBOARDS`, the
same treatment the letter tool and the Market Board get: no home-grid tile, no
nav entry, no route at all for a client. Signing in reveals all three together.

IT NEEDS NO SECRET AND NO DATABASE. Everything is computed from the committed
seed in `data/cattle_cycles.json` — USDA NASS monthly price received plus BLS
CPI-U, both keyless, both stored as published. So there is no Snowflake block
to forward here and no outage anywhere that can blank this page. The cost is
that the series advances only when the seed is regenerated, which is why the
as-of month is printed at the top rather than left to be inferred.

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


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def load_summary(schema: int = cycles.SCHEMA, key: str = cycles.DEFAULT_SERIES,
                 real: bool = True, min_phase: int = cycles.MIN_PHASE_MONTHS):
    """Dating is cheap but not free, and the result is a pure function of these four.

    `schema` is in the signature AND passed at the call site. A default alone is
    not part of the cache key — st.cache_data hashes the arguments it is CALLED
    with — and a leading underscore would ask Streamlit to drop it outright.
    Both halves, or the guard is inert.
    """
    seed = cycles.load()
    if not seed:
        return None
    return cycles.summary(seed, key=key, real=real, min_phase=min_phase)


st.title("Cattle Cycles")

view = st.segmented_control(
    "View", ["This cycle in context", "The long record"],
    default="This cycle in context", label_visibility="collapsed",
)

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
    st.caption(f"Expected {cycles.DATA.name} under apps/cattle_cycles/data/.")
    st.stop()

ctx = D["context"]
tt = D["trough_to_trough"]
# Defined ONCE, above every use. The provisional banner below renders before
# either view branch, so a per-branch definition would NameError there -- the
# script-order trap CLAUDE.md records for the WASDE panel.
basis_word = "Real" if D["real"] else "Nominal"
st.caption(
    f"USDA NASS price received, {series_label.lower()} · {D['units']} · "
    f"{D['first']:%b %Y} to {D['last']:%b %Y} · phases dated at a "
    f"{min_phase}-month minimum"
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

if view == "This cycle in context":
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
    for run in D["overlay"]:
        if run["running"]:
            continue
        fig.add_trace(go.Scatter(
            x=run["x"], y=run["y"], mode="lines", name=run["label"],
            line=dict(color=PAST_LINE, width=1.4), showlegend=False,
            # 13 traces sharing an x under "x unified" is a wall of numbers
            # nobody reads. The past runs are shape; the running one is the
            # figure, and it is the only trace that answers on hover.
            hoverinfo="skip",
        ))
    live = next((r for r in D["overlay"] if r["running"]), None)
    if live:
        fig.add_trace(go.Scatter(
            x=live["x"], y=live["y"], mode="lines", name="This run",
            line=dict(color=JSA_GREEN, width=3.2),
            hovertemplate="month %{x} of this run<br>%{y:.0f} vs 100 at the trough"
                          "<extra></extra>",
        ))
    fig.add_hline(y=100, line=dict(color=DM_BORDER, width=1), layer="below")
    fig.update_layout(
        height=430, margin=dict(l=10, r=10, t=10, b=10),
        paper_bgcolor=DM_SURFACE, plot_bgcolor=DM_SURFACE,
        hovermode="x unified", showlegend=False,
        xaxis={**AXIS, "title": "months from the start of the run"},
        yaxis={**AXIS, "title": "indexed to 100 at the trough"},
    )
    st.plotly_chart(fig, use_container_width=True)
    st.caption(money_md(
        f"Every completed {kind} run since {D['first']:%Y} in grey, each indexed to "
        f"100 at its own trough; this one in green. Indexed rather than priced "
        f"because {D['first']:%Y} traded near ${D['series'].iloc[0]:,.0f} and today "
        f"near ${ctx['level']:,.0f} in the same dollars — on a shared price axis "
        f"the shape would be invisible."
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
