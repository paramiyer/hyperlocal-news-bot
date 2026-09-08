#!/bin/bash
# wait_until.sh HH MM [max_early_seconds]
# launchd has repeatedly fired these jobs EARLY — right after a system wake rather than at
# the scheduled time (news 04:02 vs 05:30, tennis 05:36 vs 07:00, observed 2026-09-02..04).
# Exiting on an early fire would skip the day entirely, since launchd won't re-fire until
# the next occurrence. So we sleep the difference instead: early fires land on time, late
# fires (machine asleep through the slot) still run immediately.
TH="$1"; TM="$2"; MAX="${3:-10800}"
now=$(date +%s)
target=$(date -j -f "%Y-%m-%d %H:%M:%S" "$(date +%Y-%m-%d) ${TH}:${TM}:00" +%s 2>/dev/null) || exit 0
delta=$(( target - now ))
if [ "$delta" -gt 0 ]; then
  if [ "$delta" -gt "$MAX" ]; then
    echo "[guard] fired ${delta}s early — beyond ${MAX}s cap, refusing to run at $(date '+%H:%M')."
    exit 1
  fi
  echo "[guard] fired $(( delta / 60 ))m early at $(date '+%H:%M') — sleeping until ${TH}:${TM}."
  sleep "$delta"
  echo "[guard] resumed at $(date '+%H:%M')."
else
  echo "[guard] running at $(date '+%H:%M'), $(( -delta / 60 ))m after the ${TH}:${TM} slot."
fi
