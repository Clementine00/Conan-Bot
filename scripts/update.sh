#!/usr/bin/env bash
# Pull the latest published image and restart the bot if it changed.
# Copy this next to docker-compose.yml on the server and run: ./update.sh
set -euo pipefail

cd "$(dirname "$0")"

if [[ ! -f .env ]]; then
  echo "No .env in $(pwd) — the bot needs DISCORD_TOKEN. Aborting." >&2
  exit 1
fi

before=$(docker compose images --quiet bot 2>/dev/null || true)

echo "Pulling latest image..."
docker compose pull

# up -d is a no-op when the image digest is unchanged, so this is safe to
# run repeatedly; the container is only recreated on an actual update.
docker compose up -d

after=$(docker compose images --quiet bot 2>/dev/null || true)

if [[ "$before" == "$after" ]]; then
  echo "Already up to date."
else
  echo "Updated. Removing superseded layers..."
  docker image prune -f
fi

echo
docker compose ps
echo
echo "Logs:  docker compose logs -f"
