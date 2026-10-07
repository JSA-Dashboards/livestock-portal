"""Proof that the Mexican auction scraper reads mexicoganadero.com correctly.

The fixture below is real markup from that site, trimmed. Everything pinned
here is something that fails SILENTLY -- a mangled class name still carries
correct prices, a per-head figure still looks like a price, and a heifer
labelled as a steer still charts.

    python -m pytest tests/test_mx_auction.py -q
"""

import os
import sys
from datetime import date

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "..", "deploy"))

import mx_auction as mx  # noqa: E402


def _row(name, lo, hi, avg):
    return (f"<tr bgcolor='black'>"
            f"<td><font size='1'><b>{name}</b></font></td>"
            f"<td><font size='1'><b>${lo}</b></font></td>"
            f"<td><font size='1'><b>${hi}</b></font></td>"
            f"<td><font size='1'><b>${avg}</b></font></td></tr>"
            f"<tr><td></td><td></td><td></td><td></td></tr>")


HEADER = ("<tr bgcolor='black''><td><font size='1' color='white'>Clasificacion</font></td>"
          "<td><font size='1'>Minimo</font></td><td><font size='1'>Maximo</font></td>"
          "<td><font size='1'>Promedio</font></td></tr>")

PAGE = (
    "<center><b>SUBASTA GANADERA DE TAMAULIPAS</b><br>\n"
    "Precios del <b>24/sep/2026</b><br></font></center></td></tr></table>\n"
    "<table width='728'>" + HEADER
    + _row("BECERRA CN MENOR A 150KG", "90.00", "104.00", "97.00")
    + _row("BECERRO CN MENOR 150KG", "94.00", "121.00", "105.67")
    + _row("BECERRO CN 151-180KG", "85.00", "110.00", "100.69")
    + _row("BECERRO CNH 251-330", "75.00", "75.00", "75.00")
    + _row("NOVILLOS", "70.00", "78.50", "75.00")
    + "</table>\n"
    "<center><b>SUBASTA GANADERA DE DURANGO</b><br>\n"
    "Precios del <b>01/oct/2026</b><br></font></center></td></tr></table>\n"
    "<table width='728'>" + HEADER
    + _row("VACA GORDA", "40.00", "57.50", "49.25")
    + _row("VACA PARIDA", "30000.00", "35000.00", "32500.00")
    + "</table>"
)


def test_the_page_yields_both_auctions_with_their_own_dates():
    qs = mx.parse(PAGE)
    assert {(q.auction, q.sale_date) for q in qs} == {
        ("TAMAULIPAS", date(2026, 9, 24)), ("DURANGO", date(2026, 10, 1))}


def test_spanish_month_abbreviations():
    """strptime cannot read these -- %b is locale-dependent and cron runs under C."""
    assert mx.parse_sale_date("24", "sep", "2026") == date(2026, 9, 24)
    assert mx.parse_sale_date("01", "oct", "2026") == date(2026, 10, 1)
    assert mx.parse_sale_date("31", "dic", "2025") == date(2025, 12, 31)
    assert mx.parse_sale_date("01", "ene", "2027") == date(2027, 1, 1)
    assert mx.parse_sale_date("15", "xxx", "2026") is None
    assert mx.parse_sale_date("31", "feb", "2026") is None      # not a real day


def test_all_three_weight_band_spellings():
    """All three are live on the page at once, and one carries no 'KG' at all."""
    assert mx.weight_band("BECERRA CN MENOR A 150KG") == (None, 150)
    assert mx.weight_band("BECERRO CN MENOR 150KG") == (None, 150)
    assert mx.weight_band("BECERRO CN 151-180KG") == (151, 180)
    assert mx.weight_band("BECERRO CNH 251-330") == (251, 330)
    assert mx.weight_band("NOVILLOS") == (None, None)


def test_a_band_without_kg_is_not_dropped():
    """The regression that would be invisible: a real band with real head gone."""
    q = [x for x in mx.parse(PAGE) if x.clasificacion == "BECERRO CNH 251-330"]
    assert len(q) == 1 and q[0].low_kg == 251 and q[0].high_kg == 330


def test_heifers_are_not_labelled_steers():
    """Every female name contains the male one as a prefix.

    BECERRA starts BECERRO's stem, NOVILLONA starts NOVILLO, TERNERA starts
    TERNER. A male-first scan calls every heifer a steer and nothing raises.
    """
    assert mx.sex_of("BECERRA CN MENOR A 150KG") == "F"
    assert mx.sex_of("BECERRO CN 151-180KG") == "M"
    assert mx.sex_of("NOVILLONA TERMINADA") == "F"
    assert mx.sex_of("NOVILLOS") == "M"
    assert mx.sex_of("TERNERA") == "F"
    assert mx.sex_of("TERNERO") == "M"
    assert mx.sex_of("DESTETE MACHO") is None


def test_per_head_rows_are_marked_not_averaged_in():
    """Durango prints 32,500 for a cow-and-calf beside 49.25 for a fat cow.

    Same column, no unit given. Averaged together the per-head figure does not
    read as an outlier, it reads as the market moving.
    """
    qs = {q.clasificacion: q for q in mx.parse(PAGE)}
    assert qs["VACA PARIDA"].unit == mx.PER_HEAD
    assert qs["VACA GORDA"].unit == mx.PER_KG
    assert qs["BECERRO CN 151-180KG"].unit == mx.PER_KG


def test_the_unit_split_has_room_either_side():
    """Not a tuned threshold: two orders of magnitude separate the populations."""
    assert mx.unit_of((30.0, 150.0, 90.0)) == mx.PER_KG
    assert mx.unit_of((None, None, 149.9)) == mx.PER_KG
    assert mx.unit_of((None, None, 32500.0)) == mx.PER_HEAD
    # decided on the LARGEST present value, so a blank minimum cannot flip it
    assert mx.unit_of((None, 30000.0, None)) == mx.PER_HEAD


def test_header_and_spacer_rows_are_not_quotes():
    qs = mx.parse(PAGE)
    assert all(q.clasificacion.lower() != "clasificacion" for q in qs)
    assert all(q.clasificacion.strip() for q in qs)
    assert len(qs) == 7


def test_prices_parse_and_a_blank_is_none_not_zero():
    qs = {q.clasificacion: q for q in mx.parse(PAGE)}
    q = qs["BECERRO CN 151-180KG"]
    assert (q.minimum, q.maximum, q.average) == (85.0, 110.0, 100.69)
    assert mx._money("<td></td>") is None
    assert mx._money("$-") is None
    assert mx._money("") is None


def test_the_page_is_cp1252_not_utf8():
    """0xD1 is Ñ in cp1252 and Ń in the windows-1250 chardet guesses.

    The site sends no charset at all, so requests falls back to a guess that
    is wrong. The damage is cosmetic and therefore survives review -- a
    mangled class NAME still carries correct PRICES.
    """
    assert mx.ENCODING == "cp1252"
    assert b"VACA PRE\xd1ADA".decode(mx.ENCODING) == "VACA PREÑADA"


def test_only_the_first_three_value_columns_are_taken():
    """Yucatan adds prior-sale, month and year-ago averages to the same row.

    They are averages OF this series; storing them would bank the same number
    twice under different dates.
    """
    wide = PAGE.replace(
        "<td><font size='1'><b>$100.69</b></font></td></tr>",
        "<td><font size='1'><b>$100.69</b></font></td>"
        "<td><b>$99.00</b></td><td><b>$98.63</b></td><td><b>$95.50</b></td></tr>")
    q = [x for x in mx.parse(wide) if x.clasificacion == "BECERRO CN 151-180KG"][0]
    assert (q.minimum, q.maximum, q.average) == (85.0, 110.0, 100.69)


def test_nothing_parses_out_of_an_empty_or_broken_page():
    assert mx.parse("") == []
    assert mx.parse("<html><body>down for maintenance</body></html>") == []


def test_the_primary_auction_is_the_one_with_weight_bands():
    """Tamaulipas is why this exists; the others ride along on the same fetch."""
    assert mx.PRIMARY_AUCTION == "TAMAULIPAS"
    banded = [q for q in mx.parse(PAGE)
              if q.auction == "TAMAULIPAS" and q.high_kg is not None]
    assert len(banded) >= 3


# ── the USD equivalent ──────────────────────────────────────────────────────

def test_mxn_per_kg_converts_to_usd_per_cwt():
    """Two conversions in one step: kg->lb, then MXN->USD, then lb->cwt.

    Pinned against a real quote: the 181-200 kg becerro averaged 95.86 MXN/kg
    at the 24 Sep sale, and the ECB had the peso at 17.5841 that day.
    """
    assert mx.usd_per_cwt(95.86, 17.5841) == pytest.approx(247.28, abs=0.01)
    assert mx.usd_per_cwt(105.67, 17.5841) == pytest.approx(272.58, abs=0.01)
    # 1 kg = 2.2046226 lb, so a round 100 MXN/kg at a round 20 is easy to check
    # by hand: 100/2.2046226 = 45.359 MXN/lb, /20 = 2.268 USD/lb, = 226.80/cwt
    assert mx.usd_per_cwt(100.0, 20.0) == pytest.approx(226.80, abs=0.01)


def test_a_missing_rate_leaves_the_cell_empty_rather_than_implying_one():
    """None must propagate. A falsy rate treated as 1.0 prices a calf in pesos
    and labels it dollars -- a number eighteen times too big that still looks
    like a price."""
    assert mx.usd_per_cwt(95.86, None) is None
    assert mx.usd_per_cwt(95.86, 0) is None
    assert mx.usd_per_cwt(None, 17.5841) is None


def test_the_peso_moves_enough_that_the_rate_must_match_the_sale_date():
    """17.5841 on 24 Sep against 18.0943 on 7 Oct -- about 3% in two weeks.

    Converting an old sale at today's rate would move the spread by more than
    most weeks of cattle trade do, so a single live rate applied to history
    reports currency as though it were market.
    """
    at_sale = mx.usd_per_cwt(95.86, 17.5841)
    at_today = mx.usd_per_cwt(95.86, 18.0943)
    assert abs(at_sale - at_today) / at_sale > 0.025


def test_fx_lives_in_its_own_table_not_on_the_price_row():
    """Prices are banked when prices change, rates when rates change."""
    assert mx.FX_TABLE != mx.TABLE
    ddl = " ".join(mx.DDL)
    assert "MXN_PER_USD" not in ddl and "FX" not in ddl
    assert "RATE_DATE" in " ".join(mx.FX_DDL)


def test_per_head_rows_are_not_converted_as_though_per_kilo():
    """A 32,500 MXN cow run through a per-kg conversion reads as $84,000/cwt."""
    q = [x for x in mx.parse(PAGE) if x.clasificacion == "VACA PARIDA"][0]
    assert q.unit == mx.PER_HEAD
    # the page only converts PER_KG rows; this asserts the flag it switches on
    assert mx.usd_per_cwt(q.average, 17.5841) > 10_000


# ── the droplet contract, read off the host on 2026-10-07 ───────────────────
# These pin facts about the machine, not about this code, and every one of them
# is a way the job installs cleanly and then does nothing.

_DEPLOY = os.path.join(_HERE, "..", "deploy")
_INSTALLER = os.path.join(_DEPLOY, "install_mx_auction_cron.sh")
_WRAPPER = os.path.join(_DEPLOY, "run_mx_auction.sh")


def test_the_cron_line_never_invokes_python_directly():
    """cron gives a job almost no environment and this host keeps its Snowflake
    block in a .env FILE beside the code. A crontab line calling python gets no
    credentials and writes nothing, every run, looking installed.
    """
    src = open(_INSTALLER, encoding="utf-8").read()
    line = next(l for l in src.splitlines() if l.startswith("CRON_LINE="))
    assert "/bin/python" not in line and "python3" not in line, line
    assert "run_mx_auction.sh" in line, line


def test_the_cron_line_goes_through_the_alert_wrapper():
    """The droplet's crontab header, verbatim: "cron here has no MAILTO and the
    box has no MTA, so a bare entry fails silently." The exit code reaching
    /opt/alerting/cron-alert is the entire alerting contract.
    """
    src = open(_INSTALLER, encoding="utf-8").read()
    line = next(l for l in src.splitlines() if l.startswith("CRON_LINE="))
    assert "/opt/alerting/cron-alert" in line or "$ALERT" in line, line
    assert "ALERT=\"/opt/alerting/cron-alert\"" in src


def test_the_installer_refuses_without_the_alert_wrapper():
    src = open(_INSTALLER, encoding="utf-8").read()
    assert '[ ! -x "$ALERT" ]' in src, "a missing cron-alert must be a hard stop"


def test_the_installer_sources_dotenv_rather_than_the_shell():
    """An earlier version checked exported variables only, so a correctly
    configured droplet reported every one MISSING and the installer refused to
    run on a host that was ready."""
    src = open(_INSTALLER, encoding="utf-8").read()
    assert '. "$DEST/.env"' in src or 'source "$DEST/.env"' in src


def test_the_wrapper_sources_dotenv_and_exits_nonzero_on_failure():
    src = open(_WRAPPER, encoding="utf-8").read()
    assert "source .env" in src
    assert 'exit "$rc"' in src, "cron-alert keys on the exit code"


def test_the_wrapper_handles_a_missing_flock_explicitly():
    """`if ! flock -n 9` reads as "could not take the lock" when flock is simply
    absent -- command-not-found is 127 and `!` makes that true -- so the job
    exits 0 having done nothing."""
    src = open(_WRAPPER, encoding="utf-8").read()
    assert "command -v flock" in src


def test_the_installer_reads_the_crontab_back_after_writing():
    """THE BUG THAT SAID "cron installed" WHEN NOTHING WAS SCHEDULED.

    The script printed "appending", piped into `crontab -`, and went straight
    to its done banner. A write that never took read as a clean install and
    said so. The only thing resembling a check was a trailing `crontab -l |
    grep` whose EMPTY output looked exactly like a successful one -- a check
    whose failure is indistinguishable from its success is not a check.

    What proved it had not installed was the data, not the installer: every row
    in MX_AUCTION_PRICES carried RECORDED_BY = mx_auction@JSA-Nitro2, Ross's
    desktop, and none from the droplet.
    """
    src = open(_INSTALLER, encoding="utf-8").read()
    assert 'grep -cF "$CRON_TAG"' in src, "no count-based read-back"
    assert '[ "$installed" -ne 1 ]' in src, "the read-back does not assert a count"
    # It must STOP, not warn: a warning in a long install log is not read.
    tail = src[src.index('grep -cF "$CRON_TAG"'):]
    assert "exit 1" in tail, "a failed read-back must exit non-zero"


def test_the_installer_points_at_the_wrappers_own_logs():
    """The wrapper writes timestamped logs inside the checkout. A leftover
    /var/log path would have cron-alert attach a file nothing writes, so a
    failure mail would arrive carrying nothing.

    COMMENTS ARE STRIPPED FIRST. The first version of this test failed on the
    installer's own comment saying "nothing writes /var/log any more" -- the
    same trap tests/test_rundown.py records for its AST assertion, where the
    check tripped over the docstring explaining the rule it was checking.
    """
    code = "\n".join(
        l for l in open(_INSTALLER, encoding="utf-8").read().splitlines()
        if not l.lstrip().startswith("#")
    )
    assert "/var/log" not in code
    assert 'LOG_GLOB="$DEST/logs/mx_auction_*.log"' in code
