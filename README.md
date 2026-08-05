# Anti-AI Protest Radar

Scans ~90 sources every 12 hours for anti-AI protests in the US — weighted toward
San Francisco / the Bay Area and Los Angeles — scores what it finds, and publishes
a live dashboard:

**https://web-beige-iota-38.vercel.app**

Each scan produces a binary verdict:

| Verdict | Meaning | Messages |
|---|---|---|
| **0** | No genuine protest news | none |
| **1** | Genuine, corroborated, upcoming US protest news | **5 messages to +14159335114**, each carrying the dashboard link |

**Never more than 5 messages per calendar day**, no matter how many events qualify
or how many scans run. The cap is enforced against a `sent_messages` table, so a
restart or a second scan cannot reset it.

## How it runs

Scans execute on **GitHub Actions every 6 hours**, not on your Mac — so they
happen whether or not the Mac is on. Alerts go out via **ntfy.sh push
notifications** (and Twilio SMS if configured). See `SETUP_CLOUD.md` for the
one-time setup.

The local `launchd` job is disabled on purpose: running both would mean two
separate databases, double alerts, and neither respecting the other's daily cap.

## Where this lives

`~/protest-radar` — deliberately **not** in `~/Desktop`. macOS TCC blocks `launchd`
from executing anything inside Desktop, Documents, or Downloads: the scheduled job
fails with `Operation not permitted` before it runs a single line. Moving the
project out of those folders is the fix that needs no special permissions. If you
move it back, the 12-hour schedule silently stops working.

## Quick start

```bash
./run.sh --no-alert     # first scan, no messages
```

```bash
./serve.sh              # dashboard at http://localhost:8787
```

```bash
./install_schedule.sh   # scan automatically at 08:00 and 20:00 daily
```

## What it watches

| Channel | What it covers |
|---|---|
| **Google News RSS** (20 queries) | Highest-yield channel. Catches national and local coverage within hours. |
| **GDELT** (5 queries) | Global news index, US-filtered — surfaces small local outlets nothing else indexes. |
| **Bing News RSS** | Second opinion on the news queries. |
| **Direct site scrapes** (~34 sites) | PauseAI, StopAI, Stop The Race, No AGI, Encode Justice, Midas Project, AI Now, Algorithmic Justice League, Tech Workers Coalition, Athena, plus artist/labor groups (Concept Art Association, NAVA, SAG-AFTRA, WGA). |
| **Protest wires** | Indybay (newswire + calendar + search), LA Indymedia, It's Going Down, Waging Nonviolence, Labor Notes, Truthout, Common Dreams. |
| **Local press RSS** | Mission Local, 48 Hills, SF Standard, SFist, Berkeleyside, Hoodline, El Tecolote, LAist, 404 Media, Tech Policy Press. |
| **Reddit** (8 searches + 12 subs) | r/sanfrancisco, r/bayarea, r/LosAngeles, r/ControlProblem, r/ArtistHate, r/aiwars… |
| **Bluesky** (10 queries) | Full-text search — usually the *earliest* signal, since organizers post before press covers it. |
| **Mobilize.us** | Public event API used by most US progressive organizing. |
| **Eventbrite / Luma** | Public event search pages for SF and LA. |

Each scan pulls ~2,400–3,000 raw items.

## How scoring works

Additive, capped at 100 (`radar/score.py`):

| Signal | Points |
|---|---|
| High-signal phrase (`"ai protest"`, `"rally against ai"`) | +45 |
| AI subject terms (openai, agi, data center…) | +20 |
| Protest action terms (march, picket, walkout…) | +25 |
| Anti-AI stance (pauseai, moratorium, "shut it down") | +15 |
| AI and protest terms within 120 characters | +15 |
| Geography: SF/LA +25, elsewhere in US +12, foreign −30 | ±30 |
| Future-dated event | +18 |
| Core source (anti-AI org or protest wire) | +10 |
| Concrete logistics (address, "meet at", a time) | +12 |
| Forward-looking language | +12 |
| Retrospective language | −18 |
| Stale (archive URL, past date, >7 days old) | −20 |
| Noise terms (stock, webinar, "best AI tools") | −30 |

Two hard gates: no protest verb caps the score at 15; no AI subject caps it at 10.

### Statuses

- **CONFIRMED** — makes the day's verdict 1. Requires *all* of: score ≥ 70,
  forward-looking language, not stale, a positive US location match, and a real
  headline (not page navigation).
- **REPORTED** — a genuine protest that already happened, is outside the US, or
  can't be dated. Shown on the dashboard, never texted.
- **SIGNAL** — score ≥ 30. The watchlist, where a forming protest shows up first.
- **NOISE** — discarded.

### Why events, not articles

One protest produces dozens of articles and posts. `radar/cluster.py` groups items
into distinct real-world events by region, date, and target organization, then
merges near-duplicate headlines by token overlap. Clustering is why a nationally
covered protest counts as one event rather than 400 — and with the daily cap on
top, a day of heavy coverage still sends exactly 5 messages.

## Alerting

5 messages, 3 seconds apart, to `+14159335114`, each linking to the dashboard.
Two backends:

- **iMessage** (default, no signup) — macOS Messages.app via AppleScript. Requires
  Messages to be signed in, and Terminal to have Automation permission for it
  (System Settings → Privacy & Security → Automation).
- **Twilio** (real SMS, survives your Mac being asleep) — copy `.env.example` to
  `.env` and fill in the three `TWILIO_*` values. Auto-detected when present.

Every send, success or failure, is appended to `data/alerts.log`.

### Safeguards

Four independent limits, because a scan on 2026-07-29 sent **50 messages** when
five events qualified at once:

1. **Daily cap — 5 messages per calendar day, absolute.** Counted in the database
   across every scan and every event. A second scan the same day tops up toward
   the ceiling rather than starting a new burst. Change with `RADAR_MAX_PER_DAY`.
2. **Corroboration.** An event needs a concrete future date *or* two independent
   sources. This also stops two posts about the same rally each firing a burst.
3. **Headline gate.** The protest verb must appear in the title, not just deep in
   body text — that alone rejected a geopolitics post whose linked video
   description happened to mention a protest.
4. **First-run seeding.** The first scan baselines everything as already-alerted.

Note that seeding only covers what existed at seed time; a later scan that
newly discovers an old page still treats it as new. Limits 1–3 are what actually
contain that case.

**Alert-once.** Each event's `alerted` flag is set after its burst; it never
re-fires. `--dry-run` logs messages instead of sending; `--no-alert` skips
alerting entirely.

## Commands

```bash
./run.sh                  # full scan: verdict, alerts, publish, deploy
./run.sh --dry-run        # scan, log the burst instead of sending
./run.sh --no-alert       # scan, no alerting at all
./run.sh --verdict        # print only 0 or 1 (machine-readable)
./run.sh --test-alert     # send one test message
./deploy_vercel.sh        # redeploy the dashboard by hand
```

`run.sh` redeploys to Vercel after every scan, so the link already sitting in your
messages always resolves to current data.

## Tuning

Everything lives in `radar/config.py`: source lists, keyword vocabularies,
geography, and thresholds. To make alerting stricter or looser, change
`RADAR_CONFIRM_THRESHOLD` (default 70) in `.env`.

To add a source, append to `SITE_SOURCES` (HTML), `RSS_SOURCES` (feeds),
`NEWS_QUERIES` (Google/Bing), or `BLUESKY_QUERIES`.

## Layout

```
radar/
  config.py    sources, keywords, geography, thresholds
  fetch.py     HTTP with retries and per-host throttles
  sources.py   the 8 collectors
  score.py     scoring, geography, date and tense extraction
  cluster.py   articles -> distinct real-world events
  store.py     SQLite: dedupe, history, alert bookkeeping
  alert.py     iMessage / Twilio burst
  main.py      entry point
web/           dashboard (index.html + styles.css + app.js + data.json)
data/          radar.db, radar.log, alerts.log
```

## Operational notes

- A scan takes 6–12 minutes, mostly waiting on Reddit's and GDELT's rate limits
  (7s and 8s per request — deliberate, to stay a good citizen).
- Reddit returns 429 for some queries even so; the run continues and other
  collectors cover the gap. Check *Source health* on the dashboard.
- GitHub Actions cron can start 5–30 minutes late under load and very
  occasionally skips a run; four scans a day absorbs that.
- The committed `data/radar.db` is what carries dedupe and "already alerted"
  state between cloud runs. If it were not committed, every run would treat the
  world as new and re-alert everything.
