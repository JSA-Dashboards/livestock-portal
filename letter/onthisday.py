"""
"On this day" candidates for the letter, as a pick list.

WHAT THIS IS NOT. Nothing here writes itself into a letter. These are
candidates on the authoring page, exactly like the headlines, and for exactly
the same reason: a fact is EDITORIAL, and the rule this generator is built on
is that no fetched editorial text reaches a client under JSA's name without a
human choosing it. Every other figure in the letter is a USDA or CME number
that is either right or marked [[?]]; a fun fact cannot be marked.

WHY A HUMAN IS THE SAFETY, AND NOT THE FILTER. The first version of this
filter offered the 2017 Las Vegas mass shooting as an AGRICULTURE fact --
"Route 91 Harvest festival" matched the farming pattern, and the grim filter
missed it because every stem in it was written \\bmurder\\b, which does not
match "murdered". Khashoggi, Mogadishu and the Amish school shooting came
through the same hole.

Two lessons are baked in below. Stems match as PREFIXES. And a candidate must
earn its place POSITIVELY -- sport, agriculture, or a US first -- rather than
being admitted unless something looks wrong. A denylist over an encyclopaedia
fails open, and failing open here means handing Ross a massacre to pick from.
Even so, the filter will let something tasteless through eventually. That
costs a glance, because he picks. It would cost a letter if it did not.

THE FACTS ARE NOT THE PROSE. history.com's blurbs are copyrighted editorial
writing; the underlying events are facts and are not. So the panel shows the
headline and the year as a PROMPT, links out to the source, and the caption
says to write it in your own words -- the same instruction the headline panel
already carries.

    python -c "from letter import onthisday; print(onthisday.candidates())"
"""
from __future__ import annotations

import json
import re
import urllib.request
from datetime import date

UA = {"User-Agent": "Mozilla/5.0 (compatible; JSA-letter/1.0; +https://www.jpsi.com)"}

HISTORY_URL = "https://www.history.com/this-day-in-history/{month}-{day}"
WIKI_URL = ("https://api.wikimedia.org/feed/v1/wikipedia/en/onthisday/"
            "{kind}/{mm:02d}/{dd:02d}")

_MONTHS = ("january", "february", "march", "april", "may", "june", "july",
           "august", "september", "october", "november", "december")

# PREFIX STEMS, NO TRAILING BOUNDARY. \\bmurder\\b does not match "murdered",
# which is how the first version let four atrocities through. Deliberately
# broad: a false negative is a duller list, a false positive is grotesque.
_GRIM = re.compile(
    r"(kill|death|died|dead|dies|\bdie\b|fatal|massacr|genocid|murder|assassinat|"
    r"execut|suicide|bomb|shoot|shot|gunman|gunfire|stabb|\bwar\b|warfare|invad|"
    r"invasion|battle|troops|militant|ambush|siege|earthquake|tsunami|hurricane|"
    r"cyclone|flood|famine|plague|epidemic|pandemic|crash|derail|sank|sink|wreck|"
    r"disaster|collapse|destroy|terror|hostage|kidnap|riot|coup|overthrew|"
    r"overthrow|slaver|lynch|abuse|scandal|convict|prison|arrest|wound|injur|"
    r"casualt|victim|mauled|attack|assault|shelling|bombard|uprising|suppress|"
    r"\bcrisis\b|controvers|holocaust|segregat|desegregat|covid|virus|infect|"
    r"illness|disease|hospital|quarantin|outbreak|impeach|indict|resign)", re.I)

_SPORT = re.compile(
    r"\b(world series|super bowl|olympic\w*|baseball|football|basketball|hockey|"
    r"golf|tennis|boxing|nascar|kentucky derby|championship|pennant|home run|"
    r"homer|no-hitter|perfect game|nba|nfl|mlb|nhl|pga|u\.s\. open|world record|"
    r"gold medal|triple crown|heisman|heavyweight|pitcher|quarterback)\b", re.I)

_AG = re.compile(
    r"\b(farm\w*|ranch\w*|cattle|livestock|beef|corn|wheat|soybean\w*|harvest\w*|"
    r"agricultur\w*|homestead act|dust bowl|tractor|stockyard\w*|usda|"
    r"department of agriculture|grain|irrigation|rural)\b", re.I)

# "first" BUT NOT "first lady". That one matched a COVID diagnosis and offered
# it as a fun fact; the trailing negative lookahead is the whole fix.
_FIRST = re.compile(
    r"\b(first(?! lady| famil| gentleman)|becomes? the first|opened?|opens|"
    r"founded|establish\w*|dedicat\w*|"
    r"patent\w*|inaugurat\w*|invent\w*|debut\w*|premiere\w*|record)\b", re.I)

_US = re.compile(
    r"\b(united states|american|u\.s\.|\bus\b|nasa|congress|president|"
    r"washington|new york|california|texas|chicago|wyoming|iowa|kansas|"
    r"nebraska|missouri|oklahoma|colorado|montana|dakota|mississippi)\b", re.I)


def _get(url: str, timeout: int = 25) -> str:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def fetch_history_com(d: date) -> list:
    """
    (year, headline) from history.com's This Day in History.

    THE CLASS NAMES ARE BUILD-HASHED -- g1fwxflu, _15il2ffe -- and change on
    every deploy of theirs, so matching on them would break silently and
    without warning. The anchor is the year <span> paired with the heading's
    data-sentry-component attribute, which is framework-internal but survives
    a restyle. It WILL break eventually; candidates() says so out loud rather
    than returning an empty list that reads like a quiet day.

    robots.txt allows /this-day-in-history/ (only /private/ and /temp/ are
    disallowed), checked 2026-09-30.
    """
    html = _get(HISTORY_URL.format(month=_MONTHS[d.month - 1], day=d.day))
    pat = re.compile(
        r">(\d{4})\s*</span>.{0,400}?data-sentry-component=\"H3\">([^<]{6,160})</p>",
        re.S)
    out = []
    for year, title in pat.findall(html):
        out.append((int(year), re.sub(r"\s+", " ", title).strip()))
    return out


def fetch_wikipedia(d: date) -> list:
    """
    The same shape from Wikipedia's On This Day -- the fallback.

    Licensed for reuse and served by a real API, so it cannot break on a
    restyle. Rawer and grimmer than history.com, which is why it is second.
    """
    out = []
    for kind in ("selected", "events"):
        try:
            payload = json.loads(_get(WIKI_URL.format(kind=kind, mm=d.month, dd=d.day)))
        except Exception:
            continue
        for e in payload.get(kind) or []:
            text, year = (e.get("text") or "").strip(), e.get("year")
            if text and year:
                out.append((int(year), text))
    return out


def _tags(text: str) -> list:
    tags = []
    if _AG.search(text):
        tags.append("ag")
    if _SPORT.search(text):
        tags.append("sport")
    if _US.search(text):
        tags.append("US")
    if _FIRST.search(text):
        tags.append("first")
    return tags


def _keep(text: str, tags: list) -> bool:
    if _GRIM.search(text):
        return False
    # POSITIVELY, OR NOT AT ALL. "American" on its own admitted Khashoggi and
    # Mogadishu; "first" on its own admitted Opus Dei and a Vancouver
    # cathedral. Sport or agriculture stands alone; anything else needs to be
    # a US first.
    return bool(tags) and ("sport" in tags or "ag" in tags
                           or ("US" in tags and "first" in tags))


def candidates(when: date = None, limit: int = 8) -> dict:
    """
    {"items": [...], "errors": [...], "source_url": ...} for the pick list.

    Each item is {year, text, tags, source}. history.com first because it is
    better curated -- Babe Ruth's 60th homer, Cesar Chavez founding the
    National Farm Workers Association -- with Wikipedia behind it so a restyle
    degrades the panel rather than emptying it.
    """
    d = when or date.today()
    items, errors, seen = [], [], set()

    raw, source = [], "history.com"
    try:
        raw = fetch_history_com(d)
        if not raw:
            errors.append("history.com returned no events -- their page layout has "
                          "probably changed. Falling back to Wikipedia.")
    except Exception as e:                          # noqa: BLE001
        errors.append(f"history.com unreachable ({type(e).__name__}). "
                      "Falling back to Wikipedia.")

    if not raw:
        source = "Wikipedia"
        try:
            raw = fetch_wikipedia(d)
        except Exception as e:                      # noqa: BLE001
            errors.append(f"Wikipedia also unreachable ({type(e).__name__}).")

    for year, text in raw:
        # Dedupe on a stemmed prefix: the two feeds phrase the same event as
        # "NBC broadcast the first..." and "NBC broadcasts the first...".
        key = (year, " ".join(w.rstrip("s") for w in re.findall(r"[a-z]+", text.lower())[:8]))
        if key in seen:
            continue
        tags = _tags(text)
        if not _keep(text, tags):
            continue
        seen.add(key)
        weight = (3 if "ag" in tags else 0) + (2 if "sport" in tags else 0) \
            + (1 if "US" in tags else 0)
        items.append({"year": year, "text": text, "tags": tags,
                      "source": source, "_w": weight})

    items.sort(key=lambda i: (-i["_w"], -i["year"]))
    for i in items:
        i.pop("_w", None)
    return {"items": items[:limit], "errors": errors,
            "source_url": HISTORY_URL.format(month=_MONTHS[d.month - 1], day=d.day)}
