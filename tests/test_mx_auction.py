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
sys.path.insert(0, os.path.join(_HERE, "..", "scripts"))

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
