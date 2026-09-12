#!/bin/bash
# update.sh -- pull the latest voicemail-inbox and (re)deploy the single container.
# Safe to re-run. Run from the deploy checkout (e.g. /mnt/user/appdata/voicemail-inbox).
#
# Handles the 2-container -> 1-container consolidation: --remove-orphans drops
# the old separate whisper container. Fails loudly (does NOT redeploy) if the
# required AUTH_TOKEN is missing from .env, since an empty token 401s every
# /ingest upload.
set -euo pipefail
cd "$(dirname "$0")"

WHISPER_MODELS="/mnt/user/data/Documents/Voicemail/whisper-models"

echo "==> Preflight"
# AUTH_TOKEN is required by docker-compose.yml (environment: AUTH_TOKEN=${AUTH_TOKEN})
if [ ! -f .env ] || ! grep -qE '^AUTH_TOKEN=.+' .env; then
  echo "ERROR: .env is missing a non-empty AUTH_TOKEN." >&2
  echo "  Fix once:  echo 'AUTH_TOKEN=<the shared bearer token>' >> .env" >&2
  echo "  (must match the iPhone Shortcut's 'Authorization: Bearer' header)" >&2
  exit 1
fi
# New bind mount target must exist before compose creates the container.
mkdir -p "$WHISPER_MODELS"

echo "==> Fetch + hard reset to origin/main"
git fetch origin
git reset --hard origin/main

echo "==> Rebuild + restart (drops orphaned old whisper container)"
docker-compose up -d --build --remove-orphans

echo "==> Done. Reachable at http://10.0.12.44:8000"
docker-compose ps
