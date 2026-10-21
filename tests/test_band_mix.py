"""The Census weight mix, month by month.

Census publishes head against its own HS weight classes, so a SHARE is
division and nothing else -- the only assumption-free weight statement
available for cattle crossing the border. An AVERAGE is not available and must
never be derived here: the top class is open-ended ("320 kg or more") and held
1.4% of head across the record but 27.8% in August 2026, so assuming 360
against 450 kg for it swings a head-weighted average from 635 lb to 690. The
assumption would be worst in exactly the months anyone wants the number for.

    python -m pytest tests/test_band_mix.py -q
"""

import ast
import inspect
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_APP = os.path.join(_HERE, "..", "apps", "mexican_feeder_imports")
sys.path.insert(0, _APP)

import border as bd  # noqa: E402

PAGE = os.path.join(_APP, "app.py")


def _page():
    return open(PAGE, encoding="utf-8-sig").read()


def _code_of(fn):
    """Source with the docstring stripped -- these guards must read code, not
    the prose explaining the rule. The trap tests/test_rundown.py records."""
    node = ast.parse(inspect.getsource(fn).lstrip()).body[0]
    body = node.body
    if (body and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)):
        body = body[1:]
    return chr(10).join(ast.unparse(n) for n in body)


# ── a fake warehouse, so the arithmetic is pinned without one ───────────────

class _Cur:
    def __init__(self, rows):
        self._rows = rows

    def execute(self, *_a, **_k):
        return self

    def fetchall(self):
        return self._rows


class _Conn:
    def __init__(self, rows):
        self._rows = rows

    def cursor(self):
        return _Cur(self._rows)


LIGHT = ("CATTLE, LIVE, MALE, WEIGHING 90 KG OR MORE BUT LESS THAN 200 KG "
         "EACH, OTHER THAN PUREBRED BREEDING AND/OR DAIRY")
MID = ("CATTLE, LIVE, MALE, WEIGHING 200 KG OR MORE BUT LESS THAN 320 KG "
       "EACH, OTHER THAN PUREBRED BREEDING AND/OR DAIRY")
HEAVY = ("CATTLE, LIVE, MALE, WEIGHING 320 KG OR MORE EACH, NESOI")


def _rows(spec):
    """spec: {period: (light, mid, heavy)} -> _national()-shaped rows."""
    out = []
    for period, (lo, mid, hi) in spec.items():
        for descr, head in ((LIGHT, lo), (MID, mid), (HEAVY, hi)):
            out.append((period, "0102294054", descr, head, 0))
    return out


def test_the_months_are_contiguous_across_a_closure():
    """THE HOLES ARE THE STORY. Census is simply absent for 2025-01 and for
    2026-01..2026-07 -- the screwworm closures -- and plotting only the months
    that exist would pack a 14-month shutdown into the gap between two
    adjacent points. The grid is filled; the blanks are None."""
    mx = bd.band_mix_monthly(_Conn(_rows({
        "2024-10": (25_000, 70_000, 1_000),
        "2024-11": (25_000, 70_000, 1_000),
        # 2024-12 .. 2025-02 absent entirely
        "2025-03": (2_000, 60_000, 12_000),
    })))
    assert mx["months"] == ["2024-10", "2024-11", "2024-12",
                            "2025-01", "2025-02", "2025-03"]
    assert mx["head"][2] is None and mx["head"][3] is None
    assert mx["head"][0] and mx["head"][-1]


def test_a_month_with_no_cattle_has_no_mix_rather_than_a_zero_one():
    """A zero share reads as "no light cattle crossed". Nothing crossed."""
    mx = bd.band_mix_monthly(_Conn(_rows({
        "2025-04": (1_000, 50_000, 9_000),
        "2025-05": (0, 0, 0),
        "2025-06": (1_000, 50_000, 9_000),
    })))
    i = mx["months"].index("2025-05")
    assert mx["head"][i] is None
    for b in mx["bands"]:
        assert mx["share"][b][i] is None, (
            f"{b} prints a share for a month in which nothing crossed")


def test_shares_sum_to_a_hundred_on_every_live_month():
    mx = bd.band_mix_monthly(_Conn(_rows({
        "2024-01": (25_000, 70_000, 1_000),
        "2024-02": (10_000, 60_000, 30_000),
    })))
    for i, h in enumerate(mx["head"]):
        if h is None:
            continue
        tot = sum(mx["share"][b][i] for b in mx["bands"])
        assert abs(tot - 100) < 1e-6, (mx["months"][i], tot)


def test_a_thin_month_is_flagged_rather_than_dropped():
    """July 2025 prints 52.8% in the top band off 4,339 head -- one load, and
    on a share chart it reads as a regime change. It is still real data and is
    still shown; the page says what it rests on."""
    mx = bd.band_mix_monthly(_Conn(_rows({
        "2026-07": (0, 40_000, 20_000),
        "2026-08": (0, 1_800, 653),
    })))
    assert ("2026-08", 2_453) in mx["thin"]
    assert ("2026-07", 60_000) not in mx["thin"]
    i = mx["months"].index("2026-08")
    assert mx["head"][i] == 2_453, "the thin month was dropped, not flagged"


def test_a_negligible_band_is_omitted_but_its_head_is_reported():
    """`<90 kg` is 252 head in seven years and a flat line on the axis. It
    comes off the chart, and the caller is handed the total so the page can
    say what was left out rather than quietly dropping it."""
    bob = ("CATTLE, LIVE, MALE, WEIGHING LESS THAN 90 KG EACH, OTHER THAN "
           "PUREBRED BREEDING AND/OR DAIRY")
    rows = _rows({"2024-01": (25_000, 70_000, 1_000)})
    rows.append(("2024-01", "0102294010", bob, 40, 0))
    mx = bd.band_mix_monthly(_Conn(rows))
    assert bd.BANDS[0] not in mx["bands"]
    assert mx["omitted"].get(bd.BANDS[0]) == 40


def test_the_baseline_is_the_twelve_months_before_the_border_shut():
    """Not a calendar year. The first closure landed in December, so a year
    would mix two regimes and understate the change the chart exists to show.
    """
    spec = {"2023-12": (25_000, 70_000, 1_000)}
    spec.update({f"2024-{m:02d}": (25_000, 70_000, 1_000)
                 for m in range(1, 12)})
    spec["2024-12"] = (0, 0, 0)
    spec["2025-01"] = (0, 0, 0)
    spec["2025-02"] = (500, 20_000, 5_000)
    mx = bd.band_mix_monthly(_Conn(_rows(spec)))
    assert mx["baseline"] is not None
    bl = mx["baseline"]
    # PERIODS, not a formatted label -- fmt_month lives on the page, and a
    # module that spells a month commits the page to that spelling.
    assert (bl["from"], bl["to"]) == ("2023-12", "2024-11"), bl
    assert bl["head"] == 12 * 96_000
    assert abs(bl["share"][bd.BANDS[1]] - 25_000 / 96_000 * 100) < 1e-6


def test_a_run_too_short_to_be_twelve_months_yields_no_baseline():
    """The caption says "the twelve months before the border first shut". A
    shorter window would make that sentence false while every figure in it
    stayed correct, so the baseline is withheld and the headline caption
    simply does not render -- the rest of the panel still does."""
    spec = {f"2024-{m:02d}": (25_000, 70_000, 1_000) for m in range(1, 7)}
    spec["2024-07"] = (0, 0, 0)
    spec["2024-08"] = (500, 20_000, 5_000)
    mx = bd.band_mix_monthly(_Conn(_rows(spec)))
    assert mx["baseline"] is None
    assert mx["latest"] is not None, "the rest of the panel must survive"


def test_the_latest_is_the_newest_month_that_actually_carried_cattle():
    mx = bd.band_mix_monthly(_Conn(_rows({
        "2026-07": (0, 40_000, 20_000),
        "2026-08": (0, 0, 0),
    })))
    assert mx["latest"]["month"] == "2026-07"


# ── the module must not invent an average ───────────────────────────────────

def test_the_module_derives_no_average_weight():
    """The top class is open-ended, so any average carries an unverifiable
    midpoint. A future edit that quietly adds one would render perfectly."""
    src = _code_of(bd.band_mix_monthly)
    for forbidden in ("midpoint", "avg_weight", "average_weight", "/ 2",
                      "kg_mid", "MID_KG"):
        assert forbidden not in src, (
            f"band_mix_monthly contains {forbidden!r} -- an average weight "
            f"cannot be computed from an open-ended top class")


def test_the_page_calls_it_a_mix_and_says_why_not_an_average():
    page = _page()
    assert "This is a mix, not an average weight" in page
    assert "open-ended" in page


# ── the chart must not bridge the closure ───────────────────────────────────

def test_the_lines_do_not_connect_across_a_closure():
    """A bridged line draws a smooth handover from light cattle to heavy ones
    across months in which nothing crossed. Plotly's default is already
    False; it is set explicitly because the cost of it flipping is a chart
    that lies and still renders."""
    page = _page()
    i = page.index('"band_mix"')
    block = page[i:]
    assert "connectgaps=False" in block, (
        "the monthly mix traces do not pin connectgaps")


def test_the_mix_is_counted_on_feeder_cattle_only():
    """Slaughter, breeding and dairy entries answer different questions, and
    the rest of this page's head counts are feeders."""
    assert "kinds" in inspect.signature(bd.band_mix_monthly).parameters
    assert (inspect.signature(bd.band_mix_monthly)
            .parameters["kinds"].default == ("feeder",))
