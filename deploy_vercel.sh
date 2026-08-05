#!/bin/bash
# Redeploy the dashboard to Vercel production. Called by run.sh after each scan.
#
# The project's production domain (RADAR_SITE_URL) is stable and is repointed to
# the newest build automatically by `--prod`, so the link already sent to the
# phone keeps resolving to current data. No aliasing needed.
set -e
cd "$(dirname "$0")" || exit 1
[ -f .env ] && set -a && . ./.env && set +a

# launchd runs with a minimal PATH that excludes nvm, so `vercel` would not be
# found on scheduled scans. Prepend the directory it actually lives in.
export PATH="/Users/simo_sazdava/.nvm/versions/node/v24.16.0/bin:$PATH"
if ! command -v vercel >/dev/null 2>&1; then
  echo "vercel CLI not on PATH (looked in /Users/simo_sazdava/.nvm/versions/node/v24.16.0/bin) — skipping deploy" >&2
  exit 0
fi

if [ ! -f web/data.json ]; then
  echo "web/data.json missing — run ./run.sh --no-alert first" >&2
  exit 1
fi

OUT=$(vercel deploy web --prod --yes 2>&1) || { echo "$OUT" >&2; exit 1; }
BUILD=$(echo "$OUT" | grep -oE 'https://[a-zA-Z0-9._-]+\.vercel\.app' | tail -1)
echo "Deployed build : ${BUILD:-unknown}"
echo "Live at        : ${RADAR_SITE_URL:-https://web-beige-iota-38.vercel.app}"
