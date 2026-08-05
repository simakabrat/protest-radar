"""Signal classification: decide whether an item is an anti-AI protest lead.

Scoring is additive and capped at 100:

  high-signal phrase       +45   "ai protest", "rally against ai", ...
  AI subject terms         +20   openai, agi, artificial intelligence, ...
  protest action terms     +25   march, picket, walkout, rally, ...
  anti-AI stance terms     +15   pauseai, moratorium, shut it down, ...
  AI/protest proximity     +15   the two appear within 120 chars
  geography                +25   SF/Bay or LA; +12 elsewhere in US; -30 foreign
  future dated event       +18   a parseable date in the next 120 days
  core source tier         +10   dedicated anti-AI org or protest wire
  concrete logistics       +12   street address, "meet at", time of day
  negative/noise terms     -30   stock, webinar, "best AI tools", ...

>= CONFIRM_THRESHOLD (70) -> CONFIRMED, fires the SMS burst.
>= SIGNAL_THRESHOLD  (30) -> SIGNAL, shown on the dashboard.
"""
import re
from datetime import datetime, timedelta

from dateutil import parser as dateparser

from . import config

_WORD_CACHE: dict = {}


def _norm(text: str) -> str:
    text = (text or "").lower()
    text = re.sub(r"\s+", " ", text)
    return text


def _find_terms(text: str, terms) -> list:
    """Return terms present in text, matching on word boundaries where sensible."""
    hits = []
    for term in terms:
        pattern = _WORD_CACHE.get(term)
        if pattern is None:
            if term.strip().isalnum() and len(term.strip()) <= 4:
                pattern = re.compile(r"\b" + re.escape(term.strip()) + r"\b")
            else:
                pattern = re.compile(re.escape(term))
            _WORD_CACHE[term] = pattern
        if pattern.search(text):
            hits.append(term)
    return hits


def _proximity(text: str, group_a, group_b, window: int = 120) -> bool:
    """True if any term from A appears within `window` chars of any term from B."""
    pos_a = [m.start() for t in group_a for m in re.finditer(re.escape(t), text)]
    pos_b = [m.start() for t in group_b for m in re.finditer(re.escape(t), text)]
    return any(abs(a - b) <= window for a in pos_a[:40] for b in pos_b[:40])


# --------------------------------------------------------------- date parsing
_DATE_PATTERNS = [
    r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+\d{1,2}(?:st|nd|rd|th)?(?:,?\s+\d{4})?\b",
    r"\b\d{1,2}\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?(?:,?\s+\d{4})?\b",
    r"\b\d{4}-\d{2}-\d{2}\b",
    r"\b\d{1,2}/\d{1,2}/\d{2,4}\b",
]
_YEAR_RE = re.compile(r"\b20[23]\d\b")
_WEEKDAY_RE = re.compile(
    r"\b(this|next|coming)\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b")
_TIME_RE = re.compile(r"\b(1[0-2]|0?[1-9])(:[0-5]\d)?\s*(am|pm)\b")
_ADDRESS_RE = re.compile(
    r"\b\d{2,5}\s+[A-Za-z][A-Za-z.'\- ]{2,30}\b"
    r"(street|st\.|avenue|ave\.|ave\b|blvd|boulevard|road|rd\.|drive|dr\.|way|plaza|square|park)\b",
    re.I)
_MEET_RE = re.compile(r"\b(meet (?:at|up|outside)|gather (?:at|outside)|assemble at|"
                      r"starts? at|kick(?:s|ing)? off at|rsvp|join us (?:at|on|outside))\b")


def extract_event_date(text: str, published: datetime = None):
    """Best-effort extraction of a future event date. Returns (iso_date, is_future)."""
    now = datetime.utcnow()
    horizon = now + timedelta(days=365)
    candidates = []
    for pattern in _DATE_PATTERNS:
        for match in re.finditer(pattern, text, re.I):
            raw = match.group(0)
            try:
                parsed = dateparser.parse(raw, fuzzy=False,
                                          default=published or now)
            except (ValueError, OverflowError, TypeError):
                continue
            if parsed and now - timedelta(days=45) <= parsed <= horizon:
                candidates.append(parsed)
    weekday = _WEEKDAY_RE.search(text)
    if weekday and not candidates:
        try:
            parsed = dateparser.parse(weekday.group(2), default=published or now)
            if parsed and parsed < now:
                parsed += timedelta(days=7)
            if parsed:
                candidates.append(parsed)
        except (ValueError, OverflowError, TypeError):
            pass
    if not candidates:
        return None, False
    future = [c for c in candidates if c >= now - timedelta(hours=12)]
    # A bare month-day ("Oct 7") carries no year, so dateutil stamps the
    # current one and a historical reference becomes a future event date.
    # Trust those only inside a 120-day window, where an organiser plausibly
    # means the upcoming occurrence.
    if future and not _YEAR_RE.search(text):
        future = [c for c in future if c <= now + timedelta(days=120)]
    if not future:
        return (max(candidates).date().isoformat(), False) if candidates else (None, False)
    return min(future).date().isoformat(), True


_TIME_EXTRACT_RE = re.compile(
    r"\b(1[0-2]|0?[1-9])(?::([0-5]\d))?\s*([ap])\.?m\.?\b", re.I)
_NOON_RE = re.compile(r"\b(noon|midday|midnight)\b", re.I)


def extract_event_time(text: str):
    """Pull a human-readable start time ("5:30 PM") out of the text, if present."""
    match = _TIME_EXTRACT_RE.search(text or "")
    if match:
        hour, minute, meridiem = match.groups()
        return f"{int(hour)}:{minute or '00'} {meridiem.upper()}M"
    word = _NOON_RE.search(text or "")
    if word:
        return {"noon": "12:00 PM", "midday": "12:00 PM",
                "midnight": "12:00 AM"}[word.group(1).lower()]
    return None


# ------------------------------------------------------------- tense / timing
# Language that means the protest has NOT happened yet — this is what we alert on.
_PROSPECTIVE_RE = [
    re.compile(r"\b(will|gonna|going to|plans? to|planning to|set to|scheduled to|"
               r"expected to|due to|about to)\s+\w{0,12}\s*"
               r"(protest|march|rally|gather|demonstrat|picket|walk ?out|strike|"
               r"blockade|occupy|shut down)"),
    re.compile(r"\b(join us|join me|rsvp|sign up|save the date|come out|show up|"
               r"meet us|be there|spread the word|invite|register now|"
               r"bring your friends|see you there)\b"),
    re.compile(r"\b(upcoming|this (sat|sun|mon|tues|wednes|thurs|fri)day|"
               r"next (week|month|sat|sun|mon|tues|wednes|thurs|fri)day|"
               r"tomorrow|tonight|in \d{1,2} days)\b"),
    re.compile(r"\b(announc\w+|calling for|call to action|organi[sz]ing|mobili[sz]ing|"
               r"planning|prepar\w+ for)\s+(a |an |the |another )?"
               r"(protest|march|rally|demonstration|walk ?out|strike|action)"),
    re.compile(r"\bwe(?:'re| are|)\s*(protesting|marching|rallying|gathering|"
               r"walking out|taking to the streets)\b"),
    re.compile(r"\b(protest|march|rally|demonstration|action)\s+(on|this|next)\s+"
               r"(mon|tues|wednes|thurs|fri|satur|sun)day\b"),
]

# Language that means it already happened — newsworthy, but not alert-worthy.
_RETROSPECTIVE_RE = [
    re.compile(r"\b(protested|marched|rallied|picketed|demonstrated|walked out|"
               r"took to the streets|staged a|held a|gathered outside|"
               r"turned out for)\b"),
    re.compile(r"\b(hundreds|dozens|thousands|scores)\s+(of\s+)?\w{0,12}\s*"
               r"(protested|marched|gathered|rallied|descended|turned out)\b"),
    re.compile(r"\b(was|were|had been)\s+(held|staged|organi[sz]ed|attended)\b"),
    re.compile(r"\b(last|this past|previous)\s+(week|month|weekend|night|"
               r"mon|tues|wednes|thurs|fri|satur|sun)\w*\b"),
    re.compile(r"\b(yesterday|recap|aftermath|photos? from|footage from|"
               r"here's what happened|report ?back)\b"),
]


def detect_temporality(text: str, event_date: str = None, is_future: bool = False):
    """Return 'upcoming' | 'past' | 'unknown' — is the protest ahead of us or behind?"""
    prospective = sum(1 for pattern in _PROSPECTIVE_RE if pattern.search(text))
    retrospective = sum(1 for pattern in _RETROSPECTIVE_RE if pattern.search(text))
    if event_date and is_future and retrospective <= prospective:
        return "upcoming"
    if prospective > retrospective:
        return "upcoming"
    if retrospective > prospective:
        return "past"
    return "unknown"


def detect_geo(text: str):
    """Return (region_key, label) — 'sf_bay' | 'la' | 'us' | 'foreign' | 'unknown'."""
    for key, terms in config.PRIORITY_GEO.items():
        hits = _find_terms(text, terms)
        if hits:
            return key, hits[0].strip()
    if _find_terms(text, config.US_GEO):
        return "us", _find_terms(text, config.US_GEO)[0].strip()
    if _find_terms(text, config.FOREIGN_GEO):
        return "foreign", _find_terms(text, config.FOREIGN_GEO)[0].strip()
    return "unknown", ""


# Scraped pages yield navigation chrome and listing-page boilerplate, not events.
_JUNK_TITLE_RE = re.compile(
    r"^(site navigation|main navigation|skip to|menu|footer|header|breadcrumb|"
    r"cookie|newsletter sign|follow us|share this|related (posts|articles)|"
    r"load more|view all|see all events|all rights reserved)\b"
    r"|events and things to do in"
    r"|^\s*(home|news|events|about|contact|search|blog|donate)\s*$",
    re.I)


def is_junk(item: dict) -> bool:
    title = (item.get("title") or "").strip()
    return bool(_JUNK_TITLE_RE.search(title)) or len(title) < 12


# Section/landing pages an organisation publishes for *all* its protests.
_LISTING_SLUGS = {
    "protests", "protest", "events", "event", "calendar", "actions", "action",
    "news", "blog", "posts", "updates", "take-action", "get-involved",
    "upcoming", "campaigns", "press", "media", "home", "index",
}


def looks_like_listing(url: str) -> bool:
    """True when a URL is a section index rather than one specific item.

    Independent of how the URL was collected, so it also catches rows whose
    provenance flag is missing or was defaulted. An article/post URL carries an
    identifying slug or id; /protests carries none.
    """
    if not url:
        return True
    path = re.sub(r"[?#].*$", "", url.split("://")[-1])
    parts = [p for p in path.split("/")[1:] if p]
    if not parts:
        return True                      # bare domain
    last = parts[-1].lower()
    if len(parts) >= 3:
        return False                     # deep path: an item
    if any(ch.isdigit() for ch in last):
        return False                     # ids and dates mean an item
    if last in _LISTING_SLUGS:
        return True
    if len(parts) == 1 and len(last) < 20 and last.count("-") < 2:
        return True                      # short single segment: a section
    return False


_URL_YEAR_RE = re.compile(r"/(?:.*?[-_/])?(20[12]\d)[-_/]")


def url_signals(url: str):
    """Extract (archive_year, slug_text) from a URL.

    URLs are used for *geography and dating* only, never for protest/AI keyword
    matching — a listing URL like /d/ca--san-francisco/ai-protest/ would
    otherwise stamp its own search terms onto every item scraped from it.
    """
    year = None
    match = _URL_YEAR_RE.search(url or "")
    if match:
        candidate = int(match.group(1))
        if 2015 <= candidate <= datetime.utcnow().year + 1:
            year = candidate
    slug = re.sub(r"[^a-z]+", " ", (url or "").lower())
    return year, slug


def _staleness(item: dict, event_date: str, is_future: bool):
    """Return (is_stale, age_days). Old coverage must never fire an alert."""
    today = datetime.utcnow().date()
    # An archive URL (/2023-june-london) is authoritative about its own age.
    archive_year, _ = url_signals(item.get("url", ""))
    if archive_year and archive_year < today.year:
        return (True, (today.year - archive_year) * 365)
    if event_date:
        try:
            parsed = datetime.fromisoformat(event_date).date()
            return (parsed < today, (today - parsed).days)
        except ValueError:
            pass
    published = item.get("published_dt")
    if isinstance(published, datetime):
        age = (datetime.utcnow() - published).days
        return (age > 7, age)
    return (False, None)  # unknown age — neither fresh nor provably stale


def score_item(item: dict) -> dict:
    """Score one raw item in place. Returns the enriched item."""
    # The source URL is deliberately excluded: search-listing URLs such as
    # /d/ca--san-francisco/ai-protest/ would inject their query terms into
    # every item scraped from that page.
    blob = _norm(" ".join(filter(None, [
        item.get("title", ""), item.get("summary", "")])))

    high = _find_terms(blob, config.HIGH_SIGNAL_PHRASES)
    ai_hits = _find_terms(blob, config.AI_TERMS)
    protest_hits = _find_terms(blob, config.PROTEST_TERMS)
    stance_hits = _find_terms(blob, config.STANCE_TERMS)
    negative_hits = _find_terms(blob, config.NEGATIVE_TERMS)

    score = 0
    reasons = []

    if high:
        score += 45
        reasons.append(f"high-signal phrase: {', '.join(high[:3])}")
    if ai_hits:
        score += min(20, 7 * len(ai_hits))
        reasons.append(f"AI subject: {', '.join(ai_hits[:4])}")
    if protest_hits:
        score += min(25, 9 * len(protest_hits))
        reasons.append(f"protest action: {', '.join(protest_hits[:4])}")
    if stance_hits:
        score += min(15, 8 * len(stance_hits))
        reasons.append(f"anti-AI stance: {', '.join(stance_hits[:3])}")
    if ai_hits and protest_hits and _proximity(blob, ai_hits, protest_hits):
        score += 15
        reasons.append("AI and protest terms in close proximity")

    # Geography may come from the URL slug too (/2023-november-uk -> foreign).
    _, url_slug = url_signals(item.get("url", ""))
    region, place = detect_geo(blob)
    if region == "unknown":
        region, place = detect_geo(url_slug)
    if region in ("sf_bay", "la"):
        score += 25
        reasons.append(f"priority geography: {place}")
    elif region == "us":
        score += 12
        reasons.append(f"US geography: {place}")
    elif region == "foreign":
        score -= 30
        reasons.append(f"non-US location: {place}")

    published = item.get("published_dt")
    event_date, is_future = extract_event_date(blob, published)
    if event_date and is_future:
        score += 18
        reasons.append(f"upcoming date detected: {event_date}")
    elif event_date:
        score += 3

    if item.get("tier") == "core":
        score += 10
        reasons.append("core anti-AI / protest-wire source")

    logistics = bool(_ADDRESS_RE.search(blob)) or bool(_MEET_RE.search(blob)) \
        or bool(_TIME_RE.search(blob))
    if logistics and protest_hits:
        score += 12
        reasons.append("concrete logistics (address / meet-up time)")

    if negative_hits:
        penalty = min(30, 15 * len(negative_hits))
        score -= penalty
        reasons.append(f"noise terms: {', '.join(negative_hits[:3])}")

    # Hard gate: an item with no protest verb at all is never a protest lead.
    if not protest_hits and not high:
        score = min(score, 15)
    # Hard gate: no AI subject means it is some other protest entirely.
    if not ai_hits and not high and not stance_hits:
        score = min(score, 10)

    temporality = detect_temporality(blob, event_date, is_future)
    if temporality == "upcoming":
        score += 12
        reasons.append("forward-looking language (protest has not happened yet)")
    elif temporality == "past":
        score -= 18
        reasons.append("retrospective coverage (protest already happened)")

    stale, age_days = _staleness(item, event_date, is_future)
    if stale:
        score -= 20
        reasons.append(f"stale ({age_days}d old) — already happened")

    score = max(0, min(100, score))

    # CONFIRMED is the only status that fires the phone burst, so it is gated
    # hard: high score, forward-looking, US-based, fresh, and not page chrome.
    junk = is_junk(item)
    # A genuine announcement names the action in its headline. Requiring that
    # rejects commentary where "protest" only appears deep in quoted body text
    # — e.g. a geopolitics post whose linked video description mentions one.
    title_norm = _norm(item.get("title", ""))
    title_has_action = bool(_find_terms(title_norm, config.PROTEST_TERMS)
                            or _find_terms(title_norm, config.HIGH_SIGNAL_PHRASES))
    alertable = (
        score >= config.CONFIRM_THRESHOLD
        and temporality == "upcoming"
        and not stale
        # A positive US geography match is required — "unknown" is not good
        # enough to wake someone with ten texts.
        and region in ("sf_bay", "la", "us")
        and not junk
        and title_has_action
    )
    if junk:
        status = "NOISE"
    elif alertable:
        status = "CONFIRMED"
    elif score >= config.CONFIRM_THRESHOLD:
        # Real protest coverage, but historical, foreign, or undated: worth
        # showing on the dashboard, not worth ten urgent texts.
        status = "REPORTED"
    elif score >= config.SIGNAL_THRESHOLD:
        status = "SIGNAL"
    else:
        status = "NOISE"

    item.update({
        "score": score,
        "status": status,
        "temporality": temporality,
        "event_time": extract_event_time(blob),
        "url_is_direct": bool(item.get("url_is_direct", True)),
        "region": region,
        "place": place,
        "event_date": event_date,
        "is_future": is_future,
        "stale": stale,
        "age_days": age_days,
        "reasons": reasons,
        "matched_terms": {
            "high": high, "ai": ai_hits[:6], "protest": protest_hits[:6],
            "stance": stance_hits[:4],
        },
    })
    return item
