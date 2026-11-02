"""The Risk Analyzer tile — the one entry on the home grid that is not a page
of this app.

It links out to JSA-Dashboards/jsa-risk-analyzer, a separate Streamlit
deployment, so it carries `url` where every other entry carries `page`. That
key is load-bearing in two directions and both are pinned here.
"""
import ast
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
HOME = ROOT / "Home.py"


def _dashboards():
    """DASHBOARDS lifted off the AST. Importing Home.py executes Streamlit
    calls and st.navigation, so it is read rather than imported — the same
    approach tests/streamlit_source.py takes for the pages."""
    tree = ast.parse(HOME.read_text(encoding="utf-8-sig"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
                getattr(t, "id", "") == "DASHBOARDS" for t in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError("DASHBOARDS not found in Home.py")


def _external():
    return [d for d in _dashboards() if d.get("url")]


def test_the_external_tile_is_kept_out_of_st_navigation():
    """THE ONE THAT TAKES THE PORTAL DOWN. `st.Page("https://...")` raises, and
    `_pages` is built at import time, so registering this entry would stop both
    deployments booting at all on the next reboot — not the page, the portal.

    The filter is asserted on the SOURCE because the failure is at import: a
    test that imported Home.py to check this would itself be the crash."""
    src = HOME.read_text(encoding="utf-8-sig")
    assert '_pages = [d for d in DASHBOARDS if not d.get("url")]' in src, (
        "_pages no longer filters external tiles out of st.navigation; "
        "st.Page() on a URL raises and the portal will not start")

    tree = ast.parse(src)
    pages = next(n for n in tree.body
                 if isinstance(n, ast.Assign)
                 and any(getattr(t, "id", "") == "_pages" for t in n.targets))
    assert "url" in ast.unparse(pages)


def test_every_entry_has_exactly_one_of_page_or_url():
    """A tile with both is ambiguous — `d.get("url") or d["page"]` would pick
    the URL and quietly stop routing a real page. A tile with neither raises
    KeyError mid-render, after the rows above it have already drawn."""
    for d in _dashboards():
        has = [k for k in ("page", "url") if d.get(k)]
        assert len(has) == 1, f"{d['title']} has {has or 'neither'}"


def test_the_grid_renders_whichever_key_the_entry_carries():
    src = HOME.read_text(encoding="utf-8-sig")
    assert 'st.page_link(d.get("url") or d["page"], label=d["title"])' in src


def test_an_external_tile_carries_no_url_path():
    """`url_path` is this app's routing table. An external tile that had one
    would claim a route the portal cannot serve, and the nav filter above means
    nothing would ever register it — so the route would 404 from inside."""
    for d in _external():
        assert "url_path" not in d, d["title"]


def test_the_risk_analyzer_is_last_and_follows_backgrounding_crush():
    """Ross's placement, 2026-11-02: last box, to the right of Backgrounding
    Crush. The grid is one list shared by both deployments, so this fixes it in
    the client view and the staff one together."""
    titles = [d["title"] for d in _dashboards()]
    assert titles[-1] == "JSA Risk Analyzer"
    assert titles[-2] == "Backgrounding Crush"


def test_sixteen_tiles_fill_four_rows_with_no_borrow():
    """Fifteen was 4/4/4/3; sixteen is 4/4/4/4 exactly, so the last-row borrow
    does not fire. Pinned because the borrow reorders tiles when it DOES fire —
    a seventeenth dashboard gives 4/4/4/4/1 and would move this tile up a row,
    out of the corner Ross asked for."""
    per_row = 4
    n = len(_dashboards())
    assert n == 16
    rows = [list(range(i, min(i + per_row, n))) for i in range(0, n, per_row)]
    assert [len(r) for r in rows] == [4, 4, 4, 4]
    assert len(rows[-1]) != 1, "borrow would fire and move the last tile"


def test_the_url_is_the_deployed_app_not_the_repo():
    """A github.com link would send a client to source code."""
    url = _external()[0]["url"]
    assert url == "https://jsa-risk-analyzer.streamlit.app/"
    assert "github" not in url


def test_the_description_warns_about_the_second_password():
    """It is a separate deployment with its own gate, so the tile is the only
    place a reader can be told before they click. Without it a password prompt
    on an unfamiliar dark page reads as something being broken."""
    desc = _external()[0]["desc"]
    assert "new tab" in desc
    assert "password" in desc


def test_no_portal_passphrase_is_handed_to_the_external_app():
    """The link is a bare URL. Appending a token as a query parameter would put
    a portal credential in browser history and in another app's server logs —
    and the two gates are deliberately separate secrets."""
    url = _external()[0]["url"]
    assert "?" not in url and "#" not in url
    for leak in ("PASSPHRASE", "passphrase", "token", "secret"):
        assert leak not in url


@pytest.mark.parametrize("broken", [
    {"title": "X", "url": "https://x", "page": "apps/x/app.py"},   # both
    {"title": "X"},                                                # neither
])
def test_the_detector_rejects_the_broken_forms(broken):
    """A guard that cannot fail is the thing it guards against."""
    has = [k for k in ("page", "url") if broken.get(k)]
    assert len(has) != 1
