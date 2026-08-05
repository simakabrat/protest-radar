"""Print a one-glance scan summary for the GitHub Actions run page.

Lives in a file rather than a heredoc inside the workflow: YAML block scalars
strip a common indent, which silently mangles an embedded Python heredoc.
"""
import json
import pathlib
import sys

path = pathlib.Path("web/data.json")
if not path.exists():
    print("- No data.json produced.")
    sys.exit(0)

data = json.loads(path.read_text())
summary = data.get("summary", {})
verdict = data.get("verdict")

print(f"- **Verdict: {verdict}** — {data.get('verdict_label', '')}")
print(f"- Messages today: {data.get('messages_today')}/"
      f"{data.get('messages_per_day_cap')}")
print(f"- Delivery: `{data.get('alert_backend')}`")
print(f"- Confirmed: {summary.get('confirmed')} · "
      f"Events: {summary.get('total_events')} · "
      f"SF/LA: {summary.get('sf_bay')}/{summary.get('la')} · "
      f"Items scanned: {summary.get('sources_polled')}")

for title in (data.get("verdict_events") or [])[:5]:
    print(f"  - {title[:110]}")

dead = [k for k, v in (data.get("collector_stats") or {}).items() if v <= 0]
if dead:
    print(f"- ⚠️ Collectors returning nothing: {', '.join(dead)}")
