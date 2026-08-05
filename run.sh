#!/bin/bash
# One scan: collect -> score -> cluster -> verdict -> alert -> publish -> deploy.
cd "$(dirname "$0")" || exit 1
[ -f .env ] && set -a && . ./.env && set +a

./.venv/bin/python -m radar.main "$@"
STATUS=$?

# Push the refreshed dashboard so the link in any alert shows current data.
# Skipped for --test-alert and --verdict, which don't change the dashboard.
case " $* " in
  *" --test-alert "*|*" --verdict "*) ;;
  *) [ -x ./deploy_vercel.sh ] && ./deploy_vercel.sh ;;
esac

exit $STATUS
