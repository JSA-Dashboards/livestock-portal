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
    {"title": "Beef Weight", "page": "apps/beef_weight/app.py", "url_path": "beef-weight",
     "desc": "USDA NASS weekly beef slaughter weights by class, dressed & live."},
    {"title": "Beef Cutout", "page": "apps/beef_cutout/app.py", "url_path": "beef-cutout",
     "desc": "Daily USDA boxed beef cutout — Choice & Select composites, spread, volume."},
    {"title": "Livestock Inventory", "page": "apps/livestock_inventory/app.py", "url_path": "livestock-inventory",
     "desc": "USDA NASS livestock, poultry, aquaculture inventory & dairy production."},
    {"title": "CME Feeder Cattle Index", "page": "apps/cme_feeder_cattle/app.py", "url_path": "cme-feeder-cattle-index",
     "desc": "12-state feeder steer index trend, weekly rundown, and basis by sale location."},
]

_TILE_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=EB+Garamond:wght@500;600&display=swap');

div[class*="st-key-tile_"] {
    background: #32373c;
    border-radius: 4px;
    box-shadow: 0 6px 0 #ffffff, 0 6px 14px rgba(0,0,0,0.18);
    transition: transform 0.15s ease, box-shadow 0.15s ease;
    margin-bottom: 28px;
}
div[class*="st-key-tile_"]:hover {
    transform: translateY(-3px);
    box-shadow: 0 6px 0 #ffffff, 0 10px 20px rgba(0,0,0,0.25);
}
div[class*="st-key-tile_"] a[data-testid="stPageLink-NavLink"] {
    display: flex; flex-direction: column; align-items: center; justify-content: center;
    height: 140px; padding: 14px 18px; text-decoration: none !important;
    text-align: center;
}
div[class*="st-key-tile_"] a[data-testid="stPageLink-NavLink"] p {
    color: #ffffff !important;
    font-family: 'EB Garamond', Georgia, serif !important;
    font-size: 21px !important;
    font-weight: 600 !important;
    line-height: 1.3 !important;
    margin: 0 !important;
}
div[class*="st-key-tile_"] a[data-testid="stPageLink-NavLink"]:hover p {
    color: #cfe8fb !important;
}
.jsa-tile-desc {
    color: #a8b3ad; font-family: 'Source Sans Pro', system-ui, sans-serif;
    font-size: 12px; margin-top: 6px; line-height: 1.4;
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
    cols = st.columns(4)
    for i, d in enumerate(DASHBOARDS):
        with cols[i]:
            with st.container(key=f"tile_{i}"):
                st.page_link(d["page"], label=d["title"])
                st.markdown(f"<div class='jsa-tile-desc'>{d['desc']}</div>", unsafe_allow_html=True)


home_page = st.Page(render_home, title="Home", url_path="home", default=True)

pg = st.navigation(
    [home_page] + [
        st.Page(d["page"], title=d["title"], url_path=d["url_path"])
        for d in DASHBOARDS
    ],
    position="top",
)
pg.run()
