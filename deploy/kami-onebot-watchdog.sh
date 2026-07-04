#!/usr/bin/env bash
set -euo pipefail

BOT_PORT="${BOT_PORT:-18080}"
BOT_SERVICE="${BOT_SERVICE:-kami-man.service}"
ONEBOT_CONTAINER="${ONEBOT_CONTAINER:-snowluma}"
LOGGER_TAG="${LOGGER_TAG:-kami-onebot-watchdog}"

log() {
  logger -t "$LOGGER_TAG" "$*"
  printf '%s\n' "$*"
}

if ! systemctl is-active --quiet "$BOT_SERVICE"; then
  log "bot service $BOT_SERVICE is not active; skip onebot watchdog"
  exit 0
fi

if ! command -v docker >/dev/null 2>&1; then
  log "docker command not found; cannot check $ONEBOT_CONTAINER"
  exit 1
fi

container_running="$(docker inspect -f '{{.State.Running}}' "$ONEBOT_CONTAINER" 2>/dev/null || true)"
if [ "$container_running" != "true" ]; then
  log "onebot container $ONEBOT_CONTAINER is not running; starting it"
  docker start "$ONEBOT_CONTAINER" >/dev/null
  exit 0
fi

if ss -Htn | awk -v port=":$BOT_PORT" '$1 == "ESTAB" && (index($4, port) || index($5, port)) { found = 1 } END { exit found ? 0 : 1 }'; then
  exit 0
fi

log "no established OneBot websocket connection on port $BOT_PORT; restarting $ONEBOT_CONTAINER"
docker restart "$ONEBOT_CONTAINER" >/dev/null
