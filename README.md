# hyperlocal-news-bot

A self-running **hyperlocal news + community brief** for a WhatsApp group. Every morning it
sweeps local news, temple/community feeds and event listings within a small radius of one
neighbourhood, scores everything by distance + freshness + importance, and sends a compact
brief to a WhatsApp group at an exact time — unattended, from your own Mac.

Built and battle-tested for Garodia Nagar, Ghatkopar East, Mumbai. Everything locality-specific
lives in `taxonomy.json` + `config.env`, so you point it at your own area by editing config,
not code.

> ⚠️ **It runs on YOUR machine.** WhatsApp groups are end-to-end encrypted, so the bot can only
> send through your own logged-in WhatsApp session on your own computer. There is no cloud
> version — a cloud server cannot reach your WhatsApp. Your Mac must be awake (or asleep on
> power; it wakes itself) at send time.

---

## What it does

- **Scored discovery** — every candidate gets a 0–1 score from 4 layers (proximity, recency,
  local importance, source reliability), combined by tunable weights. No hand-picking.
- **Multi-sector** — news (crime, traffic, civic, utilities, weather alerts), religious
  (multiple communities), community (workshops, events), plus a positive "bright spot".
- **Smart dedup** — remembers what it sent (SQLite) so nothing repeats; multi-day events are
  announced once + a reminder near the date.
- **Link verification** — dead/section-page links are dropped and replaced with a Google
  search on the headline, so no bullet is ever a dead end.
- **Exact-time send** — composes early, holds, fires at your chosen minute.

---

## Architecture (11 files, 3 layers)

**Brain (config — edit these, not code):**
- `taxonomy.json` — sectors, weights, distance/time kernels, sources, caps, your locality's feeds
- `SKILL.md` — the natural-language instructions the AI follows each morning
- `config.env` — your secrets/paths (created from `config.example.env`, git-ignored)

**Workers (Python):**
- `scoring.py` — the scoring engine (normalized layers + weighted combine + hard gates)
- `render_brief.py` — turns scored candidates into the WhatsApp message
- `community_feeds.py` — polls temple/community YouTube RSS + WordPress media flyers
- `verify_links.py` — checks every URL resolves (works on crawler-blocked sites too)
- `record.py` — writes what was sent to `state.db` (the memory)

**Scheduler (shell + launchd):**
- `run_and_send.sh` — the single morning job: fresh compose → hold to send-time → send → record
- `wait_until.sh` — holds until an exact clock time (survives early wakes)
- `garodia-news.sh` — manual entrypoint: `--dry-run` (never sends), `--dry-run --asof "<ISO>"` (back-test)

`state.db` is a **SQLite** file (no server) — the bot's memory. It is git-ignored.

---

## Prerequisites & install

### 1. WhatsApp MCP bridge (the send path)
This is what actually talks to WhatsApp. Clone and run [whatsapp-mcp](https://github.com/lharries/whatsapp-mcp):
```bash
git clone https://github.com/lharries/whatsapp-mcp.git
cd whatsapp-mcp/whatsapp-bridge
go run main.go        # scan the QR code with WhatsApp on your phone (one time)
```
The Go **bridge** must stay running — it listens on `http://localhost:8080` and exposes
`POST /api/send {"recipient": "...", "message": "..."}`, which this bot calls directly.
It does **not** auto-start after reboot; relaunch it after a restart:
```bash
cd whatsapp-mcp/whatsapp-bridge && nohup ./main >/tmp/wa_bridge.log 2>&1 & disown
```
Requires **Go 1.21+** (`brew install go`).

### 2. Find your group JID
The bridge stores messages in SQLite. Find your group's JID:
```bash
sqlite3 whatsapp-mcp/whatsapp-bridge/store/messages.db \
  "select jid, name from chats where name like '%your group name%';"
```
Put the `...@g.us` value into `config.env` as `GROUP_JID`.

### 3. Python + dependencies
Python **3.11+**. The only third-party package is `openpyxl` (used only if you add xlsx sources);
core scoring/render/verify use the standard library.
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install openpyxl        # optional
```
`sqlite3` ships with macOS and Python — nothing to install.

### 4. Claude Code CLI (the "AI" that gathers + composes)
The morning job calls `claude -p` headless to run the sweeps and compose. Install the standalone CLI:
```bash
npm install -g @anthropic-ai/claude-code   # gives you /opt/homebrew/bin/claude
```
(You need an Anthropic account/login.)

### 5. Codex CLI (optional but recommended — reaches crawler-blocked news sites)
Many Indian news sites block automated crawlers. The bot uses [Codex](https://github.com/openai/codex)
to read them. Without it, you lose the blocked-outlet coverage but everything else still works.
```bash
brew install codex   # or per Codex's own install docs; then `codex login`
```

### 6. Configure
```bash
cp config.example.env config.env
$EDITOR config.env      # set BOT_DIR, GROUP_JID, ALERT_JID, ORIGIN_LAT/LON, send time
```
Then edit `taxonomy.json` → `origin` (your coordinates) and `religious_feeds` /
`discovery` (your locality's temples, YouTube channel IDs, event venues). The shipped values
are Ghatkopar East examples — replace them.

### 7. Initialise the memory DB
```bash
sqlite3 state.db "CREATE TABLE sent_stories (fingerprint TEXT PRIMARY KEY, canonical_url TEXT, headline TEXT, event_location TEXT, published_at TEXT, first_seen TEXT, last_seen TEXT, sent_at TEXT);
CREATE TABLE executions (execution_id TEXT PRIMARY KEY, executed_at TEXT, cutoff_at TEXT, candidates INT, excluded_24h INT, excluded_ts INT, excluded_geo INT, excluded_loc INT, duplicates INT, qualified INT, selected INT, destination TEXT, send_result TEXT, duration_s REAL);"
```

---

## Try it (never sends)
```bash
./garodia-news.sh --dry-run                                  # today, live gather, prints the brief
./garodia-news.sh --dry-run --asof "2026-09-08T07:00+05:30"  # back-test a specific morning
```

## Schedule it (macOS launchd)
1. `sudo pmset repeat wakeorpoweron MTWRFSU 05:10:00` — wake the Mac before the run (adjust time).
2. Create `~/Library/LaunchAgents/com.you.news.plist` firing `run_and_send.sh` a few minutes
   before your send time (it composes fresh, then holds to the exact minute).
3. `launchctl load` it. Keep the Mac plugged in; lid-closed is fine.

See `SKILL.md` for the full morning pipeline the AI follows.

---

## Tuning
Everything is in `taxonomy.json`:
- **weights** — how much distance vs freshness vs importance vs source matters
- **sectors** — add/remove categories, set their importance + time windows
- **sources** — reliability per outlet
- **caps** — max bullets per section

No code changes to retune — edit numbers, re-run `--dry-run`, see the effect.

---

## Honest limitations
- **WhatsApp-only content is unreachable** — blood requests, obituaries, private group posts.
  The bot only reads the open web + public feeds.
- **Some sites block deep-linking** (BookMyShow, a few papers) → those become Google-search links.
- **Elder/community camps** often live only on WhatsApp/noticeboards → sweeps will often be empty.
- Runs on one Mac; if it's fully powered off, nothing sends.

## License
Do what you like. No warranty. Be a good neighbour with it.
