#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "$0")/.."
docker info >/dev/null
docker compose up -d --pull missing
url="http://localhost:${GENTACTIX_HTTP_PORT:-8080}"
for attempt in $(seq 1 90); do
 if curl --fail --silent "$url/api/health" >/dev/null; then
  if command -v xdg-open >/dev/null; then xdg-open "$url" >/dev/null 2>&1 & fi
  printf 'GenTactix: %s\n' "$url"
  exit 0
 fi
 sleep 2
done
docker compose logs --tail=80
exit 1
