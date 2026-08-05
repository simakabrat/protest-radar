"""Source collectors. Every collector returns a list of raw item dicts:

    {source, source_type, title, summary, url, published, tier}
"""
import json
import logging
import re
import urllib.parse as up
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone

import feedparser
from bs4 import BeautifulSoup

from . import config, fetch

log = logging.getLogger("radar.sources")


def _clean(text: str, limit: int = 600) -> str:
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def _entry_time(entry):
    for key in ("published_parsed", "updated_parsed"):
        value = getattr(entry, key, None) or entry.get(key)
        if value:
            try:
                return datetime(*value[:6])
            except (TypeError, ValueError):
                pass
    return None


def _parse_feed(url: str, source_name: str, source_type: str, tier: str = "watch",
                max_items: int = 60) -> list:
    raw = fetch.get_text(url)
    if not raw:
        return []
    parsed = feedparser.parse(raw)
    items = []
    for entry in parsed.entries[:max_items]:
        published = _entry_time(entry)
        items.append({
            "source": source_name,
            "source_type": source_type,
            "title": _clean(entry.get("title", ""), 300),
            "summary": _clean(entry.get("summary", "") or entry.get("description", "")),
            "url": entry.get("link", "") or url,
            "published": published.isoformat() if published else None,
            "published_dt": published,
            "tier": tier,
        })
    return items


# ------------------------------------------------------------------ collectors
def collect_rss() -> list:
    items = []
    with ThreadPoolExecutor(max_workers=config.MAX_WORKERS) as pool:
        futures = {
            pool.submit(_parse_feed, src["url"], src["name"], "rss",
                        "core" if "Indybay" in src["name"] or "PauseAI" in src["name"]
                        else "watch"): src
            for src in config.RSS_SOURCES
        }
        for future in as_completed(futures):
            try:
                items.extend(future.result())
            except Exception as exc:  # one bad feed must not kill the run
                log.warning("rss collector failed for %s: %s",
                            futures[future]["name"], exc)
    return items


def collect_google_news() -> list:
    """Google News RSS search — the highest-yield discovery channel."""
    def one(query):
        url = ("https://news.google.com/rss/search?q="
               + up.quote(query + " when:14d")
               + "&hl=en-US&gl=US&ceid=US:en")
        return _parse_feed(url, f"Google News: {query}", "news_search",
                           "core", max_items=25)

    items = []
    with ThreadPoolExecutor(max_workers=config.MAX_WORKERS) as pool:
        for future in as_completed([pool.submit(one, q) for q in config.NEWS_QUERIES]):
            try:
                items.extend(future.result())
            except Exception as exc:
                log.warning("google news collector failed: %s", exc)
    return items


def collect_bing_news() -> list:
    def one(query):
        url = "https://www.bing.com/news/search?q=" + up.quote(query) + "&format=RSS"
        return _parse_feed(url, f"Bing News: {query}", "news_search", "watch",
                           max_items=20)

    items = []
    queries = config.NEWS_QUERIES[:10]
    with ThreadPoolExecutor(max_workers=4) as pool:
        for future in as_completed([pool.submit(one, q) for q in queries]):
            try:
                items.extend(future.result())
            except Exception as exc:
                log.warning("bing news collector failed: %s", exc)
    return items


def collect_gdelt() -> list:
    """GDELT global news index. Serialized — the API demands 5s spacing."""
    items = []
    for query in config.GDELT_QUERIES:
        url = ("https://api.gdeltproject.org/api/v2/doc/doc?query="
               + up.quote(query)
               + "&mode=artlist&maxrecords=60&format=json&timespan=14d&sort=datedesc")
        data = fetch.get_json(url)
        if not isinstance(data, dict):
            continue
        for article in data.get("articles", []):
            published = None
            seendate = article.get("seendate", "")
            try:
                published = datetime.strptime(seendate, "%Y%m%dT%H%M%SZ")
            except ValueError:
                pass
            items.append({
                "source": f"GDELT: {query[:40]}",
                "source_type": "gdelt",
                "title": _clean(article.get("title", ""), 300),
                "summary": _clean(article.get("domain", "") + " — "
                                  + article.get("sourcecountry", "")),
                "url": article.get("url", ""),
                "published": published.isoformat() if published else None,
                "published_dt": published,
                "tier": "core",
            })
    return items


def collect_reddit() -> list:
    """Reddit via .rss search endpoints (the JSON API blocks non-browser clients)."""
    def search(query):
        url = ("https://www.reddit.com/search.rss?q=" + up.quote(query)
               + "&sort=new&t=month")
        return _parse_feed(url, f"Reddit search: {query}", "reddit", "watch", 25)

    def sub(name):
        url = f"https://www.reddit.com/r/{name}/new.rss?limit=40"
        return _parse_feed(url, f"r/{name}", "reddit", "watch", 40)

    items = []
    # Reddit rate-limits aggressively per IP, so these run serially behind the
    # 7s per-host throttle rather than in parallel.
    for fn, arg in ([(search, q) for q in config.REDDIT_QUERIES]
                    + [(sub, s) for s in config.REDDIT_SUBS]):
        try:
            items.extend(fn(arg))
        except Exception as exc:
            log.warning("reddit collector failed for %r: %s", arg, exc)
    return items


def collect_bluesky() -> list:
    """Bluesky public full-text search (api.bsky.app, unauthenticated)."""
    items = []
    for query in config.BLUESKY_QUERIES:
        url = ("https://api.bsky.app/xrpc/app.bsky.feed.searchPosts?q="
               + up.quote(query) + "&limit=40&sort=latest")
        data = fetch.get_json(url)
        if not isinstance(data, dict):
            continue
        for post in data.get("posts", []):
            record = post.get("record", {}) or {}
            text = record.get("text", "")
            author = (post.get("author", {}) or {}).get("handle", "")
            published = None
            try:
                published = datetime.fromisoformat(
                    record.get("createdAt", "").replace("Z", "+00:00")
                ).replace(tzinfo=None)
            except (ValueError, AttributeError):
                pass
            rkey = (post.get("uri", "") or "").rsplit("/", 1)[-1]
            items.append({
                "source": f"Bluesky: {query}",
                "source_type": "bluesky",
                "title": _clean(text, 200),
                "summary": _clean(text),
                "url": f"https://bsky.app/profile/{author}/post/{rkey}" if rkey else "",
                "published": published.isoformat() if published else None,
                "published_dt": published,
                "tier": "watch",
            })
    return items


def collect_mobilize() -> list:
    """Mobilize.us public events API, filtered client-side to AI-relevant events."""
    items = []
    cutoff = datetime.now(timezone.utc) + timedelta(days=120)
    for query in config.MOBILIZE_QUERIES:
        url = ("https://api.mobilize.us/v1/events?per_page=100&q=" + up.quote(query)
               + "&timeslot_start=gte_now")
        data = fetch.get_json(url)
        if not isinstance(data, dict):
            continue
        for event in data.get("data", []):
            blob = " ".join(filter(None, [event.get("title", ""),
                                          event.get("summary", ""),
                                          event.get("description", "")])).lower()
            # Mobilize ignores `q`, so gate locally on AI vocabulary.
            if not any(term in blob for term in
                       ("artificial intelligence", " ai ", "ai-", "openai",
                        "anthropic", "data center", "datacenter", "automation",
                        "algorithm")):
                continue
            location = event.get("location") or {}
            venue = " ".join(filter(None, [
                location.get("venue", ""),
                (location.get("address_lines") or [""])[0],
                location.get("locality", ""), location.get("region", "")]))
            start = None
            slots = event.get("timeslots") or []
            if slots:
                try:
                    start = datetime.fromtimestamp(slots[0]["start_date"], timezone.utc)
                except (KeyError, TypeError, ValueError):
                    pass
            if start and start > cutoff:
                continue
            items.append({
                "source": "Mobilize.us",
                "source_type": "event_platform",
                "title": _clean(event.get("title", ""), 300),
                "summary": _clean(f"{event.get('summary', '')} {venue} "
                                  f"{event.get('description', '')}"),
                "url": event.get("browser_url", ""),
                "published": start.isoformat() if start else None,
                "published_dt": start.replace(tzinfo=None) if start else None,
                "tier": "core",
            })
    return items


# ------------------------------------------------------------------- HTML scrape
_LINK_NOISE = re.compile(
    r"^(home|about|contact|donate|login|sign in|sign up|menu|search|privacy|terms|"
    r"subscribe|newsletter|share|more|next|previous|read more|skip to)",
    re.I)


def _scrape_page(src: dict) -> list:
    """Pull headline-ish text and links from an arbitrary HTML page."""
    html = fetch.get_text(src["url"])
    if not html:
        return []
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    base = src["url"]
    items = []
    seen = set()

    # 1. Structured event data (JSON-LD) — the richest signal when present.
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            payload = json.loads(tag.string or "{}")
        except (ValueError, TypeError):
            continue
        for node in (payload if isinstance(payload, list) else [payload]):
            if not isinstance(node, dict):
                continue
            if "Event" not in str(node.get("@type", "")):
                continue
            location = node.get("location") or {}
            place = location.get("name", "") if isinstance(location, dict) else str(location)
            node_url = node.get("url", "") or base
            items.append({
                "source": src["name"], "source_type": "html_event",
                "title": _clean(str(node.get("name", "")), 300),
                "summary": _clean(f"{node.get('description', '')} {place} "
                                  f"{node.get('startDate', '')}"),
                "url": node_url,
                "published": None, "published_dt": None,
                "tier": src.get("tier", "watch"),
                "url_is_direct": node_url.rstrip("/") != base.rstrip("/"),
            })

    # 2. Headings and links, each paired with nearby context text.
    for tag in soup.find_all(["h1", "h2", "h3", "h4", "a"]):
        title = _clean(tag.get_text(" "), 250)
        if len(title) < 12 or _LINK_NOISE.match(title):
            continue
        href = tag.get("href") if tag.name == "a" else None
        if not href:
            link = tag.find("a", href=True)
            href = link["href"] if link else None
        # A heading with no link of its own falls back to the page it was found
        # on. That page is a listing (e.g. /protests), not the protest itself,
        # so flag it — the UI must not present it as a direct link.
        if not href:
            parent_link = tag.find_parent("a", href=True)
            href = parent_link["href"] if parent_link else None
        url = up.urljoin(base, href) if href else base
        direct = bool(href) and url.rstrip("/") != base.rstrip("/")
        key = (title.lower(), url)
        if key in seen:
            continue
        seen.add(key)
        context = ""
        parent = tag.find_parent(["article", "li", "div", "section"])
        if parent:
            context = _clean(parent.get_text(" "), 400)
        items.append({
            "source": src["name"], "source_type": "html",
            "title": title, "summary": context, "url": url,
            "published": None, "published_dt": None,
            "tier": src.get("tier", "watch"),
            "url_is_direct": direct,
        })
    return items[:250]


def collect_sites() -> list:
    items = []
    targets = config.SITE_SOURCES + config.EVENT_SEARCH_URLS
    with ThreadPoolExecutor(max_workers=config.MAX_WORKERS) as pool:
        futures = {pool.submit(_scrape_page, src): src for src in targets}
        for future in as_completed(futures):
            try:
                items.extend(future.result())
            except Exception as exc:
                log.warning("site scrape failed for %s: %s",
                            futures[future]["name"], exc)
    return items


COLLECTORS = [
    ("google_news", collect_google_news),
    ("rss", collect_rss),
    ("sites", collect_sites),
    ("reddit", collect_reddit),
    ("bluesky", collect_bluesky),
    ("gdelt", collect_gdelt),
    ("bing_news", collect_bing_news),
    ("mobilize", collect_mobilize),
]


def collect_all() -> tuple:
    """Run every collector. Returns (items, per-source stats)."""
    all_items, stats = [], {}
    for name, collector in COLLECTORS:
        try:
            found = collector()
            stats[name] = len(found)
            all_items.extend(found)
            log.info("collector %s -> %d items", name, len(found))
        except Exception as exc:
            stats[name] = -1
            log.error("collector %s crashed: %s", name, exc)
    return all_items, stats
