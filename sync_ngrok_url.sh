#!/bin/bash
# sync_ngrok_url.sh — reads current ngrok tunnel URL and pushes it to the
# DO server if it changed. Also runs a 7zap health check every tick.
# Runs every 5 min via com.pieza.sync-ngrok-url LaunchAgent.

set -uo pipefail   # -e removed so health-check failures don't abort the script

NGROK_API="http://localhost:4040/api/tunnels"
DO_HOST="root@134.122.115.142"
DO_ENV="/opt/parts-bot/.env"
STATE_FILE="$HOME/pieza-relay/.last_ngrok_url"
HEALTH_FAILS_FILE="$HOME/pieza-relay/.health_fails"
LOG_FILE="/tmp/sync_ngrok.log"

RELAY_LOCAL="http://localhost:8765"
RELAY_TOKEN="pieza2026"
# Known-good VIN for health probe (Porsche Macan 2017)
TEST_VIN="WP1ZZZ9YBKLA80516"
HEALTH_THRESHOLD=3   # notify after this many consecutive failures

PYTHON3="/opt/homebrew/bin/python3"
NOTIFY_SCRIPT="$HOME/pieza-relay/notify_7zap.py"

ts()  { date "+%Y-%m-%d %H:%M:%S"; }
log() { echo "$(ts): $*" | tee -a "$LOG_FILE"; }

# ── 0. 7zap health check ──────────────────────────────────────────────────
PROBE_URL="${RELAY_LOCAL}/proxy?_url=https://7zap.com/api/catalog/vin_tree&language=en&vin=${TEST_VIN}&modification_number=-&cc=0&page=1"

HEALTH_CODE=$(curl -sf -o /dev/null -w "%{http_code}" \
    -H "X-Relay-Token: ${RELAY_TOKEN}" \
    --max-time 15 \
    "${PROBE_URL}" 2>/dev/null) || HEALTH_CODE="000"

if [ "$HEALTH_CODE" = "401" ] || [ "$HEALTH_CODE" = "403" ] || [ "$HEALTH_CODE" = "000" ]; then
    # Read current fail count (default 0)
    FAILS=0
    if [ -f "$HEALTH_FAILS_FILE" ]; then
        RAW=$(cat "$HEALTH_FAILS_FILE" 2>/dev/null || echo "0")
        [[ "$RAW" =~ ^[0-9]+$ ]] && FAILS=$RAW
    fi
    FAILS=$((FAILS + 1))
    echo "$FAILS" > "$HEALTH_FAILS_FILE"
    log "Health check FAILED (HTTP ${HEALTH_CODE}) — consecutive failures: ${FAILS}/${HEALTH_THRESHOLD}"

    if [ "$FAILS" -ge "$HEALTH_THRESHOLD" ]; then
        log "Threshold reached — triggering failure notification"
        "$PYTHON3" "$NOTIFY_SCRIPT" "relay returned HTTP ${HEALTH_CODE} for ${FAILS} consecutive checks" \
            2>&1 | tee -a "$LOG_FILE" || true
    fi
else
    # Health check passed
    if [ -f "$HEALTH_FAILS_FILE" ]; then
        OLD_FAILS=$(cat "$HEALTH_FAILS_FILE" 2>/dev/null || echo "0")
        echo "0" > "$HEALTH_FAILS_FILE"
        if [ "${OLD_FAILS:-0}" -gt "0" ]; then
            log "Health check recovered (HTTP ${HEALTH_CODE}) — resetting fail counter"
            # Also clear the .notified flag so next failure triggers a fresh alert
            rm -f "$HOME/pieza-relay/.notified" 2>/dev/null || true
        fi
    fi
    log "Health check OK (HTTP ${HEALTH_CODE})"
fi

# ── 1. Read current ngrok URL ──────────────────────────────────────────────
NGROK_URL=$(curl -sf "$NGROK_API" \
    | "$PYTHON3" -c "
import sys, json
d = json.load(sys.stdin)
https = [t['public_url'] for t in d.get('tunnels', []) if t['public_url'].startswith('https')]
print(https[0] if https else '')
" 2>/dev/null) || NGROK_URL=""

if [ -z "$NGROK_URL" ]; then
    log "ngrok not running or no HTTPS tunnel — skipping URL sync"
    exit 0
fi

# ── 2. Compare with last known URL ────────────────────────────────────────
LAST_URL=""
[ -f "$STATE_FILE" ] && LAST_URL=$(cat "$STATE_FILE")

if [ "$NGROK_URL" = "$LAST_URL" ]; then
    log "URL unchanged: $NGROK_URL"
    exit 0
fi

log "URL changed: '${LAST_URL}' → '${NGROK_URL}'"

# ── 3. Update DO server .env and restart bot ──────────────────────────────
ssh -o StrictHostKeyChecking=no -o BatchMode=yes -o ConnectTimeout=10 \
    "$DO_HOST" bash -s <<EOF 2>&1 | tee -a "$LOG_FILE"
set -e
if grep -q '^SEVENZAP_RELAY_URL=' "$DO_ENV"; then
    sed -i 's|^SEVENZAP_RELAY_URL=.*|SEVENZAP_RELAY_URL=${NGROK_URL}|' "$DO_ENV"
else
    echo 'SEVENZAP_RELAY_URL=${NGROK_URL}' >> "$DO_ENV"
fi
pm2 restart parts-bot --update-env
echo "DO server updated to ${NGROK_URL}"
EOF

# ── 4. Save new URL ────────────────────────────────────────────────────────
echo "$NGROK_URL" > "$STATE_FILE"
log "Done."
