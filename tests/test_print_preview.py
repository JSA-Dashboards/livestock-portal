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


# ── one image per page ───────────────────────────────────────────────────────

def test_a_multipage_letter_saves_one_image_per_page():
    """
    A TALL IMAGE IS UNREADABLE IN A TEXT, which is the whole reason for this.

    Ross texts the letter to clients through RingCentral. The 2026-10-02
    afternoon letter came out 1632x6336 — about 1:3.9 — and a phone fits an
    image to the bubble width, so 6336px of height is squeezed to roughly
    1400 and 8.5pt body text lands near ONE PIXEL tall. MMS re-compresses on
    top, so zooming magnifies pixels that no longer hold the letter. The
    one-page brief works because 8.5x11 is about 1:1.3.

    Measured after the split: three sheets at aspect 1.38 / 1.29 / 1.29.
    """
    out = _compose()(LETTER)
    assert "page ' + (idx + 1) + ' of ' + pages" in out
    assert "Math.round(canvas.height / pageH)" in out


def test_the_cut_measures_only_the_text_column():
    """
    THE FRAME DEFEATS A FULL-WIDTH SCAN. The sage frame runs down both edges
    of every page, so "emptiest row" never reads zero — a blank row scored 2
    and a line of text scored 40, which is not the signal it looks like.
    Scanning inside the 0.95in margin makes a clean row read exactly 0, and
    only then does the cut finder work.
    """
    out = _compose()(LETTER)
    assert "0.95 * PX * 2" in out, "the ink scan is no longer inset past the frame"


def test_the_cut_searches_outward_from_the_nominal():
    """
    A top-down scan returns the FIRST blank row in the window and dragged a
    cut 200px even when the nominal position was already clean. Walking
    outwards takes the NEAREST clean row, so a page needing no adjustment
    gets none — verified: cut 2 moved 0px, cut 1 moved 118px to escape text.
    """
    out = _compose()(LETTER)
    assert "nominal - d" in out and "nominal + d" in out


def test_the_cut_is_centred_in_the_blank_run():
    """
    Taking the first clean row left page 1's last line flush against the
    bottom edge with no margin — nothing sliced, but it looks broken on a
    client letter. Centring in the run gives the page above a bottom margin
    and the page below a top one. After: every page has ink-free rows at
    both edges.
    """
    out = _compose()(LETTER)
    assert "midOfRun" in out


def test_each_page_image_is_stamped_with_its_number():
    """
    THE CLIENT NEVER SEES THE FILENAME. The pages go out as three separate
    texts, and MMS guarantees no ordering across carriers, so a reader
    holding a bubble of pixels has no way to tell that page 2 is missing or
    that it arrived before page 1. The filename carries it; the image did
    not. Now it does.
    """
    out = _compose()(LETTER)
    assert "'Page ' + (idx + 1) + ' of ' + pages" in out
    assert "c.fillText(" in out


def test_the_page_label_gets_its_own_strip():
    """
    IT CANNOT SHARE THE PAGE'S BOTTOM MARGIN, because that margin is not a
    fixed size. The cut lands wherever the blank run is, so on the real
    2026-10-02 letter the white below the last line of text measured 23px on
    page 1 against 83 and 99 on pages 2 and 3 — there is no offset clear of
    the text on all three. Reserving a strip makes the space exist.
    """
    out = _compose()(LETTER)
    assert "Math.max(bot - top, pageH) + LABEL_H" in out, (
        "the label no longer has reserved space and can land on the text"
    )


def test_a_single_page_letter_is_not_stamped():
    """
    The morning brief is one page. "Page 1 of 1" on it would be noise, and
    the strip would make it taller than a sheet for no reason. Same rule the
    filename already follows.
    """
    out = _compose()(LETTER)
    assert "pages > 1 ? 52 : 0" in out


def test_the_label_fits_inside_its_strip():
    """
    Arithmetic rather than a string match, because the failure here is
    silent: a font bumped past the strip height, or a baseline offset raised
    above it, draws the label over the last line of the letter and nothing
    raises. Checks the glyph box sits inside the reserved band.
    """
    out = _compose()(LETTER)
    strip = int(re.search(r"pages > 1 \? (\d+) : 0", out).group(1))
    baseline = int(re.search(r"slice\.height - (\d+)\)", out).group(1))
    size = int(re.search(r"c\.font = '\d+ (\d+)px", out).group(1))

    # Baseline measured up from the slice bottom; the descender hangs below
    # it and the cap height rises above. 0.25/0.8 of the em is generous for
    # Calibri and keeps this from being a restatement of the constants.
    assert baseline + size * 0.8 <= strip, (
        f"label top {baseline + size * 0.8:.0f}px exceeds the {strip}px strip"
    )
    assert baseline - size * 0.25 > 0, "the descender falls off the bottom edge"


def test_there_are_two_image_buttons_for_two_destinations():
    """
    TEXTING AND HUBSPOT WANT OPPOSITE THINGS. A phone fits an image to the
    bubble width, so a multi-page letter has to be split or 8.5pt body text
    lands near one pixel tall. HubSpot's email editor takes a SINGLE asset
    and will not accept a set of page images -- dragging them in does not
    work. One capture, two save paths.
    """
    out = _compose()(LETTER)
    assert 'id="jsa-png"' in out and 'id="jsa-png-one"' in out
    assert "Save pages (texting)" in out
    assert "Save one image (HubSpot)" in out


def test_both_buttons_share_one_capture_path():
    """
    If the two exports captured separately they could drift into producing
    different-looking letters -- different margins, different line breaks --
    and nobody would notice until a client had both.
    """
    out = _compose()(LETTER)
    assert out.count("html2canvas(el, {") == 1
    assert "function wire(btn, split)" in out
    assert "wire(document.getElementById('jsa-png'), true)" in out
    assert "wire(document.getElementById('jsa-png-one'), false)" in out


def test_the_single_image_skips_the_page_stamp_and_the_cutting():
    """
    The one-image export returns before any of the splitting work: no
    "Page N of M", no cut-finding, and a filename with no page suffix.
    Verified in a browser on a real 3-page letter: one 1632x6336 PNG from
    the HubSpot button, three stamped pages from the texting one.
    """
    out = _compose()(LETTER)
    i = out.index("if (!split) {")
    j = out.index("ONE IMAGE PER PAGE")
    single = out[i:j]
    assert "one.download = base + '.png';" in single
    assert "Page ' + (idx + 1)" not in single
    assert "cutNear" not in single


def test_the_single_image_is_content_height_not_whole_sheets():
    """
    HALF THE HUBSPOT IMAGE WAS EMPTY WHITE. Measured on the 2026-10-07
    afternoon report: scrollHeight 1161px against a 1056px sheet, 105px
    over, rounded up to 2112 — so 951px of blank paper went into the email
    under the letter. Reported by Ross.

    The paged export still rounds up: each page has to read as a sheet, and
    the splitter cuts on whole-sheet boundaries.
    """
    out = _compose()(LETTER)
    assert "split ? Math.max(1, Math.ceil(el.scrollHeight / PAGE_H)) * PAGE_H" in out
    assert ": el.scrollHeight;" in out


def test_the_watermark_centres_because_the_capture_height_is_right():
    """
    The 50-years mark is `position: fixed; top: 46%`, and html2canvas lays
    fixed elements out against the windowHeight it is handed. Rounding the
    single image up to two sheets therefore put it at 46% of 2112 — down by
    the signature rather than on the middle of the page.

    So there is no watermark special-case anywhere, and there should not
    be: capturing at the real height centres it by construction. Ross
    reported the white band and the off-centre mark separately; they were
    one cause. Verified on the export itself — the light-grey centroid
    lands at 46.3% of image height, and horizontally within a pixel of
    centre because `left: 50%` resolves against the captured sheet width.
    """
    out = _compose()(LETTER)
    assert "windowHeight: h" in out, "fixed elements no longer see the capture height"
    assert ".wm" not in out.split("_IMAGE_SCRIPT")[-1][:4000], (
        "a watermark special-case appeared; the height fix should make one "
        "unnecessary")


def test_multiple_downloads_are_staggered():
    """
    Chrome drops some downloads fired in a tight loop from one gesture, and
    raises its "allow multiple downloads" prompt per file rather than once.
    """
    out = _compose()(LETTER)
    assert "setTimeout" in out and "600" in out
