"""
JSA Livestock Portal — shared shell combining fourteen livestock dashboards
(CME Feeder Cattle Index, Seasonal Futures & Spreads, Commitment of Traders,
Cattle on Feed, US Cow Herd, Mexican Feeder Imports, Cattle Weights, Beef
Cutout, Beef Trimmings, Livestock Inventory, Cash Cattle Trade, Fed Cattle
Crush, Backgrounding Crush, US Beef Trade) into one app with top-navigation
tabs.

Makes the single set_page_config call allowed per multi-page run, then
hands off to st.navigation (top nav, no sidebar, no login gate — matches
how each of these ran standalone).

A shared-passphrase gate is written and ready in portal_auth.py but is NOT
wired in — deferred 2026-09-22. To enable it, set PORTAL_PASSPHRASE in the
app's secrets FIRST, then call portal_auth.require_passphrase() immediately
after set_page_config below. It fails closed, so wiring it without the secret
in place takes all fourteen dashboards down.
"""
from pathlib import Path

import streamlit as st

import portal_auth

HERE = Path(__file__).parent


def _asset(name: str) -> str:
    return str(HERE / "assets" / name)


st.set_page_config(
    page_title="JSA Livestock Portal",
    page_icon=_asset("jsa_favicon.png"),
    layout="wide",
)

# Hide Streamlit's own chrome WITHOUT hiding the portal's top navigation.
#
# THE NAV LIVES INSIDE THE TOOLBAR, which is not obvious and has now cost two
# wrong fixes in one day. The real tree on Streamlit 1.64, read out of the
# running app:
#
#   header[data-testid="stHeader"]
#     └── div[data-testid="stToolbar"]
#           ├── div …  → a[data-testid="stTopNavLink"]  ← OUR PAGE TABS
#           │            button[data-testid="stTopNavSection"] ("3 more")
#           ├── div[data-testid="stToolbarActions"]     ← Share + Cloud icons
#           └── span[data-testid="stMainMenu"]          ← hamburger
#
# So `header {visibility:hidden}` (added 2026-10-02) hid the tabs, and so did
# `[data-testid="stToolbar"] {visibility:hidden}`, which was the first attempt
# at fixing it. Both are one level too high. Only the last two children may be
# hidden; the toolbar and the header must stay visible or the nav goes with
# them.
#
# Checked by walking the DOM in the deployed app rather than locally: local
# Streamlit is 1.63 and renders st.navigation in the SIDEBAR, so none of this
# structure exists there and a local check would show nothing wrong.
st.markdown("""<style>
#MainMenu {visibility: hidden;}
footer {visibility: hidden;}
[data-testid="stToolbarActions"] {display: none;}
[data-testid="stMainMenu"] {display: none;}
[data-testid="stDecoration"] {display: none;}
</style>""", unsafe_allow_html=True)

# Hide the Streamlit Community Cloud viewer badge (the profile avatar that links
# to the creator's other apps) for a clean, client-facing footer.
# The Streamlit Cloud badge (creator avatar + logo) is drawn by Cloud's outer page,
# outside this iframe, so CSS here can't reach it; add the rule to the parent
# document instead (same-origin). No-op when run locally.
_BADGE_JS = """<script>(function(){try{var w=window;while(w.parent&&w.parent!==w){try{void w.parent.document;w=w.parent;}catch(e){break;}}var d=w.document;if(d.getElementById('jsa-hide-cloud-badge'))return;var s=d.createElement('style');s.id='jsa-hide-cloud-badge';s.textContent="[class*='_profileContainer_'],[class*='_viewerBadge_']{display:none !important;}";d.head.appendChild(s);}catch(e){}})();</script>"""
try:
    st.html(_BADGE_JS, unsafe_allow_javascript=True)
except TypeError:  # older Streamlit without st.html JS support
    import streamlit.components.v1 as _stc
    _stc.html(_BADGE_JS, height=0)

DASHBOARDS = [
    {"title": "CME Feeder Cattle Index", "page": "apps/cme_feeder_cattle/app.py", "url_path": "cme-feeder-cattle-index",
     "desc": "12-state feeder steer index trend, weekly rundown, and basis by sale location."},
    {"title": "Seasonal Futures & Spreads", "page": "apps/livestock_seasonal/app.py", "url_path": "seasonal-futures-spreads",
     "desc": "CME Live Cattle, Feeder Cattle, and Lean Hogs seasonal futures, spreads, and spread matrix."},
    # Beside Seasonal rather than at the end of the list: the two futures-market
    # pages belong together, and the grid is 4/4/4/2 at fourteen either way.
    {"title": "Commitment of Traders", "page": "apps/cot_report/app.py", "url_path": "commitment-of-traders",
     "desc": "Managed money net futures position in Live Cattle and Feeder Cattle — CFTC's weekly Disaggregated report, with twenty years of context."},
    {"title": "Cash Cattle Trade", "page": "apps/cash_trade/app.py", "url_path": "cash-trade",
     "desc": "Combined Steer/Heifer FOB & Dressed prices, plus national negotiated cash trade volume."},
    {"title": "Beef Cutout", "page": "apps/beef_cutout/app.py", "url_path": "beef-cutout",
     "desc": "Daily USDA boxed beef cutout — Choice & Select composites, spread, volume."},
    {"title": "Mexican Feeder Imports", "page": "apps/mexican_feeder_imports/app.py", "url_path": "mexican-feeder-imports",
     "desc": "Border status, crossing activity by port, and Mexican feeder head counts from Census trade data."},
    {"title": "Beef Trimmings", "page": "apps/beef_trimmings/app.py", "url_path": "beef-trimmings",
     "desc": "US Fresh 90s vs. South America & Australia/NZ Frozen 90s (Cow Meat) import prices."},
    {"title": "US Beef Trade", "page": "apps/beef_trade/app.py", "url_path": "beef-trade",
     "desc": "Monthly beef exports and imports on the carcass-weight basis, each against the USDA WASDE forecast."},
    {"title": "Cattle Weights", "page": "apps/beef_weight/app.py", "url_path": "beef-weight",
     "desc": "USDA NASS weekly cattle slaughter weights by class, dressed & live."},
    {"title": "US Cow Herd", "page": "apps/us_cow_herd/app.py", "url_path": "us-cow-herd",
     "desc": "Herd expansion vs liquidation — bred female values, the retention incentive, and replacement receipts."},
    {"title": "Cattle on Feed", "page": "apps/cattle_on_feed/app.py", "url_path": "cattle-on-feed",
     "desc": "USDA on-feed inventory, placements, marketings, the quarterly heifers-on-feed share — and Cold Storage stocks back to 1917."},
    {"title": "Livestock Inventory", "page": "apps/livestock_inventory/app.py", "url_path": "livestock-inventory",
     "desc": "USDA NASS livestock, poultry, aquaculture inventory & dairy production."},
    {"title": "Fed Cattle Crush", "page": "apps/fed_cattle_crush/app.py", "url_path": "fed-cattle-crush",
     "desc": "Feeding margin calculator — prices your cattle off the futures curve, then every number is yours to change."},
    {"title": "Backgrounding Crush", "page": "apps/backgrounding_crush/app.py", "url_path": "backgrounding-crush",
     "desc": "Buy calves, sell feeders — value of gain against cost of gain, cash calf market vs the feeder board."},
]

# Kept OUT of DASHBOARDS on purpose. It is an authoring tool rather than a
# dashboard, and it gets its own section above the grid instead.
#
# The second reason given here until 2026-10-07 was a LAYOUT one -- that a
# thirteenth tile would give the grid 4/4/4/1 and strand one. US Beef Trade
# made that thirteenth tile real, and the grid now rebalances its last row
# rather than depending on the count (see TILES_PER_ROW below), so the layout
# argument no longer holds and only the first reason does. It is noted rather
# than deleted because it was load-bearing for two weeks and someone reading
# the TILES_PER_ROW comment will wonder which of the two moved.
# UNLISTED, NOT JUST LOCKED. The page is passphrase-gated, which stops a client
# getting IN -- but a registered page still shows a tile on the home grid and an
# entry in the top nav, and clients should not see that the letter tool exists
# at all.
#
# So it is registered only when asked for: open the portal with ?tools=1 once,
# and the tile and nav entry appear for that browser session. Without the
# parameter the page is not registered, so there is no tile, no nav entry, and
# /weekly-cattle-reports does not route.
#
# The parameter is UNLISTING, not security -- anyone who guessed it would still
# face the passphrase, which is the actual control. Two different jobs.
TOOLS_PARAM = "tools"
TOOLS_SESSION_KEY = "_tools_visible"

TOOLS = [
    {"title": "JSA Daily Cattle Reports", "page": "apps/weekly_reports/app.py",
     # url_path deliberately unchanged by the rename, the way Cattle Weights
     # kept "beef-weight" -- any bookmark already handed out keeps working.
     "url_path": "weekly-cattle-reports",
     "desc": "Build the daily client letter from live data. Friday is the week-in-review format. Passphrase required."},
    # ITS OWN PAGE, NOT A TAB ON THE LETTER. A hidden Streamlit tab still
    # EXECUTES, so as a third tab there its seven fetches would run on every
    # keystroke in the letter's commentary boxes and add their cold cost to the
    # page Ross opens under deadline each morning. Separate pages also mean an
    # exception in one cannot blank the other.
    {"title": "Cattle Market Board", "page": "apps/market_board/app.py",
     "url_path": "cattle-market-board",
     "desc": "Every dashboard's headline on one page: what is moving the cattle "
             "market, what it means, and how far back the evidence actually "
             "goes. Passphrase required."},
]

_TILE_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=EB+Garamond:wght@500;600&display=swap');

/* The tile IS the dark box. Padding lives here and overflow is clipped to the
   rounded corners, so both the title link and the description sit inside it.
   Previously the description was a sibling of a fixed height:140px link, which
   put it below the painted area and made it read as floating outside the box. */
div[class*="st-key-tile_"] {
    background: #32373c;
    border-radius: 6px;
    overflow: hidden;
    padding: 16px 18px 18px;
    min-height: 132px;
    box-shadow: 0 2px 10px rgba(0,0,0,0.16);
    transition: transform 0.15s ease, box-shadow 0.15s ease;
    margin-bottom: 22px;
}
div[class*="st-key-tile_"]:hover {
    transform: translateY(-3px);
    box-shadow: 0 8px 18px rgba(0,0,0,0.26);
}
/* Let content set the height instead of a fixed 140px, and drop the centring:
   a wrapped two-line title reads ragged when centred in a narrow tile. */
div[class*="st-key-tile_"] a[data-testid="stPageLink-NavLink"] {
    display: block;
    padding: 0 !important;
    margin: 0 !important;
    text-align: left;
    text-decoration: none !important;
    background: transparent !important;
}
div[class*="st-key-tile_"] a[data-testid="stPageLink-NavLink"] p {
    color: #ffffff !important;
    font-family: 'EB Garamond', Georgia, serif !important;
    font-size: 18px !important;
    font-weight: 600 !important;
    line-height: 1.22 !important;
    letter-spacing: 0.1px !important;
    margin: 0 !important;
    /* Long titles wrap rather than spilling past the tile edge. */
    overflow-wrap: anywhere;
    hyphens: none;
}
div[class*="st-key-tile_"] a[data-testid="stPageLink-NavLink"]:hover p {
    color: #cfe8fb !important;
}
.jsa-tile-desc {
    color: #a8b3ad;
    font-family: 'Source Sans Pro', system-ui, -apple-system, sans-serif;
    font-size: 12px;
    line-height: 1.45;
    margin-top: 9px;
}
</style>
"""


def tools_visible() -> bool:
    """
    Admin sees the tools; clients do not.

    ONE QUESTION, ASKED IN ONE PLACE -- portal_auth.is_admin(). ?tools=1 is kept
    as a way in for a session that has not signed in yet, so a bookmark still
    works, but signing in is the real route and the only one that opens the page
    itself.
    """
    if portal_auth.is_admin() or st.session_state.get(TOOLS_SESSION_KEY):
        return True
    try:
        asked = st.query_params.get(TOOLS_PARAM)
    except Exception:
        asked = None
    if str(asked or "").strip().lower() in ("1", "true", "yes", "on"):
        st.session_state[TOOLS_SESSION_KEY] = True
        return True
    return False


def render_home():
    st.markdown(_TILE_CSS, unsafe_allow_html=True)
    col_logo, col_title = st.columns([1, 6])
    with col_logo:
        st.image(_asset("logo-full.png"), width=140)
    with col_title:
        st.markdown(
            "<div style='padding-top:14px'>"
            "<h2 style='margin:0;color:#32373c;font-family:\"EB Garamond\",Georgia,serif'>"
            "Livestock Portal</h2>"
            "<div style='color:#64748b'>John Stewart &amp; Associates · pick a dashboard</div>"
            "</div>",
            unsafe_allow_html=True,
        )

    st.write("")

    # Tools sit above the dashboards, in their own row, reusing the same tile
    # styling. Asking for TILES_PER_ROW columns and filling only the first keeps
    # this tile the same width as every tile below it -- a lone st.columns(1)
    # tile would stretch the full page and stop matching.
    if TOOLS and tools_visible():
        tool_cols = st.columns(4)
        for offset, t in enumerate(TOOLS):
            with tool_cols[offset]:
                with st.container(key=f"tile_tool_{offset}"):
                    st.page_link(t["page"], label=t["title"])
                    st.markdown(f"<div class='jsa-tile-desc'>{t['desc']}</div>",
                                unsafe_allow_html=True)
        st.write("")

    # Four per row, not one column per dashboard. st.columns(len(DASHBOARDS))
    # gave eight ~170px columns, too narrow for an 18px serif title -- which is
    # why "CME Feeder Cattle Index" was spilling past its own tile edge. Always
    # ask for TILES_PER_ROW columns even on a short final row, or the leftover
    # tiles stretch to fill and stop matching the rows above.
    #
    # Keep the last row from holding a SINGLE tile -- that reads as a mistake
    # rather than a layout. This is why the number has moved as dashboards were
    # added: 4 at eight, 3 at nine (3/3/3), and back to 4 at ten, since three
    # would give 3/3/3/1 and strand one tile. Four gives 4/4/2 now, 4/4/3 at
    # eleven and 4/4/4 at twelve, so it does not need revisiting each time.
    # Five would divide ten evenly but puts the tiles back near the ~170px
    # width that made "CME Feeder Cattle Index" spill past its own edge.
    #
    # THIRTEEN IS THE COUNT NO SINGLE NUMBER SOLVES, which is why the rule
    # above stopped being enough on 2026-10-07. The remainder is 1 at two,
    # three, four and six per row, so every one of them strands a tile; only
    # five (5/5/3) and seven divide it acceptably, and five is the width the
    # comment above rejected on measurement. Rather than pick between a
    # stranded tile and a narrow one, the LAST ROW BORROWS: when the final row
    # would hold a single tile, one moves down from the row before it, giving
    # 4/4/3/2 here. Tiles keep their four-column width -- a row of three or
    # two still asks for TILES_PER_ROW columns and fills the first few, the
    # same trick the TOOLS row above uses -- and no row is ever left alone.
    _render_grid = True
    TILES_PER_ROW = 4
    _rows = [DASHBOARDS[i:i + TILES_PER_ROW]
             for i in range(0, len(DASHBOARDS), TILES_PER_ROW)]
    if len(_rows) > 1 and len(_rows[-1]) == 1:
        _rows[-1].insert(0, _rows[-2].pop())
    _n = 0
    for row in _rows:
        cols = st.columns(TILES_PER_ROW)
        for offset, d in enumerate(row):
            with cols[offset]:
                with st.container(key=f"tile_{_n}"):
                    st.page_link(d["page"], label=d["title"])
                    st.markdown(f"<div class='jsa-tile-desc'>{d['desc']}</div>",
                                unsafe_allow_html=True)
            _n += 1

    # Discreet, and deliberately uninformative: a client who sees "Staff
    # sign-in" learns that staff exist, not that a letter tool does.
    st.write("")
    portal_auth.admin_sign_in()


home_page = st.Page(render_home, title="Home", url_path="home", default=True)

# TOOLS are registered only when asked for -- see the note above TOOLS. An
# unregistered page has no nav entry and its url_path does not route.
_pages = list(DASHBOARDS) + (list(TOOLS) if tools_visible() else [])

pg = st.navigation(
    [home_page] + [
        st.Page(d["page"], title=d["title"], url_path=d["url_path"])
        for d in _pages
    ],
    position="top",
)
pg.run()
