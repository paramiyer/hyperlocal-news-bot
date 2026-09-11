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

# 1) FRESH compose (writes MSG + SEL). Retry once after the usage-limit reset if we hit it.
_compose(){
  STAMP=$(date +%s); rm -f "$MSG"
  _pre=$(wc -l <"$LOG" | tr -d ' ')      # log line count before this compose
  "$WRAPPER" \
    "COMPOSE ONLY. Read and follow $SKILL through step 8. render_brief.py writes $MSG and $SEL. Do NOT send. Print the message and BOT_RESULT: COMPOSED." \
    "$LOG" "Bash Read WebSearch WebFetch" "Garodia compose"
}
_is_fresh(){ [ -s "$MSG" ] && [ "$(stat -f %m "$MSG")" -ge "$STAMP" ]; }
_hit_limit(){ tail -n +"$((_pre+1))" "$LOG" | grep -qiE "hit your (usage|session) limit|resets [0-9]"; }

log "=== compose start ==="
_compose
if ! _is_fresh && _hit_limit; then
  # RETRY-AFTER-RESET (added 2026-09-11): a quota limit at ~03:46 (before the 4:40 reset)
  # used to lose the whole day. Wait until the reset time printed in the log, +5 min, then
  # retry compose ONCE. Bounded to 90 min so a bad parse can't hang the job past the send.
  WAKE=$(python3 -c "
import re,datetime as dt
txt=open('$LOG').read()
m=re.findall(r'resets (\d{1,2}):(\d{2})\s*(am|pm)?', txt, re.I)
tz=dt.timezone(dt.timedelta(hours=4)); now=dt.datetime.now(tz)
if m:
    h,mn,ap=m[-1]; h=int(h)%12+(12 if (ap or '').lower()=='pm' else 0)
    t=now.replace(hour=h,minute=int(mn),second=0,microsecond=0)
    if t<=now: t+=dt.timedelta(days=1)
    wait=int((t-now).total_seconds())+300
else:
    wait=3600
print(max(60,min(wait,5400)))
")
  log "compose hit the usage limit — waiting ${WAKE}s for reset, then ONE retry."
  sleep "$WAKE"
  log "=== compose retry (post-reset) ==="
  _compose
fi

# 2) freshness gate — after any retry
if ! _is_fresh; then
  log "NO FRESH message (compose failed / still limited). Alerting, NOT sending."
  curl -s -m10 -X POST http://localhost:8080/api/send -H 'Content-Type: application/json' \
   -d "{\"recipient\":\"$ALERT\",\"message\":\"⚠️ Garodia news: no fresh brief composed this morning (compose failed or quota still out after retry) — nothing sent. Check $LOG\"}" >>"$LOG" 2>&1
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
