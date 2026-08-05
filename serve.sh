#!/bin/bash
# Serve the dashboard at http://localhost:8787
cd "$(dirname "$0")/web" || exit 1
echo "Anti-AI Protest Radar -> http://localhost:8787"
exec ../.venv/bin/python -m http.server 8787
