"""SQLite persistence: dedupe, history, alert bookkeeping."""
import hashlib
import json
import re
import sqlite3
from datetime import datetime

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    fingerprint TEXT PRIMARY KEY,
    title       TEXT,
    summary     TEXT,
    url         TEXT,
    source      TEXT,
    source_type TEXT,
    score       INTEGER,
    status      TEXT,
    region      TEXT,
    place       TEXT,
    event_date  TEXT,
    is_future   INTEGER,
    temporality TEXT,
    reasons     TEXT,
    published   TEXT,
    first_seen  TEXT,
    last_seen   TEXT,
    alerted     INTEGER DEFAULT 0,
    alerted_at  TEXT
);
CREATE INDEX IF NOT EXISTS idx_items_score  ON items(score DESC);
CREATE INDEX IF NOT EXISTS idx_items_status ON items(status);
CREATE INDEX IF NOT EXISTS idx_items_seen   ON items(first_seen DESC);

CREATE TABLE IF NOT EXISTS events (
    event_key    TEXT PRIMARY KEY,
    title        TEXT,
    url          TEXT,
    score        INTEGER,
    status       TEXT,
    region       TEXT,
    place        TEXT,
    target       TEXT,
    event_date   TEXT,
    event_time   TEXT,
    temporality  TEXT,
    source_count INTEGER,
    sources      TEXT,
    links        TEXT,
    url_is_direct INTEGER DEFAULT 1,
    reasons      TEXT,
    first_seen   TEXT,
    last_seen    TEXT,
    alerted      INTEGER DEFAULT 0,
    alerted_at   TEXT
);
CREATE INDEX IF NOT EXISTS idx_events_score ON events(score DESC);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

-- One row per message actually sent. This is the source of truth for the
-- daily cap, so a restart or a second scan cannot reset the count.
CREATE TABLE IF NOT EXISTS sent_messages (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    sent_on   TEXT,
    sent_at   TEXT,
    phone     TEXT,
    event_key TEXT,
    body      TEXT
);
CREATE INDEX IF NOT EXISTS idx_sent_on ON sent_messages(sent_on);

CREATE TABLE IF NOT EXISTS runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at  TEXT,
    finished_at TEXT,
    collected   INTEGER,
    scored      INTEGER,
    new_signals INTEGER,
    confirmed   INTEGER,
    alerts_sent INTEGER,
    stats       TEXT,
    error       TEXT
);
"""


def fingerprint(item: dict) -> str:
    """Stable identity for an item: normalized URL, else normalized title."""
    url = (item.get("url") or "").strip().lower()
    url = re.sub(r"[?#].*$", "", url).rstrip("/")
    title = re.sub(r"\W+", " ", (item.get("title") or "").lower()).strip()
    basis = url if len(url) > 12 else f"{item.get('source', '')}|{title}"
    if title and len(url) > 12:
        basis = f"{url}|{title[:60]}"
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:32]


def connect():
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def upsert(conn, item: dict) -> bool:
    """Insert or refresh an item. Returns True if this is the first sighting."""
    now = datetime.utcnow().isoformat()
    fp = item["fingerprint"]
    existing = conn.execute(
        "SELECT fingerprint, score FROM items WHERE fingerprint = ?", (fp,)
    ).fetchone()
    if existing:
        conn.execute(
            "UPDATE items SET last_seen = ?, score = ?, status = ?, "
            "event_date = COALESCE(?, event_date), reasons = ? WHERE fingerprint = ?",
            (now, item["score"], item["status"], item.get("event_date"),
             json.dumps(item.get("reasons", [])), fp))
        return False
    conn.execute(
        "INSERT INTO items (fingerprint, title, summary, url, source, source_type, "
        "score, status, region, place, event_date, is_future, temporality, reasons, "
        "published, first_seen, last_seen) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (fp, item.get("title", ""), item.get("summary", ""), item.get("url", ""),
         item.get("source", ""), item.get("source_type", ""), item["score"],
         item["status"], item.get("region", ""), item.get("place", ""),
         item.get("event_date"), int(bool(item.get("is_future"))),
         item.get("temporality", "unknown"),
         json.dumps(item.get("reasons", [])), item.get("published"), now, now))
    return True


def upsert_event(conn, event: dict) -> bool:
    """Insert or refresh a clustered event. Returns True if newly seen."""
    now = datetime.utcnow().isoformat()
    key = event["event_key"]
    existing = conn.execute(
        "SELECT event_key FROM events WHERE event_key = ?", (key,)).fetchone()
    if existing:
        conn.execute(
            "UPDATE events SET last_seen = ?, score = ?, status = ?, "
            "source_count = ?, sources = ?, temporality = ?, links = ?, "
            "url = ?, url_is_direct = ?, "
            "event_date = COALESCE(?, event_date), "
            "event_time = COALESCE(?, event_time) WHERE event_key = ?",
            (now, event["score"], event["status"], event["source_count"],
             json.dumps(event["sources"]), event["temporality"],
             json.dumps(event.get("links", [])), event.get("url", ""),
             int(bool(event.get("url_is_direct", True))),
             event.get("event_date"), event.get("event_time"), key))
        return False
    conn.execute(
        "INSERT INTO events (event_key, title, url, url_is_direct, score, status, "
        "region, place, target, event_date, event_time, temporality, source_count, "
        "sources, links, reasons, first_seen, last_seen) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (key, event["title"], event["url"],
         int(bool(event.get("url_is_direct", True))),
         event["score"], event["status"],
         event["region"], event["place"], event["target"], event.get("event_date"),
         event.get("event_time"), event["temporality"], event["source_count"],
         json.dumps(event["sources"]), json.dumps(event.get("links", [])),
         json.dumps(event.get("reasons", [])), now, now))
    return True


def unalerted_confirmed_events(conn) -> list:
    """Confirmed, still-upcoming events that have never triggered a burst.

    Corroboration is required on top of the per-item score: either a concrete
    future date, or two independent sources reporting it. A lone undated post
    is a dashboard signal, not grounds for ten urgent texts — and this is also
    what stops two posts about the same rally from each firing a burst.
    """
    rows = conn.execute(
        "SELECT * FROM events WHERE status = 'CONFIRMED' AND alerted = 0 "
        "AND temporality != 'past' "
        "AND (event_date IS NOT NULL OR source_count >= 2) "
        "ORDER BY score DESC").fetchall()
    return [dict(row) for row in rows]


def mark_events_alerted(conn, keys) -> None:
    now = datetime.utcnow().isoformat()
    conn.executemany(
        "UPDATE events SET alerted = 1, alerted_at = ? WHERE event_key = ?",
        [(now, key) for key in keys])


def seed_all_alerted(conn) -> int:
    """First-run baseline: mark everything known as already alerted."""
    cursor = conn.execute(
        "UPDATE events SET alerted = 1, alerted_at = ? WHERE alerted = 0",
        (datetime.utcnow().isoformat(),))
    conn.execute("UPDATE items SET alerted = 1 WHERE alerted = 0")
    return cursor.rowcount


def _today() -> str:
    """Current date in the alerting timezone, not the runner's.

    A cloud runner is on UTC, which would roll the daily cap over at 5pm
    California time and allow a second burst the same evening.
    """
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo(config.ALERT_TIMEZONE)).strftime("%Y-%m-%d")
    except Exception:
        return datetime.now().strftime("%Y-%m-%d")


def messages_sent_today(conn, day: str = None) -> int:
    """How many alert messages have gone out on `day` (YYYY-MM-DD)."""
    day = day or _today()
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM sent_messages WHERE sent_on = ?", (day,)).fetchone()
    return row["n"] if row else 0


def record_message(conn, phone: str, body: str, event_key: str = "") -> None:
    conn.execute(
        "INSERT INTO sent_messages (sent_on, sent_at, phone, event_key, body) "
        "VALUES (?,?,?,?,?)",
        (_today(), datetime.now().isoformat(), phone, event_key, body[:400]))


def get_meta(conn, key: str, default=None):
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_meta(conn, key: str, value: str) -> None:
    conn.execute("INSERT INTO meta (key, value) VALUES (?, ?) "
                 "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                 (key, str(value)))


def top_events(conn, limit: int = 200) -> list:
    rows = conn.execute(
        "SELECT * FROM events WHERE status IN ('CONFIRMED','REPORTED','SIGNAL') "
        "ORDER BY score DESC, source_count DESC LIMIT ?", (limit,)).fetchall()
    return [dict(row) for row in rows]


def top_items(conn, limit: int = 300) -> list:
    rows = conn.execute(
        "SELECT * FROM items WHERE status IN ('CONFIRMED','REPORTED','SIGNAL') "
        "ORDER BY score DESC, first_seen DESC LIMIT ?", (limit,)
    ).fetchall()
    return [dict(row) for row in rows]


def recent_runs(conn, limit: int = 30) -> list:
    rows = conn.execute(
        "SELECT * FROM runs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [dict(row) for row in rows]


def start_run(conn) -> int:
    cursor = conn.execute("INSERT INTO runs (started_at) VALUES (?)",
                          (datetime.utcnow().isoformat(),))
    conn.commit()
    return cursor.lastrowid


def finish_run(conn, run_id: int, **fields) -> None:
    fields["finished_at"] = datetime.utcnow().isoformat()
    assignments = ", ".join(f"{k} = ?" for k in fields)
    conn.execute(f"UPDATE runs SET {assignments} WHERE id = ?",
                 list(fields.values()) + [run_id])
    conn.commit()
