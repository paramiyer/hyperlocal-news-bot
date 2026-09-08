---
name: garodia-news-whatsapp-bot
description: Send a hyperlocal 24h news digest (max 6 stories, ~6km around Garodia Nagar, Ghatkopar East) to the "__GROUP_NAME__" WhatsApp group. Runs daily at 07:00 Asia/Kolkata via a local launchd schedule (05:30 Asia/Dubai host time).
---

# Garodia Nagar 24h local brief -> WhatsApp

Config: `__BOT_DIR__/config.json`
State:  `__BOT_DIR__/state.db`

## Dry-run mode
If the prompt contains `DRY RUN`, execute every step EXCEPT step 9 (send).
Print the diagnostics block and the exact message that WOULD be sent. Never send.

## 0. Pre-flight
Call `mcp__whatsapp__list_chats(query: "__GROUP_NAME__")`. If the tool errors or is
unavailable, print `BOT_RESULT: FAILURE: whatsapp MCP not connected` and STOP —
don't spend search calls on a send that can't happen.

## 1. Time window (HARD CONSTRAINT)
```bash
TZ=Asia/Kolkata date "+%Y-%m-%d %H:%M"        # execution_time
TZ=Asia/Kolkata date -v-24H "+%Y-%m-%d %H:%M" # cutoff_time
TZ=Asia/Kolkata date "+%Y-%m-%d"              # execution_id date
```
`execution_id` = `garodia-news-YYYY-MM-DD` (IST date).
ALL window math uses Asia/Kolkata regardless of host timezone.

## 2. Idempotency
```sql
SELECT send_result FROM executions WHERE execution_id='garodia-news-YYYY-MM-DD';
```
If a row exists with `send_result='SUCCESS'`, print `BOT_RESULT: SUCCESS (already sent)` and STOP.

## 3. Discovery
Search across localities x topics. Localities: Garodia Nagar, Ghatkopar (E/W), Pant Nagar,
Vidyavihar, Jagruti Nagar, Asalpha, Saki Naka, Kurla, Tilak Nagar, Chembur, Vikhroli, Powai,
Chandivali. Topics: accident, crime, police, fire, traffic, BMC, civic, road, redevelopment,
demolition, Metro, railway, school, hospital, AND explicitly for the utilities/alerts
sectors: 'water cut' / 'water supply shutdown', 'power cut' / 'load shedding' / 'scheduled
outage', 'IMD warning' / 'red alert' / 'orange alert' / 'heavy rain' / 'waterlogging'.
Map results: water/power/outage -> sector `utilities`; weather warning/flooding -> `alerts`.

**Reachable sources only.** Use `allowed_domains: ["freepressjournal.in","lokmattimes.com"]`.
Do NOT query timesofindia / hindustantimes / indianexpress / mid-day / thehindu / ndtv —
they return a hard HTTP 400 (crawler blocked) and waste the call.
Also fetch the FPJ Mumbai index directly: https://www.freepressjournal.in/mumbai
(it renders per-story timestamps, which search results do not).

Official sites may be tried as primary sources, but as of 2026-09-01 these were dead ends:
BMC portal (broken SAP iView), Instagram (captions never render), Facebook (login wall),
X (HTTP 402). Don't burn more than one call each re-testing them.

## 4. Timestamp validation (HARD)
For EVERY surviving candidate, `WebFetch` the article and read its printed publish/update
time. NEVER trust a search-result date. Exclude if `published_or_updated_at < cutoff_time`
-> log `EXCLUDED_OUTSIDE_24H_WINDOW`. Exclude if the time can't be determined
-> log `EXCLUDED_TIMESTAMP_UNVERIFIED`. This step catches real traps: on 2026-09-01 a
Ghatkopar LBS Road crash looked current in search results and was actually 13 Sep 2025.
An old event qualifies ONLY on a genuinely material NEW development inside the window;
summarize only the new development.

## 5. Geography (HARD)
Event must have occurred within ~RADIUS_KM of your ORIGIN_LAT, ORIGIN_LON (from config.env). Use Haversine when coordinates
resolve; otherwise infer conservatively from locality/road/landmark/station/police
jurisdiction/BMC ward. A locality name merely APPEARING in the article is not enough —
on 2026-09-01 a "Ghatkopar businessman" extortion story actually occurred at Vakola,
Bandra East, and was correctly rejected. Unverifiable -> `EXCLUDED_LOCATION_UNVERIFIED`.

## 6. Dedupe (per-subject, scoped by signal_type)
fingerprint = `<sector>|<SPECIFIC-subject-slug>|<date>`. Fingerprint on what THIS bullet is
about, NOT the umbrella event it happened at. An award ceremony held at the Dahi Handi is its
OWN story (keyed on the honorees), separate from the Dahi Handi bullet — do not collapse it.

Scope the dedup check by signal_type: a `bright`/`community` candidate is compared ONLY against
prior rows of the same signal_type, never against a news bullet. This is what lets a positive
sub-story of an already-sent news event still reach the bright slot (fixed 2026-09-07 — it was
starving the bright slot before).

Still collapse TRUE duplicates — same subject, same facts, another outlet — to one, keeping the
strongest source. A previously-sent story returns only on a material new development. Set
`duplicate:true` on a candidate only when it fails THIS scoped, per-subject test.

## 7. Build candidates (discovery now EMITS objects, does not decide inclusion)
Steps 3-6 no longer rank or gate by hand. Each surviving item becomes a CANDIDATE object.
Everything from steps 4-6 (timestamp, geography, dedupe) is recorded AS FIELDS; the scorer
applies them, not you. Fields:
```json
{"sector":"safety|transport|civic|traffic|environment|events|property|business|
           rel_tambrahm|rel_jain|rel_vaishnav|bright",
 "source":"<key from taxonomy.json sources>",
 "dist_km": <haversine km from Garodia Nagar, or null if location unverifiable>,
 "post_time":"YYYY-MM-DDThh:mm:ss+05:30",   // for non-imminent sectors
 "event_time":"YYYY-MM-DDThh:mm:ss+05:30",  // for imminent sectors (transport/traffic/civic/rel_jain)
 "timestamp_verified": true|false,          // false => hard-dropped
 "duplicate": true|false,                   // true => hard-dropped (multi-day event already sent)
 "head":"<short headline>", "body":"<=2 concise lines", "src":"<publication>", "url":"<link>",
 "org":"<org, area>"                        // religious items only
}
```
Sector picks the emoji, resident-weight and recency window; source picks reliability — all
from `taxonomy.json`. Do NOT invent a source key; use one that exists (add to taxonomy via
config change if genuinely new).

Gather from every discovery leg — WebSearch/WebFetch (FPJ, Lokmat), Codex (blocked outlets),
`community_feeds.py` (temple YouTube + Bhajan Samaj flyers), the Parasdham search (7.5b below)
— and put them ALL in one candidates array. Over-include; the scorer drops what fails.

## 7.5 Religious feed candidates
Run `python3 community_feeds.py 24`. SKIP any item the helper marks `[GENERIC-DROP]` — a generic untitled livestream ('… is live') carries no program detail and is not newsworthy (per `taxonomy.religious_feeds.youtube_title_filter`). Each in-window TITLED YouTube item and each in-window Bhajan
Samaj flyer (read the image for the event) becomes a candidate with sector `rel_tambrahm`
(or `rel_vaishnav`), source = its org key, post_time = the item's timestamp.

## 7.5b Parasdham (Jain) — search-discovered, TWO touchpoints
Parasdham events live on `paramconnect.parasdham.org` (JS app, no feed) — DISCOVER by search.
Run the Codex query below; `WebFetch` each event URL to confirm date/venue/in-radius.
Emit a candidate: sector `rel_jain`, source `parasdham`, `event_time` = event START.

A real Jain event is announced TWICE, never daily (Param 2026-09-06):
- **Touchpoint 1 — announcement:** the first morning the event is discovered and no
  `parasdham|<slug>|<start>|announce` row exists in `sent_stories`. Include it; on send,
  write that key.
- **Touchpoint 2 — reminder:** fires the morning the event's ACTIONABLE deadline is within
  24h. The deadline = the arrival/registration close if the event page states one (Paryushan:
  "arrive by 6 PM on 7 Sep"), ELSE the event start. Anchor on the deadline, NOT a fixed
  48h-before-start — a residential shibir must surface on its arrival day, not a day early.
  Phrase it to the deadline ("arrive by 6 PM today" / "starts tomorrow"). Key `...|<start>|reminder`.
- **Between and after:** set `duplicate:true` so the scorer drops it.

The scorer keeps the event "valid" for up to 30 days out (horizon), but these two dedup keys
are what make it appear only twice. Worked example — Paryushan (starts 8 Sep): shows 4 Sep
(announce) and 6 Sep (reminder, arrival 6 PM that day), suppressed 5-6 Sep.
```bash
cd /tmp && codex exec --skip-git-repo-check "Search for Parasdham (Param Namramuni, Ghatkopar
East) events in the next 30 days. Check parasdham.org and paramconnect.parasdham.org. Give
event name, exact start date/time, venue, URL. If none, say NONE."
```

## 7.5c Vaishnav — search-discovered, TWO touchpoints (same as Jain)
No Vaishnav feed exists, so DISCOVER by search. Codex sweep, `WebFetch` to confirm
date/venue/in-radius. Emit candidate: sector `rel_vaishnav`, source = the org, `event_time`
= START. Same two-touchpoint dedup as Parasdham (announcement + eve-within-48h; keys
`vaishnav|<org>|<slug>|<start>|announce` and `|eve`).
```bash
cd /tmp && codex exec --skip-git-repo-check "Search for Vaishnav / Pushtimarg / Swaminarayan
events in the next 30 days within ~6km of Ghatkopar East Mumbai — Ghatkopar Haveli (Navnitpriyaji),
ISKCON Ghatkopar/Vidyavihar, BAPS Garodia Nagar, Vadtal Swaminarayan Pant Nagar, Sri Ahobila Mutt
Chembur, Balaji Mandir Rajawadi. Give event name, exact start date/time, venue, URL. If none, say NONE."
```

## 7.5d Community sweeps — workshops/fun events + elder health (were MISSING before 2026-09-08)
These two sectors had NO discovery wired. Run both Codex sweeps every morning; each result is a
candidate with the right sector, source, and (for dated events) `event_time` = START. Use the
same TWO-touchpoint dedup as religious events (announce + reminder within 24h of the deadline).

Fun events / workshops (sector `fun_events`):
```bash
cd /tmp && codex exec --skip-git-repo-check "Search for cultural events, workshops, talks, music/
drama shows or fun community activities in the next 30 days within ~6km of Ghatkopar East Mumbai —
check BookMyShow/Insider/Townscript for Ghatkopar venues (Zaverben Popatlal Sabhagraha, community
halls), and local listings. Give event name, exact date/time, venue, URL. If none, say NONE."
```
Elder health (sector `elder_health`):
```bash
cd /tmp && codex exec --skip-git-repo-check "Search for FREE or subsidised medical / eye / health
check-up camps for SENIOR CITIZENS in the next 30 days within ~6km of Ghatkopar East Mumbai —
by local hospitals (Rajawadi etc.), RWAs, Lions/Rotary clubs, senior-citizen associations. Give
camp name, exact date/time, venue, organiser, URL. If none, say NONE."
```
Both land in the 🤝 COMMUNITY section. If a sweep returns NONE, emit nothing for it (silent).

## 7.9 Verify every link (HARD — before compose)
Run the link checker on the candidates file:
```bash
python3 __BOT_DIR__/verify_links.py /tmp/garodia-candidates.json
```
For every candidate marked DEAD or GENERIC (dead link, truncated, or a bare section/home page
like `timesofindia.com/city/mumbai`):
1. Try to re-source a WORKING deep link (another outlet, the primary org page). If found, swap it in.
2. If none resolves, KEEP the story but blank its `url` — the composer then auto-substitutes
   a Google search link on the headline (`google.com/search?q=<headline> <publication>`), so the
   reader can still find it. NEVER send a dead or section-root URL.
Works on crawler-blocked sites too (status-only check). This closes the 2026-09-07 dead-link
defect where a bullet linked to the generic TOI Mumbai page instead of the article.

## 8. Score + compose (THE engine — no hand-ranking)
Write the candidates array to a temp file and run the scorer. It ranks within each
signal_type, applies caps, and composes the brief. You do NOT rank or format by hand.
```bash
python3 render_brief.py --json /tmp/garodia-candidates.json
```
with `/tmp/garodia-candidates.json` = `{"day":"<execution IST date>","candidates":[ ... ]}`.
The output above the `--- scoring trace ---` line IS the message to send (verbatim). The trace
is your diagnostics: report the per-candidate scores and every DROP line with its gate.

Header time: the composer prints `7:00 AM IST` for the scheduled run; it reflects the `day`.
Zero news candidates -> the composer already prints the header + "No significant verified
local news found in the last 24 hours." Nothing to hand-craft.

To retune behaviour, edit `taxonomy.json` (weights, sector windows, source reliability) —
never the code, never per-item rules here.

## 9. Final validation, then send
Before sending, assert ALL: selected <= 6; every story passed steps 4 and 5; every bullet
has category + source + URL; summaries <= 2 lines; message non-empty; destination JID is
`__GROUP_JID__` AND is in `config.allowlist` AND resolves to `__GROUP_NAME__`;
no prior SUCCESS row for this execution_id. If ANY assertion fails: DO NOT SEND.

`mcp__whatsapp__send_message(recipient: "__GROUP_JID__", message: <text>)`

## 10. Verify + record
`send_message` returning `{"success": true}` is the primary signal. Then check
`mcp__whatsapp__list_chats(query: "__GROUP_NAME__")`.

**KNOWN ISSUE — do not resend on failed verification.** Both `list_chats` and the bridge's
local `messages.db` have repeatedly failed to surface a just-sent outgoing message while the
send actually succeeded (documented in pr-digest-whatsapp-bot, and reproduced again on
2026-09-01 with this bot's own first send). One good-faith resend previously produced a real
visible duplicate in a group. If `send_message` returned success but verification can't
confirm it: print `BOT_RESULT: SUCCESS` and note verification was inconclusive. Only print
FAILURE if `send_message` ITSELF errored.

**Persist deterministically (do NOT hand-write SQL).** After a confirmed send, run:
```bash
python3 __BOT_DIR__/record.py --commit /tmp/garodia-selected.json
```
`render_brief.py` already wrote `/tmp/garodia-selected.json` (every selected item + its
fingerprint). This records the execution row AND a `sent_stories` row for EVERY selected
item — including the Parasdham announce/eve touchpoint keys — so tomorrow's dedup reads
the DB, never a remembered timeline. This closes the 2026-09-07 dedup-drift defect.
In a DRY RUN, run `record.py --dry` instead (shows rows, writes nothing).
Print the diagnostics block:
```
Candidates found / Outside 24h / Timestamp unverifiable / Outside radius /
Location unverifiable / Duplicates removed / Qualified / Selected
```
Then print the literal line `BOT_RESULT: SUCCESS` (the launchd wrapper greps for it).

## Schedule
launchd: `~/Library/LaunchAgents/com.param.garodia-news.plist`, fires **05:30 Asia/Dubai
host time = 07:00 IST**, daily. Wakes the Mac via `pmset repeat wakeorpoweron`.
**If the host timezone ever changes, the plist Hour/Minute MUST be recomputed** — launchd
uses host local time, not IST. All in-skill window math is already Asia/Kolkata-explicit.
Wrapper: `~/mcp-servers/whatsapp-mcp/scripts/run_bot_with_retry.sh` (restarts the Go bridge,
clears orphaned MCP processes, checks for the success marker, DMs Param on failure).
Logs: `/tmp/garodia-news.log`.

## Representative handles (MLA / MP) — NEWS ITEMS ONLY
Configured in `config.representatives`:
- **MLA, Ghatkopar East** — Parag Shah (BJP, since 2024)
- **MP, Mumbai North East** — Sanjay Dina Patil (Shiv Sena UBT, since 2024)
  (Garodia Nagar sits in Ghatkopar East, inside the Mumbai North East LS seat.)

**Currently DORMANT** — their handles are on Instagram/Facebook/X, all three unreachable
(captions don't render / login wall / HTTP 402, verified 2026-09-01). Do not waste calls
re-testing more than once per run. If an authenticated fetch path is ever added, activate
them as PRIMARY sources for civic announcements — but they are politicians' feeds, so the
**news-items-only** filter is mandatory and stricter than for a newspaper:

INCLUDE only a concrete civic/safety/infrastructure development a resident can act on or
must know (works sanctioned/started, road or water shutdown, relief measure, official order,
inaugurated facility with a real service change).

EXCLUDE festival greetings, birthday/anniversary wishes, condolences, campaign and
promotional content, event photo-ops with no civic outcome, party/opinion messaging, and
reposts carrying no new facts. An announcement still must pass the same 24h and 6km
guardrails, and needs a citable permalink — if there's no stable URL, exclude it.

## ⚠️ OUTPUT CONTRACT — READ LAST, OBEY ABSOLUTELY
The **final line** of your output MUST be exactly this, and nothing else:

BOT_RESULT: SUCCESS

Bare. No backticks, no bold, no quotes, no trailing punctuation, no prose after it.
The launchd wrapper greps for that exact line. If it is missing, the wrapper declares the
run FAILED and sends Param a false-alarm DM — even when the message was delivered
perfectly. This has happened twice (2026-09-02 backticks, 2026-09-03 marker omitted
entirely after a prose summary).

Write any commentary, diagnostics or caveats BEFORE that line. The marker is the last
thing you emit, every single run, without exception. Use `BOT_RESULT: FAILURE: <reason>`
instead only if the send itself errored.

## Delivery is CONFIRMED WORKING (settled 2026-09-04)
Param visually confirmed a bot-sent message arriving in the group. The bridge's send path
works. What does NOT work is verification: the bridge **never writes its own API-sent
messages back into `messages.db`**, so `list_chats` and the store can never show a message
this bot sent. That is structural, not a bug and not lag.

Therefore: treat `send_message` returning `{"success": true}` as delivery. Do NOT attempt
store-based verification, do NOT report "verification inconclusive", and NEVER resend.


## ⚠️ CORRECTION 2026-09-04 — two real misses, both now fixed

On 2026-09-04 this bot sent "no significant local news" while a **major road closure through
Ghatkopar was scheduled for the next day**. ChatGPT found it; this pipeline did not. Two
independent causes, both correctable:

### Cause 1 — the source list was far too narrow
Only `freepressjournal.in` + `lokmattimes.com` were being queried, on the false assumption
that everything else was crawler-blocked. Verified reachable, ADD THESE:
`mumbailive.com` (hyperlocal Mumbai, genuinely useful), `business-standard.com`,
`zeenews.india.com`, `scroll.in`, `theprint.in`, `dnaindia.com`, `deccanherald.com`.

Still hard-blocked (HTTP 400, do not query): timesofindia, hindustantimes, indianexpress,
mid-day, thehindu, ndtv, moneycontrol, economictimes, indiatoday, news18, abplive,
timesnownews, newindianexpress.

### Use Codex to reach the blocked outlets
Most Indian media is blocked to this crawler. The Codex CLI is installed and authenticated
and CAN read them. Run it as a research step every time:
```bash
cd /tmp && codex exec --skip-git-repo-check "Search the web. List local news items from the
last 24 hours, AND any scheduled disruptions taking effect in the next 48 hours, within ~6km
of Garodia Nagar / Ghatkopar East Mumbai. For each give: headline, what happened, exact
location, publication name, article URL, and exact publication date/time. Prioritise Mumbai
Traffic Police / BMC notifications. If nothing qualifies, say NONE."
```
Treat its output as CANDIDATES, not verified facts — it can be wrong. Cross-check the
timestamp and location before including anything, exactly as for any other candidate. It is
acceptable to cite a URL Codex found but this crawler cannot open, PROVIDED Codex reported a
specific publication, date and (for official notices) a notification number.

### Cause 2 — the 24h rule wrongly excluded a forward-looking advisory
The closure was announced 25 Aug for an event on 5 Sep. Strict "published within 24h" filters
that out — yet on 4 Sep it was the single most useful thing a resident could know.

**NEW RULE — imminent events qualify.** An item ALSO qualifies if it is a scheduled
disruption or event TAKING EFFECT within the next 48 hours, no matter when it was announced:
road closures and diversions, water cuts, power shutdowns, processions, protests, school or
exam closures, planned demolitions, rail/Metro blocks.
- For these, freshness means the EVENT is imminent, not that the article is new.
- Still enforce the 6km geography rule unchanged.
- Dedupe hard: send such an item at most twice — once when found, once on the eve. Record it
  in `sent_stories` keyed on the EVENT date so it does not repeat daily.
- The strict rolling-24h rule still applies to everything else (things that HAPPENED).

Log these as `QUALIFIED_IMMINENT_EVENT` in diagnostics, counted separately.

## ⚠️ CORRECTION 2026-09-06 — the photo-op filter was over-applied
The 6 Sep run logged `Excluded, no civic value: 1 (Bollywood stars at Ghatkopar Dahi Handi
— photo-op)` and thereby dropped **the Maharashtra CM attending a Dahi Handi in Ghatkopar
West** — thousands of Govindas, a full-day closure of the Andheri–Ghatkopar Link Road, and
billed as India's biggest. That was a genuine local headline.

Cause: `config.content_filter` ("exclude event photo-ops with no civic outcome") was written
for **the MLA/MP social feeds**, where photo-ops dominate. It was wrongly applied to news
coverage. It now lives at `config.representatives.feed_content_filter` and is scoped to
those feeds only.

**NEW RULE — `config.vip_presence_rule`.** A dignitary (CM, Deputy CM, Governor, Union
Minister, Municipal Commissioner, Mayor, local MLA/MP) physically present at an event INSIDE
the 6km radius is newsworthy in its own right. Do NOT discard it as a photo-op — especially
when it draws large crowds, triggers closures/diversions/security deployment, is a notably
large local event, or carries an announcement affecting the area.

Celebrity attendance alone, with no crowd, civic or traffic consequence, may still be
dropped — but say so in the diagnostics and name who, so the call is auditable.

General principle: when in doubt about civic value, INCLUDE it and let the ranking step
decide. Silent exclusion of a real local headline is a far worse failure than a marginal
bullet. Every exclusion under a "no civic value" judgement MUST be named in the diagnostics.

## ✨ BRIGHT SPOT — added 2026-09-06 after group feedback
Feedback from the group: the brief is genuinely useful but unrelentingly grim. That was
structural, not editorial — every high-ranked category in step 7 is a threat, accident or
disruption, and 🏪 Community/Business ranks 14th of 15, so it could never win a slot.

**Reserve ONE slot for a positive local story.** Composition is now:
- up to **5** hard-news bullets, ranked exactly as before (safety first — unchanged), plus
- up to **1** ✨ Bright Spot, placed LAST, after the hard news.
Total still capped at 6.

**Window: 72 hours for this slot only** — a deliberate, logged deviation from the strict
rolling-24h rule. Feel-good items are rare inside 6km and not time-critical; a 24h window
would leave the slot permanently empty. Every other bullet stays strictly 24h.
Geography (6km) applies unchanged. Log as `QUALIFIED_BRIGHT_SPOT`.

Qualifies: local sports or academic wins; a new park/library/clinic/playground opening; a
civic fix actually completed (road finished, bridge opened, flooding resolved); community
initiatives and clean-ups; local business milestones or awards; heritage restoration,
public art, greening; everyday decency — a rescue, a return, a neighbour helping.

NEVER: fabricate or inflate to fill the slot; recycle an old item to stay positive; spin a
tragedy as uplifting; use it for political promises. **If nothing genuine qualifies, leave
it out silently.** An empty slot is fine. An invented one destroys the brief's credibility,
which is the one thing keeping it worth reading.

Discovery: add positive terms to the sweep — "inaugurated", "opened", "wins", "award",
"felicitated", "topper", "completed", "restored", "renovated", "initiative", "drive",
"rescued", "reunited", "milestone", "anniversary" — across the same localities. Ask Codex
for positive local items explicitly; the default news flow surfaces almost none.

Format the bullet as:
`• ✨ Bright Spot — {headline}` with the same 2-line summary, source and URL rules.

### Bright spot radius — SETTLED 2026-09-06
The bright spot uses the SAME ~6km radius as hard news. Param explicitly declined widening
it. The slot will therefore be empty on most days — that is expected and correct. Never
widen the radius, never stretch a marginal item to fill it, and never re-propose widening.

### Bullet count — REVISED 2026-09-06
The bright spot must NOT displace a hard-news story. Composition is now:
- up to **6** hard-news bullets (the original cap, unchanged), plus
- up to **1** ✨ Bright Spot, additional, placed last.
So the maximum message is **7 bullets**. The "max 6" rule now governs HARD NEWS only.
Everything else is unchanged: still don't pad toward 6, fewer is still better than weak.

## 🛕 RELIGIOUS FEEDS — separate section, added 2026-09-06 (renamed from COMMUNITY)
Local temple/samaj feeds, as their OWN section — never mixed into the news ranking.
```bash
python3 __BOT_DIR__/community_feeds.py 24
```
Orgs: **Ghatkopar Bhajan Samaj** (90 Feet Rd, Garodia Nagar) and **Shankaralayam Sanstha,
Chedda Nagar / Hariharaputra Samaj** (Chembur). Both in-radius.

NAMING: Param's "Hariharapurta Samaj" = **Hariharaputra** Samaj, Mumbai — parent body of
Shankaralayam. NOT the Hariharapura Math in Karnataka; Codex conflated the two on 2026-09-06.

MECHANISM: YouTube channel pages are JS-rendered and unreadable. The per-channel **RSS feed**
is plain XML carrying exact `<published>` timestamps. Always use the helper. Instagram and
Facebook remain unreadable (captions never render / login wall).

RULES: strict 24h window on `<published>`. List plainly — org, what it is, time, link. No
ranking, no importance filtering: if the temple posted it, it goes in. These do NOT consume
a hard-news bullet or the bright-spot slot. If nothing is in window, omit the section
entirely rather than announcing its absence.

Format:
```
🛕 RELIGIOUS
• {Org} — {what it is}
  {link}
```

### Religious section — website event pages (added 2026-09-06)
Check both each run, but expect little:
- `https://bhajansamaj.org/upcoming-activities-2/` — events are IMAGE posters. Dates sit
  inside the images and are NOT machine-readable. **Never infer a date from a poster title.**
- `https://shankaralayam.in/upcoming-events` — readable text, but a static annual calendar
  (Dec-May) with no publication timestamps; not refreshed daily.

Include a website item ONLY if the page states a date falling in the window, or an event
happening today/tomorrow. Otherwise skip it silently. YouTube RSS remains the only surface
here with reliable per-item timestamps.

### Religious feeds — THREE temples + poster image-recognition (2026-09-06)
`community_feeds.py` now covers three in-radius temples:
- **Ghatkopar Bhajan Samaj** — Garodia Nagar — `UC5Qy6rpUFZ6GVQNH_Xasbdw`
- **Thiruchembur Murugan Temple / Sri Subramania Samaj** — Chedda Nagar — `UCY6krAvueN6UVLIUewA1n2w`
- **Shankaralayam Sanstha / Hariharaputra Samaj** — Chedda Nagar — `UCebsGuiyZlsYR1067Sp9VUA`

**Murugan temple live-streams most days** with generic "SRI SUBRAMANIA SAMAJ is live" titles.
Include AT MOST ONE per run, labelled as the daily stream, or it floods the section.

**POSTER IMAGE-RECOGNITION — mandatory for Bhajan Samaj.** Their entire calendar is inside
image posters; the page text carries no dates. On 2026-09-06 text scraping returned nothing
while reading the posters found *Asthapadi Bhajan, 06 September* — happening that day.
1. Fetch the events page with a full browser UA **and** Accept header (bare curl → HTTP 406).
2. Pull full-size `.jpeg` URLs under `/wp-content/uploads/` (skip `-400x284` thumbnails).
3. `HEAD` each for `Last-Modified` — that is the poster's publication timestamp.
4. **Download and READ each poster as an image** to extract the printed event dates.
5. Include an event if it is today/tomorrow, or the poster was published inside the window.

NEVER infer a date from a filename or title. `Gokulashtami-2026.jpeg` does not tell you when
Gokulashtami is. Read the image, or skip it.
