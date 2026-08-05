"""Urgent alerting: sends a burst of messages when a protest is CONFIRMED.

Two backends, tried in order:
  1. Twilio  — real SMS. Used when TWILIO_* env vars are set.
  2. iMessage — macOS Messages.app via AppleScript. No account needed.

Every send is logged to data/alerts.log so a burst is always auditable.
"""
import json
import logging
import subprocess
import time
from datetime import datetime

from . import config

log = logging.getLogger("radar.alert")


def _log_alert(line: str) -> None:
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(config.DATA_DIR / "alerts.log", "a") as handle:
        handle.write(f"{datetime.utcnow().isoformat()}Z {line}\n")


_REGION_LABEL = {"sf_bay": "SF / Bay Area", "la": "Los Angeles",
                 "us": "United States", "foreign": "outside US",
                 "unknown": "location unknown"}


def compose_daily(events: list, index: int, total: int) -> str:
    """The message sent when the day's verdict is 1.

    Leads with the strongest event, notes how many others there are, and always
    carries the dashboard link so the full picture is one tap away.
    """
    lead = events[0]
    when = lead.get("event_date") or "date TBD"
    where = lead.get("place") or _REGION_LABEL.get(lead.get("region", ""), "US")
    extra = len(events) - 1
    site = config.SITE_URL or "(dashboard URL not configured)"
    return (
        f"[{index}/{total}] ANTI-AI PROTEST NEWS TODAY\n"
        f"{lead.get('title', '')[:130]}\n"
        f"When: {when} | Where: {where}\n"
        f"Confidence: {lead.get('score')}/100"
        + (f"\n+{extra} more lead{'s' if extra > 1 else ''} today" if extra > 0 else "")
        + f"\nAll details: {site}"
    )


def compose(item: dict, index: int, total: int) -> str:
    when = item.get("event_date") or "date TBD"
    where = item.get("place") or _REGION_LABEL.get(item.get("region", ""), "US")

    # Events store a JSON list in `sources`; raw items store a single `source`.
    sources = item.get("sources") or item.get("source") or ""
    if isinstance(sources, str) and sources.startswith("["):
        try:
            sources = json.loads(sources)
        except ValueError:
            pass
    if isinstance(sources, (list, tuple)):
        label = ", ".join(str(s) for s in sources[:2])
        if len(sources) > 2:
            label += f" +{len(sources) - 2} more"
    else:
        label = str(sources)

    return (
        f"[{index}/{total}] URGENT — ANTI-AI PROTEST CONFIRMED\n"
        f"{item.get('title', '')[:140]}\n"
        f"When: {when} | Where: {where}\n"
        f"Confidence: {item.get('score')}/100\n"
        f"Seen via: {label[:70] or 'radar scan'}\n"
        f"{item.get('url', '')}"
    )


# ------------------------------------------------------------------- backends
def _send_twilio(to: str, body: str) -> bool:
    import requests
    url = (f"https://api.twilio.com/2010-04-01/Accounts/"
           f"{config.TWILIO_SID}/Messages.json")
    try:
        resp = requests.post(
            url, auth=(config.TWILIO_SID, config.TWILIO_TOKEN),
            data={"From": config.TWILIO_FROM, "To": to, "Body": body}, timeout=20)
        if resp.status_code in (200, 201):
            return True
        log.error("twilio send failed %s: %s", resp.status_code, resp.text[:200])
    except Exception as exc:
        log.error("twilio send errored: %s", exc)
    return False


def _send_imessage(to: str, body: str) -> bool:
    """Send via Messages.app. Falls back from iMessage to SMS if unavailable."""
    script = f'''
    on run
        set targetNumber to "{to}"
        set msg to {_applescript_string(body)}
        tell application "Messages"
            try
                set svc to 1st account whose service type = iMessage
                set target to participant targetNumber of svc
                send msg to target
                return "ok-imessage"
            on error
                try
                    set svc to 1st account whose service type = SMS
                    set target to participant targetNumber of svc
                    send msg to target
                    return "ok-sms"
                on error errMsg
                    return "fail: " & errMsg
                end try
            end try
        end tell
    end run
    '''
    try:
        result = subprocess.run(["osascript", "-e", script],
                                capture_output=True, text=True, timeout=45)
        output = (result.stdout or "").strip()
        if output.startswith("ok"):
            return True
        log.error("imessage send failed: %s %s", output, (result.stderr or "")[:200])
    except Exception as exc:
        log.error("imessage send errored: %s", exc)
    return False


def _applescript_string(text: str) -> str:
    """Encode a Python string as an AppleScript string literal."""
    escaped = text.replace("\\", "\\\\").replace('"', '\\"')
    parts = escaped.split("\n")
    return " & return & ".join(f'"{part}"' for part in parts)


def _send_ntfy(body: str, title: str = None) -> bool:
    """Push via ntfy.sh. No account needed; the topic itself is the secret."""
    import requests
    url = f"{config.NTFY_SERVER.rstrip('/')}/{config.NTFY_TOPIC}"
    headers = {
        "Title": (title or "Anti-AI Protest Radar")[:200],
        "Priority": "urgent",
        "Tags": "rotating_light",
    }
    if config.SITE_URL:
        headers["Click"] = config.SITE_URL
    try:
        resp = requests.post(url, data=body.encode("utf-8"),
                             headers=headers, timeout=20)
        if resp.status_code in (200, 201):
            return True
        log.error("ntfy send failed %s: %s", resp.status_code, resp.text[:200])
    except Exception as exc:
        log.error("ntfy send errored: %s", exc)
    return False


def active_backends() -> list:
    """Every delivery channel currently configured, in priority order."""
    backends = []
    if config.TWILIO_SID and config.TWILIO_TOKEN and config.TWILIO_FROM:
        backends.append("twilio")
    if config.NTFY_TOPIC:
        backends.append("ntfy")
    if config.IMESSAGE_ENABLED:
        backends.append("imessage")
    return backends


def backend_name() -> str:
    """Human-readable summary of the delivery channels, for the dashboard."""
    backends = active_backends()
    return " + ".join(backends) if backends else "NONE CONFIGURED"


def send_one(body: str, to: str = None, dry_run: bool = False,
             title: str = None) -> bool:
    """Deliver one message. Succeeds if *any* configured channel accepts it.

    Every channel is attempted rather than stopping at the first success, so a
    silently broken one never masks the others.
    """
    to = to or config.ALERT_PHONE
    backends = active_backends()

    if not backends:
        log.error("no delivery channel configured — message NOT sent")
        _log_alert(f"NO-BACKEND (dropped): {body[:120]!r}")
        return False

    if dry_run:
        _log_alert(f"DRY-RUN via {'+'.join(backends)} to {to}: {body[:120]!r}")
        log.info("[dry-run] would send via %s", "+".join(backends))
        return True

    results = {}
    for backend in backends:
        if backend == "twilio":
            results[backend] = _send_twilio(to, body)
        elif backend == "ntfy":
            results[backend] = _send_ntfy(body, title)
        elif backend == "imessage":
            results[backend] = _send_imessage(to, body)

    delivered = [b for b, ok in results.items() if ok]
    failed = [b for b, ok in results.items() if not ok]
    if failed:
        log.warning("delivery failed on: %s", ", ".join(failed))
    _log_alert(f"{'SENT' if delivered else 'FAILED'} "
               f"[ok={','.join(delivered) or '-'} fail={','.join(failed) or '-'}] "
               f"to {to}: {body[:120]!r}")
    return bool(delivered)


def send_daily_burst(conn, events: list, store, dry_run: bool = False) -> int:
    """Verdict 1: send the day's messages, respecting the hard daily cap.

    The cap is enforced against messages already recorded in the database, so a
    second scan on the same day tops up to the ceiling rather than starting over.
    """
    if not events:
        return 0
    to = config.ALERT_PHONE
    already = store.messages_sent_today(conn)
    budget = max(0, config.ALERT_MAX_PER_DAY - already)
    count = min(config.ALERT_BURST, budget)

    if count <= 0:
        log.warning("daily cap reached (%d/%d already sent today) — sending nothing",
                    already, config.ALERT_MAX_PER_DAY)
        return 0
    if count < config.ALERT_BURST:
        log.warning("daily cap trims this burst to %d (%d already sent today)",
                    count, already)

    log.warning("VERDICT 1 — sending %d message(s) to %s; lead: %r",
                count, to, events[0].get("title", "")[:80])
    sent = 0
    for index in range(1, count + 1):
        body = compose_daily(events, index, count)
        title = f"[{index}/{count}] Anti-AI protest news"
        if send_one(body, to=to, dry_run=dry_run, title=title):
            sent += 1
            if not dry_run:
                store.record_message(conn, to, body,
                                     events[0].get("event_key", ""))
                conn.commit()
        if index < count:
            time.sleep(0 if dry_run else config.ALERT_BURST_DELAY)
    log.warning("daily burst complete: %d/%d delivered", sent, count)
    return sent


def send_burst(item: dict, count: int = None, dry_run: bool = False) -> int:
    """Send `count` messages about one confirmed protest. Returns sent count."""
    count = count or config.ALERT_BURST
    to = config.ALERT_PHONE
    sent = 0
    log.warning("ALERT BURST: %d messages to %s for %r",
                count, to, item.get("title", "")[:80])
    for index in range(1, count + 1):
        if send_one(compose(item, index, count), to=to, dry_run=dry_run):
            sent += 1
        if index < count:
            time.sleep(0 if dry_run else config.ALERT_BURST_DELAY)
    log.warning("ALERT BURST complete: %d/%d delivered", sent, count)
    return sent
