#!/usr/bin/env bash
set -euo pipefail

BOT_PORT="${BOT_PORT:-18080}"
BOT_SERVICE="${BOT_SERVICE:-kami-man.service}"
ONEBOT_CONTAINER="${ONEBOT_CONTAINER:-snowluma}"
LOGGER_TAG="${LOGGER_TAG:-kami-onebot-watchdog}"
QQ_LOGIN_HELPER="${QQ_LOGIN_HELPER:-/home/ubuntu/qqbot/kami-man/deploy/qq_login_recover.py}"
RESTART_COOLDOWN_SECONDS="${RESTART_COOLDOWN_SECONDS:-300}"
RESTART_STAMP="${RESTART_STAMP:-/run/kami-onebot-watchdog-last-restart}"

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

if [ -r "$QQ_LOGIN_HELPER" ]; then
  if recovery_output="$(docker exec -i "$ONEBOT_CONTAINER" python3 - < "$QQ_LOGIN_HELPER" 2>&1)"; then
    log "$recovery_output; waiting for OneBot to reconnect"
    exit 0
  else
    recovery_status=$?
    log "$recovery_output"
    if [ "$recovery_status" -eq 4 ]; then
      # A login screen is present, but clicking without recognizing the button is unsafe.
      exit 0
    fi
  fi
else
  log "QQ login helper not found at $QQ_LOGIN_HELPER"
fi

now="$(date +%s)"
last_restart="$(cat "$RESTART_STAMP" 2>/dev/null || echo 0)"
if [[ "$last_restart" =~ ^[0-9]+$ ]] && (( now - last_restart < RESTART_COOLDOWN_SECONDS )); then
  log "no established OneBot websocket connection on port $BOT_PORT; restart cooldown active"
  exit 0
fi

log "no established OneBot websocket connection on port $BOT_PORT; restarting $ONEBOT_CONTAINER"
printf '%s\n' "$now" > "$RESTART_STAMP"
docker restart "$ONEBOT_CONTAINER" >/dev/null
