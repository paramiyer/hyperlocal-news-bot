#!/usr/bin/env python3
"""Compose a WhatsApp brief from scored candidates. Live-pipeline renderer:
gather candidates -> scoring.score_candidates -> compose text.

  render_brief.py YYYY-MM-DD    # render that morning's 7 AM brief from its candidate set
"""
import sys, datetime as dt
import scoring
from scoring import TAX

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))

# ---- real candidate sets per morning (window = prior 24h to 07:00 IST) ----
# Each candidate: sector, source, dist_km, post_time or event_time, + render fields.
CANDIDATES = {
  # Illustrative only — real candidates are produced live by the discovery step (see SKILL.md)
  # and passed via `render_brief.py --json <file>`. Kept minimal for the repo.
  "2026-01-01": [
    {"sector":"safety","source":"free_press_journal","dist_km":0.5,
     "post_time":"2026-01-01T02:00:00+05:30","head":"Example local safety item",
     "body":"one-line summary","src":"Example Paper","url":"<url>"},
  ],
}



def emit_selected(day, ranked):
    """Write the selected items + fingerprints so record.py can persist them after send."""
    import json as _j, re as _re
    def slug(x): return _re.sub(r"[^a-z0-9]+","-",(x or "").lower()).strip("-")[:60]
    items=[]
    for st in ("news","community","religious","bright_spot"):
        for r in ranked.get(st, []):
            base=(r.get("event_time") or r.get("post_time") or "")[:10]
            fp=r.get("fp") or f"{r['sector']}|{slug(r.get('head'))}|{base}"
            items.append({"fp":fp,"sector":r["sector"],"head":r.get("head"),
                          "url":r.get("url",""),"org":r.get("org",""),
                          "event_time":r.get("event_time"),"post_time":r.get("post_time")})
    _j.dump({"day":day,"items":items}, open("/tmp/garodia-selected.json","w"), indent=2)



def _search_link(head, src=""):
    import urllib.parse as _up
    q=_up.quote(f"{head} {src}".strip())
    return f"https://www.google.com/search?q={q}"

def _good_url(u):
    if not u or "..." in u or u.strip() in ("<url>","<u>","<flyer url>",""): return False
    return u.startswith("http")

def compose(day, ranked):
    asof = dt.datetime.fromisoformat(f"{day}T07:00:00+05:30")
    d = asof.strftime("%-d %b %Y")
    L = [f"📍 GARODIA NAGAR — 24H LOCAL BRIEF", f"🗓 {d} | 7:00 AM IST | 📡 ~6 km", ""]
    # ORDER (Param 2026-09-09): COMMUNITY -> RELIGIOUS -> NEWS (bright spot stays with news)
    comm = ranked.get("community", [])
    if comm:
        L.append("🤝 COMMUNITY")
        for r in comm:
            emoji = TAX["sectors"][r["sector"]]["emoji"]
            line = f"• {emoji} {r['head']}"
            if r.get("body"): line += f" — {r['body']}"
            L.append(line)
            L.append(f"  {r['url'] if _good_url(r.get('url','')) else _search_link(r.get('head',''), r.get('src',''))}")
        L.append("")
    rel = ranked["religious"]
    if rel:
        L.append("🛕 RELIGIOUS")
        for r in rel:
            tag = "TODAY: " if (TAX["sectors"][r["sector"]].get("imminent") and r.get("event_time")) else ""
            line = f"• {r.get('org','?')} — {tag}{r['head']}"
            if r.get("body"): line += f", {r['body']}"
            L.append(line)
            L.append(f"  {r['url'] if _good_url(r.get('url','')) else _search_link(r.get('head',''), r.get('src',''))}")
        L.append("")
    L.append("📰 NEWS")
    news = ranked["news"]
    if not news:
        L.append("No significant verified local news found in the last 24 hours."); L.append("")
    for r in news:
        emoji = TAX["sectors"][r["sector"]]["emoji"]
        L.append(f"• {emoji} {r['head']}")
        if r.get("body"): L.append(r["body"])
        _u = r.get("url") if _good_url(r.get("url")) else _search_link(r.get("head",""), r.get("src",""))
        L.append(f"Source: {r['src']} — {_u}"); L.append("")
    bs = ranked["bright_spot"]
    for r in bs:
        L.append(f"• ✨ Bright Spot — {r['head']}");
        if r.get("body"): L.append(r["body"])
        _u = r.get("url") if _good_url(r.get("url")) else _search_link(r.get("head",""), r.get("src",""))
        L.append(f"Source: {r['src']} — {_u}"); L.append("")
    L.append("━━━━━━━━━━")
    L.append("Verified significant local news from the last 24 hrs only.")
    return "\n".join(L)


def render_from_json(path):
    """LIVE entry: read {"day":"YYYY-MM-DD","candidates":[...]} produced at runtime by the
    discovery step, score, and print the composed brief + trace."""
    import json
    obj = json.load(open(path)) if path != "-" else json.load(sys.stdin)
    day = obj["day"]
    asof = dt.datetime.fromisoformat(f"{day}T07:00:00+05:30")
    ranked, dropped = scoring.score_candidates(obj["candidates"], asof)
    emit_selected(day, ranked)
    _msg = compose(day, ranked)
    open('/tmp/garodia-message.txt','w').write(_msg)
    print(_msg)
    print(f"\n--- scoring trace ({day}) ---")
    for st in ["news","religious","bright_spot"]:
        for r in ranked[st]:
            print(f"  {r['score']:.3f} [{r['sector']:<12}] {r.get('head','')[:40]}")
    for r in dropped:
        print(f"  DROP {r['gate']:<28} {r.get('head','')[:40]}")


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--json":
        render_from_json(sys.argv[2] if len(sys.argv) > 2 else "-"); return
    day = sys.argv[1] if len(sys.argv) > 1 else "2026-09-06"
    asof = dt.datetime.fromisoformat(f"{day}T07:00:00+05:30")
    ranked, dropped = scoring.score_candidates(CANDIDATES[day], asof)
    emit_selected(day, ranked)
    _msg = compose(day, ranked)
    open('/tmp/garodia-message.txt','w').write(_msg)
    print(_msg)
    print(f"\n--- scoring trace ({day} 07:00) ---")
    for st in ["news","religious","bright_spot"]:
        for r in ranked[st]:
            print(f"  {r['score']:.3f} [{r['sector']:<12}] {r['head'][:40]}")
    for r in dropped:
        print(f"  DROP {r['gate']:<28} {r['head'][:40]}")


if __name__ == "__main__":
    main()
