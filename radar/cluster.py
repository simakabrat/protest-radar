"""Group individual items into distinct real-world protest events.

One protest generates dozens of articles and posts. Alerting is event-level:
the phone burst fires once per *event*, not once per article.

Clustering key = (region, event_date-or-week, dominant target org) with a
token-overlap merge pass to catch retellings that use different wording.
"""
import re
from collections import defaultdict
from datetime import datetime

from .score import looks_like_listing

_STOPWORDS = set("""
a an the and or of for to in on at by with from as is are was were be been being
this that these those it its his her their our your my you we they he she i
new said says say just now here there what how why when who which than then
""".split())

# Named targets let us separate "protest at OpenAI" from "protest at a data center".
_TARGETS = [
    ("openai", ["openai", "open ai", "sam altman"]),
    ("anthropic", ["anthropic", "claude"]),
    ("google", ["google", "deepmind", "gemini"]),
    ("meta", ["meta ai", "facebook", "zuckerberg"]),
    ("xai", ["xai", "x.ai", "grok", "musk"]),
    ("nvidia", ["nvidia"]),
    ("waymo", ["waymo", "robotaxi", "cruise", "driverless"]),
    ("datacenter", ["data center", "datacenter", "data centre"]),
    ("capitol", ["capitol", "congress", "senate", "white house", "legislature"]),
    ("studio", ["studio", "sag-aftra", "wga", "hollywood", "voice actor"]),
]


def _tokens(text: str) -> set:
    words = re.findall(r"[a-z0-9']{3,}", (text or "").lower())
    return {w for w in words if w not in _STOPWORDS}


def _target(text: str) -> str:
    low = (text or "").lower()
    for name, terms in _TARGETS:
        if any(term in low for term in terms):
            return name
    return "general"


def _time_bucket(item: dict) -> str:
    """Bucket by event date when known.

    Undated coverage all lands in one bucket on purpose: the same protest is
    reported by outlets over several days, and bucketing those by publication
    week would split one real event into several.
    """
    if item.get("event_date"):
        return f"d:{item['event_date']}"
    return "undated"


def _similar(a: set, b: set, threshold: float = 0.30) -> bool:
    """Containment similarity — robust to headlines of very different lengths."""
    if not a or not b:
        return False
    overlap = len(a & b)
    if overlap >= 4:  # four shared content words is a strong retelling signal
        return True
    return overlap / min(len(a), len(b)) >= threshold


def cluster_items(items: list) -> list:
    """Return a list of event dicts, each holding its member items."""
    buckets = defaultdict(list)
    for item in items:
        blob = f"{item.get('title', '')} {item.get('summary', '')}"
        key = (item.get("region", "unknown"), _time_bucket(item), _target(blob))
        buckets[key].append(item)

    events = []
    for (region, bucket, target), members in buckets.items():
        # Second pass: split a bucket into sub-clusters by title similarity.
        groups = []
        for item in sorted(members, key=lambda m: -m.get("score", 0)):
            tokens = _tokens(item.get("title", ""))
            for group in groups:
                if _similar(tokens, group["tokens"]):
                    group["members"].append(item)
                    group["tokens"] |= tokens
                    break
            else:
                groups.append({"tokens": tokens, "members": [item]})

        for group in groups:
            group_members = group["members"]
            lead = max(group_members, key=lambda m: m.get("score", 0))
            dates = [m["event_date"] for m in group_members if m.get("event_date")]
            times = [m["event_time"] for m in group_members if m.get("event_time")]
            upcoming = [m for m in group_members
                        if m.get("temporality") == "upcoming"]

            # Prefer a link that points at the protest itself over one that
            # merely points at the listing page it was scraped from.
            def is_direct(member):
                url = member.get("url") or ""
                return bool(member.get("url_is_direct", True)) and \
                    not looks_like_listing(url)

            ranked = sorted(group_members,
                            key=lambda m: (is_direct(m), m.get("score", 0)),
                            reverse=True)
            best = next((m for m in ranked if m.get("url")), lead)

            # Every distinct link behind this event, so the card can show them all.
            links, seen_urls = [], set()
            for member in ranked:
                url = (member.get("url") or "").strip()
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)
                links.append({
                    "url": url,
                    "source": member.get("source", ""),
                    "title": member.get("title", "")[:120],
                    "direct": is_direct(member),
                })
            events.append({
                "event_key": f"{region}|{bucket}|{target}|"
                             f"{sorted(group['tokens'])[:4]}",
                "title": lead.get("title", ""),
                "url": best.get("url", "") or lead.get("url", ""),
                "url_is_direct": is_direct(best),
                "links": links[:8],
                "score": lead.get("score", 0),
                "status": lead.get("status", ""),
                "region": region,
                "place": lead.get("place", ""),
                "target": target,
                "event_date": min(dates) if dates else None,
                "event_time": times[0] if times else None,
                "temporality": ("upcoming" if upcoming else
                                lead.get("temporality", "unknown")),
                "source_count": len(group_members),
                "sources": sorted({m.get("source", "") for m in group_members})[:12],
                "reasons": lead.get("reasons", []),
                "members": [m["fingerprint"] for m in group_members],
                "lead_fingerprint": lead["fingerprint"],
            })

    events.sort(key=lambda e: (-e["score"], -e["source_count"]))
    return events
