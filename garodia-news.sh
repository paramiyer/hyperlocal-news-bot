#!/bin/bash
# Garodia Nagar 24h local brief -> WhatsApp.
#   ./garodia-news.sh                          # live run (sends)
#   ./garodia-news.sh --dry-run                # full pipeline, prints preview, never sends
#   ./garodia-news.sh --dry-run --asof "2026-09-06T07:00+05:30"
#                                              # dry run pinned to a specific IST moment,
#                                              # for like-for-like testing of the 7 AM brief
SKILL=__BOT_DIR__/SKILL.md
WRAPPER=__WA_MCP_DIR__/scripts/run_bot_with_retry.sh
TOOLS="Bash Read WebSearch WebFetch mcp__whatsapp__list_chats mcp__whatsapp__send_message"

# Hold until the real scheduled time if launchd fired us early (see wait_until.sh).
[ "${1:-}" = "--dry-run" ] || __BOT_PARENT__/wait_until.sh 5 30 || exit 1

if [ "${1:-}" = "--dry-run" ]; then
  ASOF=""
  if [ "${2:-}" = "--asof" ] && [ -n "${3:-}" ]; then
    ASOF="

PINNED CLOCK — this is a back-test. Treat the current moment as EXACTLY ${3} (Asia/Kolkata).
Compute execution_time, the 24h cutoff, the 72h bright-spot cutoff, execution_id and the
header date/time FROM THIS PINNED MOMENT, not the real wall clock. When you run
community_feeds.py, pass it: --asof \"${3}\". Ignore the idempotency check for this back-test
(state.db reflects the real timeline, not this pinned one) but say what it WOULD have done."
  fi
  exec /opt/homebrew/bin/claude -p \
    "DRY RUN. Read and follow the instructions in $SKILL to build today's Garodia Nagar digest. Execute every step EXCEPT the send. Print the diagnostics block and the exact message that would be sent.${ASOF}" \
    --allowedTools "$TOOLS" --permission-mode dontAsk
fi

# Scheduled COMPOSE phase (phase A): build the brief, write /tmp/garodia-message.txt +
# /tmp/garodia-selected.json, do NOT send. send_at_seven.sh fires it at exactly 07:00 IST.
if [ "${1:-}" = "--compose" ]; then
  exec "$WRAPPER" \
    "COMPOSE ONLY. Read and follow $SKILL through step 8 (score + compose). render_brief.py writes /tmp/garodia-message.txt and /tmp/garodia-selected.json. Do the idempotency check (step 2). DO NOT run step 9 send and DO NOT send_message — a separate job fires the message at 07:00 IST exactly. Print the composed message and BOT_RESULT: COMPOSED." \
    "/tmp/garodia-news.log" "Bash Read WebSearch WebFetch" "Garodia compose"
fi

exec "$WRAPPER" \
  "Read and follow the instructions in $SKILL to send today's Garodia Nagar local news digest. Referenced by absolute path because WorkingDirectory is /tmp — read the file directly and execute its steps." \
  "/tmp/garodia-news.log" \
  "$TOOLS" \
  "Garodia news digest"
