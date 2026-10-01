"""
The preview iframe must still be a WELL-FORMED HTML DOCUMENT.

The print button is chrome wrapped around the letter, and the tempting way to
add chrome is to concatenate it on the front. That silently breaks the letter:
a doctype that is not the first thing in the document is discarded, and the
whole page renders in quirks mode, where table rows and margins lay out
differently. Both print paths are supposed to produce the same letter, so a
divergence here is invisible until a client gets a page that does not match.

Measured on the real preview in a real browser, 2026-09-30, before the fix:

    document.compatMode == "BackCompat"      (standards is "CSS1Compat")
    document.doctype is None
    the letter's own <meta>, <title> and <style> all inside <body>
    first cash band 102px tall, against 108px in standards mode

These tests pin the STRUCTURE rather than the mechanism, so they keep holding
if the button's markup or styling changes.
"""
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

APP = ROOT / "apps" / "weekly_reports" / "app.py"

BUTTON_TAG = '<button id="jsa-print"'


def _compose():
    """
    The page's own composer, lifted out without importing the page.

    `apps/weekly_reports/app.py` is a Streamlit script -- importing it would
    run the whole letter builder and demand secrets. Exec'ing just the helper
    keeps this a unit test of the thing that actually broke.
    """
    src = APP.read_text(encoding="utf-8")
    # EVERY module-level triple-quoted constant, discovered rather than listed.
    # A hard-coded pair broke the whole file the moment _IMAGE_SCRIPT was added
    # -- nine tests failing on a NameError that said nothing about the change.
    parts = []
    for m in re.finditer(r'^(_[A-Z][A-Z0-9_]*) = """(.*?)"""', src, re.S | re.M):
        parts.append(m.group(1) + ' = """' + m.group(2) + '"""')
    assert any("_PRINT_STYLE" in p for p in parts), "_PRINT_STYLE not found in app.py"
    assert any("_PRINT_BUTTON" in p for p in parts), "_PRINT_BUTTON not found in app.py"
    m = re.search(r"^def _with_print_button\(doc: str\) -> str:.*?(?=\n\S)",
                  src, re.S | re.M)
    assert m, "_with_print_button not found in app.py"
    ns = {"re": re}
    exec("\n".join(parts) + "\n\n" + m.group(0), ns)
    return ns["_with_print_button"]


LETTER = (
    "<!DOCTYPE html><html><head><meta charset='utf-8'><title>JSA</title>"
    "<style>body{margin:0}</style></head><body><div class='frame'></div>"
    "<p>letter</p></body></html>"
)

# The real letter, reduced to the part that broke the first fix. render.py's
# stylesheet genuinely contains the words "put a background on <body>", so the
# first "<body" in the document is prose inside a CSS comment.
LETTER_WITH_BODY_IN_A_CSS_COMMENT = (
    "<!DOCTYPE html><html><head><title>JSA</title><style>\n"
    "/* z-index -1 puts it under the content, which only works because the\n"
    "   page background lives on <html> -- put a background on <body> and\n"
    "   this disappears underneath it. */\n"
    ".wm { z-index: -1; }\n"
    "</style></head><body class=\"am\"><p>letter</p></body></html>"
)


def test_the_composed_preview_still_starts_with_the_doctype():
    """The whole point. A doctype anywhere but first is thrown away."""
    out = _compose()(LETTER)
    assert out.lstrip().upper().startswith("<!DOCTYPE HTML>"), (
        "the doctype is no longer first -- the preview will render in quirks "
        "mode and stop matching Build PDF"
    )


def test_the_button_style_lands_in_the_head():
    out = _compose()(LETTER)
    head = out[: out.lower().index("</head>")]
    assert "#jsa-print" in head


def test_the_button_itself_lands_inside_the_body():
    out = _compose()(LETTER)
    at = out.index(BUTTON_TAG)
    assert out.lower().index("<body") < at < out.lower().index("</body>")


def test_the_button_survives_a_body_mentioned_in_a_css_comment():
    """
    THE FIRST FIX FAILED HERE, and silently.

    `doc.find("<body")` matched the words "put a background on <body>" inside
    render.py's own stylesheet comment, so the button was inserted into a CSS
    comment and never became an element. The preview rendered perfectly and
    simply had no print button -- the failure mode this repo keeps meeting:
    a search matching prose rather than markup, raising nothing.
    """
    out = _compose()(LETTER_WITH_BODY_IN_A_CSS_COMMENT)
    assert out.index(BUTTON_TAG) > out.index("</style>"), (
        "the button landed inside the stylesheet -- it is inert there"
    )
    assert out.index(BUTTON_TAG) > out.index('<body class="am">')


def test_the_button_is_hidden_when_printing():
    """It is chrome. It must never appear on the client's letter."""
    out = _compose()(LETTER)
    assert re.search(r"@media\s+print\s*\{[^}]*#jsa-print[^}]*display:\s*none", out)


def test_there_is_a_save_as_image_button(monkeypatch=None):
    """Added 2026-10-01 at Ross's ask: a button to save the report as an image."""
    out = _compose()(LETTER)
    assert 'id="jsa-png"' in out
    assert "html2canvas" in out


def test_the_image_button_is_hidden_when_printing():
    """Chrome, like the print button. It must never appear on a client letter."""
    out = _compose()(LETTER)
    assert re.search(r"@media\s+print\s*\{[^}]*#jsa-png[^}]*display:\s*none", out)


def test_the_image_capture_is_told_the_sheet_is_the_viewport():
    """
    THE FRAME AND WATERMARK ARE position:fixed.

    They lay out against whatever window html2canvas is told about. At the
    iframe's real size they hug a ~712px box, the page margin collapses, and
    the frame ends up flush to the image edge.
    """
    out = _compose()(LETTER)
    for opt in ("windowWidth", "windowHeight", "scrollX", "scrollY"):
        assert opt in out, f"{opt} is gone -- fixed-position chrome will mis-render"


def test_the_image_is_captured_in_page_geometry_not_screen_geometry():
    """
    THE IMAGE MUST MATCH THE PDF, which is Ross's ask of 2026-10-01 and the
    whole reason page mode exists.

    render.py has no @media print rules, so the only screen/print difference
    is the page box: an 8.5in sheet with a 0.52in @page margin, against the
    iframe's ~7.42in and no margin. That is a 6.80in text block against a
    6.76in one, which RE-WRAPS LINES -- the first version of this button did
    not even break its text where the PDF does.

    Verified at the time against both artifacts: the PNG came out 1632x2112
    (8.5x11 at 2x) with the first sage pixel 0.5208in in, and the PDF draws
    the frame as a 716x956 css-px rect, which is 8.5x11 less 0.52in a side.
    """
    out = _compose()(LETTER)
    assert "8.5in" in out, "the capture no longer forces the sheet width"
    assert "0.52in" in out, "the frame is no longer offset to the page margin"
    # the body padding that puts the text block where print puts it
    for pad in ("0.72in", "0.85in", "0.90in"):
        assert pad in out, f"page-mode body padding {pad} is gone"


def test_the_image_is_rounded_up_to_whole_sheets():
    """
    A one-page brief should be a full 8.5x11, not cropped to its last line --
    that is what makes it read as the letter rather than as a screenshot.
    """
    out = _compose()(LETTER)
    assert "Math.ceil" in out and "PAGE_H" in out


def test_page_mode_is_removed_afterwards():
    """
    An 8.5in !important left behind would reflow the preview the reader is
    looking at, and it would survive until they navigated away.
    """
    out = _compose()(LETTER)
    assert "mode.remove()" in out


def test_a_cdn_failure_says_so_on_the_button():
    """
    A CDN that does not load otherwise leaves a button that does nothing,
    which is the exact class of silent failure this file exists to avoid.
    """
    out = _compose()(LETTER)
    assert "typeof html2canvas !== 'function'" in out
    assert "did not load" in out


def test_the_letter_is_not_otherwise_altered():
    """Everything the letter said must survive the wrapping, exactly once."""
    out = _compose()(LETTER)
    for fragment in ("<div class='frame'></div>", "<p>letter</p>", "<title>JSA</title>"):
        assert out.count(fragment) == 1


@pytest.mark.parametrize("doc", [
    "<p>no head, no body</p>",
    "<!DOCTYPE html><html><body><p>no head</p></body></html>",
    "<!DOCTYPE html><html><head><title>t</title></head><p>no body tag</p></html>",
])
def test_a_letter_without_a_head_or_body_still_gets_a_button(doc):
    """
    Degrade to prepending rather than losing the button.

    A button in an odd place is cosmetic; a preview with no way to print is
    the one that stops the letter going out.
    """
    out = _compose()(doc)
    assert "jsa-print" in out


def test_the_page_rule_names_a_fixed_size():
    """
    A FIXED size is what suppresses the print dialog's orientation control.

    Chromium's GetPageSizeAndOrientationInfo marks every page kFixed when
    @page names a size, which sets all_pages_have_custom_orientation, and the
    preview then REMOVES the Layout control instead of pre-selecting Portrait;
    the ticket falls back to unavailableValue, which is portrait. `size: auto`
    would give the control back along with the reader's sticky landscape.

    Nothing about the PDF can catch a regression here -- the page box is
    8.5x11 either way -- which is why it is pinned.
    """
    from letter import render

    m = re.search(r"@page\s*\{([^}]*)\}", render.CSS)
    assert m, "@page rule is gone"
    size = re.search(r"size:\s*([^;]+)", m.group(1))
    assert size, "@page no longer names a size"
    assert size.group(1).strip() != "auto", (
        "@page size went to auto -- Chromium will show the Layout control "
        "again and honour the reader's sticky orientation"
    )


def test_the_page_rule_does_not_carry_a_redundant_portrait_keyword():
    """
    Pins a fix that was WRONG, so nobody re-applies it.

    `size: letter portrait` was committed on 2026-09-30 to fix a dialog stuck
    on landscape. Blink discards an orientation keyword that is redundant with
    an already-portrait named size, so it parses to exactly `size: letter` --
    confirmed by reading the rule back through a live CSSOM, where it
    serialises without the keyword. The commit could not have done anything,
    and leaving it in the file would document a mechanism that does not exist.
    """
    from letter import render

    m = re.search(r"@page\s*\{([^}]*)\}", render.CSS)
    size = re.search(r"size:\s*([^;]+)", m.group(1)).group(1).strip().lower()
    assert "portrait" not in size, (
        "Blink drops `portrait` after a portrait named size -- this is inert, "
        "and it misrepresents why the orientation control disappears"
    )


def test_the_page_does_not_concatenate_the_chrome_onto_the_front():
    """
    Pins the REGRESSION, not just the fix.

    `_print_ui + html` is the shape that broke it, and it is the shape someone
    reaches for again when adding a second button. Comments and docstrings are
    stripped first: this repo's tests have matched their own prose before.
    """
    src = APP.read_text(encoding="utf-8")
    src = re.sub(r'"""(.*?)"""', "", src, flags=re.S)
    src = re.sub(r"#.*", "", src)
    assert "_print_ui" not in src, "the old front-concatenated chrome is back"
    assert "_with_print_button(html)" in src
