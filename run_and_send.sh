#!/bin/bash
# Single scheduled job: compose fresh, hold to exactly 07:00 IST, send. No two-job race.
# Fires at 05:15 Dubai; if launchd wakes it early (~04:00), it still composes fresh, then
# HOLDS (machine kept awake) until 05:30 Dubai = 07:00 IST, then sends. Guarantees:
#   - content is a FRESH gather (compose runs at start of THIS job)
#   - send lands at 07:00 IST, not early (caffeinate-backed hold, honored, not ignored)
D=__BOT_DIR__
WRAPPER=__WA_MCP_DIR__/scripts/run_bot_with_retry.sh
SKILL=$D/SKILL.md ; MSG=/tmp/garodia-message.txt ; SEL=/tmp/garodia-selected.json
JID="__GROUP_JID__" ; LOG=/tmp/garodia-news.log
ALERT="__ALERT_JID__"
DAY=$(TZ=Asia/Kolkata date +%Y-%m-%d)
log(){ echo "[$(TZ=Asia/Dubai date '+%H:%M:%S') Dubai] run: $*" >>"$LOG"; }

# keep the Mac awake for this whole job (compose + hold + send)
caffeinate -i -s -w $$ & disown

# idempotency: already sent today?
if sqlite3 "$D/state.db" "select 1 from executions where execution_id='garodia-news-$DAY' and send_result like 'SUCCESS%';" | grep -q 1; then
  log "already sent today ($DAY) — exit."; exit 0; fi

# 1) FRESH compose (writes MSG + SEL). Stamp start so we can prove freshness.
STAMP=$(date +%s)
log "=== compose start ==="
rm -f "$MSG"
"$WRAPPER" \
  "COMPOSE ONLY. Read and follow $SKILL through step 8. render_brief.py writes $MSG and $SEL. Do NOT send. Print the message and BOT_RESULT: COMPOSED." \
  "$LOG" "Bash Read WebSearch WebFetch" "Garodia compose"

# 2) freshness: MSG must exist AND be newer than this job's start (a real gather, not a stale file)
if [ ! -s "$MSG" ] || [ "$(stat -f %m "$MSG")" -lt "$STAMP" ]; then
  log "NO FRESH message (compose failed or stale file). Alerting, NOT sending."
  curl -s -m10 -X POST http://localhost:8080/api/send -H 'Content-Type: application/json' \
   -d "{\"recipient\":\"$ALERT\",\"message\":\"⚠️ Garodia news: no fresh brief composed this morning — nothing sent. Check $LOG\"}" >>"$LOG" 2>&1
  exit 1
fi
log "fresh compose OK ($(stat -f %Sm "$MSG"))."

# 3) HOLD until exactly 05:30 Dubai = 07:00 IST (cap 200 min covers a ~04:00 early wake)
"$D/../wait_until.sh" 5 30 12000 >>"$LOG" 2>&1

# 4) SEND + record
BODY=$(python3 -c "import json;print(json.dumps({'recipient':'$JID','message':open('$MSG').read()}))")
RESP=$(curl -s -m20 -X POST http://localhost:8080/api/send -H 'Content-Type: application/json' -d "$BODY")
log "bridge: $RESP"
if echo "$RESP" | grep -q '"success":true'; then
  log "SENT at $(TZ=Asia/Kolkata date '+%H:%M IST')."
  [ -s "$SEL" ] && python3 "$D/record.py" --commit "$SEL" >>"$LOG" 2>&1
  echo "BOT_RESULT: SUCCESS" >>"$LOG"
else
  log "SEND FAILED. Alerting."
  curl -s -m10 -X POST http://localhost:8080/api/send -H 'Content-Type: application/json' \
   -d "{\"recipient\":\"$ALERT\",\"message\":\"⚠️ Garodia news failed to send. Check $LOG\"}" >>"$LOG" 2>&1
  exit 1
fi
