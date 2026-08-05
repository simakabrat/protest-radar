"""Entry point: collect -> score -> store -> alert -> publish dashboard data."""
import argparse
import json
import logging
import sys
from datetime import datetime, timedelta

from . import alert, cluster, config, score, sources, store


def setup_logging(verbose: bool = False) -> None:
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    handlers = [logging.FileHandler(config.LOG_PATH), logging.StreamHandler(sys.stdout)]
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)-16s %(message)s",
        handlers=handlers, force=True)
    logging.getLogger("urllib3").setLevel(logging.WARNING)


log = logging.getLogger("radar.main")


def publish(conn, stats: dict, alerts_sent: int, new_signals: list,
            events: list = None, verdict: int = 0,
            confirmed_new: list = None) -> dict:
    """Write web/data.json — everything the dashboard renders."""
    items = store.top_items(conn, limit=400)
    for item in items:
        try:
            item["reasons"] = json.loads(item.get("reasons") or "[]")
        except (ValueError, TypeError):
            item["reasons"] = []

    stored_events = store.top_events(conn, limit=200)
    for event in stored_events:
        for field in ("sources", "reasons", "links"):
            try:
                event[field] = json.loads(event.get(field) or "[]")
            except (ValueError, TypeError):
                event[field] = []

    runs = store.recent_runs(conn, limit=20)
    for run in runs:
        try:
            run["stats"] = json.loads(run.get("stats") or "{}")
        except (ValueError, TypeError):
            run["stats"] = {}

    # Republishing outside a scan (a backfill, say) has no stats of its own;
    # carry the last real scan's numbers rather than reporting zero collectors.
    if not stats:
        stats = next((r["stats"] for r in runs if r.get("stats")), {})

    now = datetime.utcnow()
    day_ago = (now - timedelta(hours=24)).isoformat()
    confirmed = [e for e in stored_events if e["status"] == "CONFIRMED"]
    reported = [e for e in stored_events if e["status"] == "REPORTED"]
    upcoming = [e for e in stored_events if e.get("temporality") == "upcoming"]

    payload = {
        "generated_at": now.isoformat() + "Z",
        "verdict": verdict,
        "verdict_label": "NEWS FOUND" if verdict else "NO NEWS",
        "verdict_events": [e.get("title", "") for e in (confirmed_new or [])][:10],
        "site_url": config.SITE_URL,
        "alert_phone": config.ALERT_PHONE,
        "alert_backend": alert.backend_name(),
        "messages_today": store.messages_sent_today(conn),
        "messages_per_day_cap": config.ALERT_MAX_PER_DAY,
        "thresholds": {"confirm": config.CONFIRM_THRESHOLD,
                       "signal": config.SIGNAL_THRESHOLD},
        "summary": {
            "total_events": len(stored_events),
            "total_tracked": len(items),
            "confirmed": len(confirmed),
            "reported": len(reported),
            "signals": len([e for e in stored_events if e["status"] == "SIGNAL"]),
            "new_24h": len([e for e in stored_events
                            if (e.get("first_seen") or "") >= day_ago]),
            "upcoming_events": len(upcoming),
            "sf_bay": len([e for e in stored_events if e.get("region") == "sf_bay"]),
            "la": len([e for e in stored_events if e.get("region") == "la"]),
            "alerts_sent_this_run": alerts_sent,
            "sources_polled": sum(v for v in stats.values() if v > 0),
        },
        "collector_stats": stats,
        "events": stored_events,
        "items": items,
        "new_this_run": [i["fingerprint"] for i in new_signals],
        "runs": runs,
    }

    config.WEB_DIR.mkdir(parents=True, exist_ok=True)
    with open(config.WEB_DIR / "data.json", "w") as handle:
        json.dump(payload, handle, indent=1, default=str)
    log.info("published dashboard data: %d items, %d confirmed",
             len(items), len(confirmed))
    return payload


def run(dry_run: bool = False, no_alert: bool = False) -> dict:
    conn = store.connect()
    run_id = store.start_run(conn)
    error = None
    alerts_sent = 0
    new_signals = []

    try:
        log.info("=== collection start ===")
        raw_items, stats = sources.collect_all()
        log.info("collected %d raw items", len(raw_items))

        scored, seen = [], set()
        for item in raw_items:
            if not item.get("title"):
                continue
            item["fingerprint"] = store.fingerprint(item)
            if item["fingerprint"] in seen:
                continue
            seen.add(item["fingerprint"])
            scored.append(score.score_item(item))

        keepers = [i for i in scored if i["status"] != "NOISE"]
        log.info("scored %d unique items -> %d above signal threshold",
                 len(scored), len(keepers))

        for item in keepers:
            if store.upsert(conn, item):
                new_signals.append(item)
        conn.commit()

        # Collapse items into distinct real-world events: one protest =
        # one alert burst, no matter how many outlets cover it.
        events = cluster.cluster_items(keepers)
        new_events = [e for e in events if store.upsert_event(conn, e)]
        conn.commit()
        log.info("%d new items, %d events (%d new)",
                 len(new_signals), len(events), len(new_events))

        first_run = store.get_meta(conn, "seeded") is None
        if first_run:
            seeded = store.seed_all_alerted(conn)
            store.set_meta(conn, "seeded", datetime.utcnow().isoformat())
            conn.commit()
            log.warning("FIRST RUN: baselined %d existing events without alerting. "
                        "Future runs alert only on newly discovered protests.", seeded)

        # The day's verdict is binary: 1 means genuine, corroborated,
        # still-upcoming US protest news exists; 0 means it does not.
        confirmed_new = store.unalerted_confirmed_events(conn)
        verdict = 1 if confirmed_new else 0
        sent_today = store.messages_sent_today(conn)
        log.info("VERDICT %d — %d qualifying event(s); %d/%d messages already "
                 "sent today", verdict, len(confirmed_new), sent_today,
                 config.ALERT_MAX_PER_DAY)

        if verdict and not no_alert:
            alerts_sent = alert.send_daily_burst(conn, confirmed_new, store,
                                                 dry_run=dry_run)
            if not dry_run and alerts_sent:
                # Every qualifying event is marked so today's news never
                # re-alerts on the next scan.
                store.mark_events_alerted(conn, [e["event_key"] for e in confirmed_new])
                conn.commit()
        elif verdict:
            log.info("alerting suppressed (--no-alert); verdict was 1 with %d event(s)",
                     len(confirmed_new))

        payload = publish(conn, stats, alerts_sent, new_signals, events,
                          verdict=verdict, confirmed_new=confirmed_new)
        store.finish_run(conn, run_id, collected=len(raw_items), scored=len(scored),
                         new_signals=len(new_signals), confirmed=len(confirmed_new),
                         alerts_sent=alerts_sent, stats=json.dumps(stats))
        return payload
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        log.exception("run failed")
        store.finish_run(conn, run_id, error=error)
        raise
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Anti-AI Protest Radar")
    parser.add_argument("--dry-run", action="store_true",
                        help="log alerts instead of sending them")
    parser.add_argument("--no-alert", action="store_true",
                        help="skip alerting entirely")
    parser.add_argument("--verbose", "-v", action="store_true")
    parser.add_argument("--test-alert", action="store_true",
                        help="send one test message to the configured number")
    parser.add_argument("--verdict", action="store_true",
                        help="print only the binary verdict (0 = no news, 1 = news)")
    args = parser.parse_args()
    setup_logging(args.verbose)

    if args.test_alert:
        ok = alert.send_one(
            "TEST — Anti-AI Protest Radar is wired up. Real alerts will "
            f"arrive as {config.ALERT_BURST} urgent messages.", dry_run=args.dry_run)
        print("test alert:", "sent" if ok else "FAILED",
              f"(backend={alert.backend_name()})")
        return 0 if ok else 1

    payload = run(dry_run=args.dry_run, no_alert=args.no_alert)
    summary = payload["summary"]
    if args.verdict:
        # Machine-readable mode: emit only the 0/1 signal.
        print(payload["verdict"])
        return 0
    verdict = payload["verdict"]
    print(f"\n{'='*62}\n  ANTI-AI PROTEST RADAR — run complete\n{'='*62}")
    print(f"  VERDICT           : {verdict}  ({payload['verdict_label']})")
    print(f"  Messages today    : {payload['messages_today']}/"
          f"{payload['messages_per_day_cap']}")
    print(f"  Distinct events   : {summary['total_events']}")
    print(f"  Tracked signals   : {summary['total_tracked']}")
    print(f"  CONFIRMED upcoming: {summary['confirmed']}")
    print(f"  REPORTED (past)   : {summary['reported']}")
    print(f"  New in last 24h   : {summary['new_24h']}")
    print(f"  SF Bay / LA       : {summary['sf_bay']} / {summary['la']}")
    print(f"  Upcoming events   : {summary['upcoming_events']}")
    print(f"  Alerts sent       : {summary['alerts_sent_this_run']}")
    print(f"{'='*62}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
