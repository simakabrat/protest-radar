# Cloud setup — 15 minutes, then it runs without your Mac

Everything is built and committed. Three steps remain, and all three need *your*
accounts, which is why I can't do them for you.

---

## Step 1 — Install the ntfy app and subscribe (2 min)

This is how alerts reach your phone with the Mac off.

1. Install **ntfy** — [iOS App Store](https://apps.apple.com/us/app/ntfy/id1625396347)
2. Open it → **+** → Subscribe to topic
3. Enter exactly:

```
protest-radar-gVWqZ2eKy27kz-nJ
```

4. Leave server as the default `ntfy.sh`

**Verify it worked:** run this and your phone should buzz.

```bash
curl -H "Title: Radar test" -H "Priority: urgent" -d "If you see this, cloud alerts will reach you." https://ntfy.sh/protest-radar-gVWqZ2eKy27kz-nJ
```

> Treat that topic string like a password — anyone who knows it can read your
> alerts (and send you fake ones). It is deliberately kept out of the repo.

---

## Step 2 — Push to GitHub (5 min)

Create an **empty** repo at https://github.com/new — name it `protest-radar`,
no README, no .gitignore. Then:

```bash
cd ~/protest-radar && git branch -M main && git remote add origin https://github.com/YOUR_USERNAME/protest-radar.git && git push -u origin main
```

**Make it public** unless you have a reason not to: public repos get unlimited
Actions minutes. A private repo has 2,000 min/month and this uses ~1,200. Nothing
secret is in the code — the topic and any tokens live in Secrets, not files.

---

## Step 3 — Add the repository secrets (5 min)

In your repo: **Settings → Secrets and variables → Actions → New repository secret**.

| Secret name | Value |
|---|---|
| `RADAR_NTFY_TOPIC` | `protest-radar-gVWqZ2eKy27kz-nJ` |
| `RADAR_SITE_URL` | `https://web-beige-iota-38.vercel.app` |

Optional, both independent of each other:

| Secret name | Why |
|---|---|
| `VERCEL_TOKEN` | Redeploys the dashboard after each scan so the link in your alerts shows fresh data. Get one at vercel.com/account/tokens. Without it, scans still run and alert — the dashboard just stops updating. |
| `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM_NUMBER` | Adds real SMS to +14159335114 alongside ntfy. Both channels fire, so one failing still reaches you. ~$1.15/month. |

---

## Step 4 — Prove it works

Repo → **Actions** tab → **Protest Radar Scan** → **Run workflow**.

It takes 10–15 minutes. When it finishes, the run summary shows the verdict,
message count, and how many events were scanned. From then on it runs itself
every 6 hours.

---

## What "reliable" actually means here

Honest limits, so nothing surprises you:

- **GitHub Actions cron is not to-the-minute.** Under load, runs can start
  5–30 minutes late. Occasionally a scheduled run is skipped entirely. Four runs
  a day means a skip costs you at most one window, not a day.
- **Scheduled workflows are disabled after 60 days of no repo activity.** Every
  scan commits the refreshed database, which counts as activity — so this stays
  alive on its own. Just don't be alarmed if GitHub emails you about it.
- **ntfy.sh is a free public service** with no uptime guarantee. If that worries
  you, add Twilio as the second channel; both fire on every alert.
- **Reddit blocks datacenter IPs harder than home ones**, so expect more 429s in
  the cloud than locally. The other seven collectors carry the load — check
  *Source health* on the dashboard if you want to see the split.

The daily cap of 5 messages is enforced against the committed database using
**America/Los_Angeles** dates, so a UTC runner can't roll the day over early and
send you a second burst the same evening.

---

## Your Mac's local schedule is now off

`~/Library/LaunchAgents/com.protestradar.scan.plist.disabled` — renamed, not
deleted. Leaving it running would have scanned against a *separate* local
database, so the two copies would double-alert and neither would respect the
other's daily cap. The cloud is now the single source of truth.

To run a scan by hand locally anyway:

```bash
cd ~/protest-radar && ./run.sh --no-alert
```
