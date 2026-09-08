#!/bin/bash
# Phase B: fire the pre-composed brief at EXACTLY 07:00 IST (05:30 Asia/Dubai host time).
# Phase A (compose) ran ~15 min earlier and left /tmp/garodia-message.txt + selected.json.
MSG=/tmp/garodia-message.txt
SEL=/tmp/garodia-selected.json
JID="__GROUP_JID__"
LOG=/tmp/garodia-news.log
DAY=$(TZ=Asia/Kolkata date +%Y-%m-%d)
log(){ echo "[$(date '+%H:%M:%S')] send: $*" >>"$LOG"; }

# hold until exactly 05:30 Dubai (07:00 IST); if we're already past it, send now
__BOT_PARENT__/wait_until.sh 5 30 900 >>"$LOG" 2>&1

# freshness: message must exist and be from today's compose
if [ ! -s "$MSG" ]; then log "no message file — compose phase failed. Alerting."; 
  curl -s -m10 -X POST http://localhost:8080/api/send -H 'Content-Type: application/json' \
   -d "{\"recipient\":\"__ALERT_JID__\",\"message\":\"⚠️ Garodia news: compose phase produced no message this morning. Check $LOG\"}" >>"$LOG" 2>&1
  exit 1; fi
if ! grep -q "$(TZ=Asia/Kolkata date '+%-d %b %Y')" "$MSG"; then
  log "message file is stale (not today). Refusing to send."; exit 1; fi

# idempotency: don't double-send if already recorded today
if sqlite3 __BOT_DIR__/state.db \
   "select 1 from executions where execution_id='garodia-news-$DAY' and send_result like 'SUCCESS%';" | grep -q 1; then
  log "already sent today ($DAY). Skipping."; exit 0; fi

# send via bridge REST (same path the failure-alert uses; parse success from body)
BODY=$(python3 -c "import json,sys;print(json.dumps({'recipient':'$JID','message':open('$MSG').read()}))")
RESP=$(curl -s -m20 -X POST http://localhost:8080/api/send -H 'Content-Type: application/json' -d "$BODY")
log "bridge response: $RESP"
if echo "$RESP" | grep -q '"success":true'; then
  log "SENT at $(TZ=Asia/Kolkata date '+%H:%M IST')."
  [ -s "$SEL" ] && python3 __BOT_DIR__/record.py --commit "$SEL" >>"$LOG" 2>&1
  echo "BOT_RESULT: SUCCESS" >>"$LOG"
else
  log "SEND FAILED. Alerting Param."
  curl -s -m10 -X POST http://localhost:8080/api/send -H 'Content-Type: application/json' \
   -d "{\"recipient\":\"__ALERT_JID__\",\"message\":\"⚠️ Garodia news failed to send at 7 AM. Check $LOG\"}" >>"$LOG" 2>&1
  exit 1
fi
