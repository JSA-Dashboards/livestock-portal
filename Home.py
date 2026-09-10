"""
JSA Livestock Portal — shared shell combining four livestock dashboards
(Beef Weight, Beef Cutout, Livestock Inventory, CME Feeder Cattle Index)
into one app with top-navigation tabs.

Makes the single set_page_config call allowed per multi-page run, then
hands off to st.navigation (top nav, no sidebar, no login gate — matches
how each of these ran standalone).
"""
from pathlib import Path

import streamlit as st

HERE = Path(__file__).parent


def _asset(name: str) -> str:
    return str(HERE / "assets" / name)


st.set_page_config(
    page_title="JSA Livestock Portal",
    page_icon=_asset("jsa_favicon.png"),
    layout="wide",
)

DASHBOARDS = [
    {"title": "CME Feeder Cattle Index", "page": "apps/cme_feeder_cattle/app.py", "url_path": "cme-feeder-cattle-index",
     "desc": "12-state feeder steer index trend, weekly rundown, and basis by sale location."},
    {"title": "Seasonal Futures & Spreads", "page": "apps/livestock_seasonal/app.py", "url_path": "seasonal-futures-spreads",
     "desc": "CME Live Cattle, Feeder Cattle, and Lean Hogs seasonal futures, spreads, and spread matrix."},
    {"title": "Cattle on Feed", "page": "apps/cattle_on_feed/app.py", "url_path": "cattle-on-feed",
     "desc": "USDA on-feed inventory, placements, marketings, and the quarterly heifers-on-feed share."},
    {"title": "US Cow Herd", "page": "apps/us_cow_herd/app.py", "url_path": "us-cow-herd",
     "desc": "Herd expansion vs liquidation — bred female values, the retention incentive, and replacement receipts."},
    {"title": "Beef Weight", "page": "apps/beef_weight/app.py", "url_path": "beef-weight",
     "desc": "USDA NASS weekly beef slaughter weights by class, dressed & live."},
    {"title": "Beef Cutout", "page": "apps/beef_cutout/app.py", "url_path": "beef-cutout",
     "desc": "Daily USDA boxed beef cutout — Choice & Select composites, spread, volume."},
    {"title": "Beef Trimmings", "page": "apps/beef_trimmings/app.py", "url_path": "beef-trimmings",
     "desc": "US Fresh 90s vs. South America & Australia/NZ Frozen 90s (Cow Meat) import prices."},
    {"title": "Livestock Inventory", "page": "apps/livestock_inventory/app.py", "url_path": "livestock-inventory",
     "desc": "USDA NASS livestock, poultry, aquaculture inventory & dairy production."},
    {"title": "Cash Cattle Trade", "page": "apps/cash_trade/app.py", "url_path": "cash-trade",
     "desc": "Combined Steer/Heifer FOB & Dressed prices, plus national negotiated cash trade volume."},
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
    # Four per row, not one column per dashboard. st.columns(len(DASHBOARDS))
    # gave eight ~170px columns, too narrow for an 18px serif title -- which is
    # why "CME Feeder Cattle Index" was spilling past its own tile edge. Always
    # ask for TILES_PER_ROW columns even on a short final row, or the leftover
    # tiles stretch to fill and stop matching the rows above.
    #
    # Nine dashboards divide evenly by three. Four would leave a single tile
    # alone on a third row, which reads as a mistake rather than a layout.
    TILES_PER_ROW = 3
    for start in range(0, len(DASHBOARDS), TILES_PER_ROW):
        cols = st.columns(TILES_PER_ROW)
        for offset, d in enumerate(DASHBOARDS[start:start + TILES_PER_ROW]):
            with cols[offset]:
                with st.container(key=f"tile_{start + offset}"):
                    st.page_link(d["page"], label=d["title"])
                    st.markdown(f"<div class='jsa-tile-desc'>{d['desc']}</div>",
                                unsafe_allow_html=True)


home_page = st.Page(render_home, title="Home", url_path="home", default=True)

pg = st.navigation(
    [home_page] + [
        st.Page(d["page"], title=d["title"], url_path=d["url_path"])
        for d in DASHBOARDS
    ],
    position="top",
)
pg.run()
