#!/usr/bin/env python3
"""Community feeds — temple/samaj YouTube uploads near Garodia Nagar.

  community_feeds.py [hours_back] [--asof "YYYY-MM-DDTHH:MM+05:30"]

YouTube channel pages are JS-rendered and unreadable, but the per-channel RSS feed is
plain XML with exact <published> timestamps. Instagram/Facebook remain unreadable
(captions never render / login wall), so YouTube + websites are the workable surface.
"""
import sys, re, json, urllib.request, datetime as dt

FEEDS = [
    {"org": "Ghatkopar Bhajan Samaj",
     "where": "90 Feet Rd, Garodia Nagar, Ghatkopar East (in-radius)",
     "channel_id": "UC5Qy6rpUFZ6GVQNH_Xasbdw",
     "site": "https://bhajansamaj.org/"},
    {"org": "Thiruchembur Murugan Temple / Sri Subramania Samaj",
     "where": "Chedda Nagar, Chembur (~3-4km, in-radius)",
     "channel_id": "UCY6krAvueN6UVLIUewA1n2w",
     "site": "https://www.youtube.com/@srisubramaniasamaj548",
     "note": "Live-streams most days; titles are generic 'is live'. Include AT MOST ONE per run, labelled as the daily stream."},
    {"org": "Shankaralayam Sanstha (Chedda Nagar) / Hariharaputra Samaj",
     "where": "Chedda Nagar, Chembur (~3-4km, in-radius)",
     "channel_id": "UCebsGuiyZlsYR1067Sp9VUA",
     "site": "https://shankaralayam.in/"},
]

def entries(cid):
    url = f"https://www.youtube.com/feeds/videos.xml?channel_id={cid}"
    try:
        x = urllib.request.urlopen(url, timeout=25).read().decode("utf-8", "replace")
    except Exception as e:
        return [{"error": str(e)}]
    out = []
    for m in re.findall(r"<entry>.*?</entry>", x, re.S):
        g = lambda p: (re.search(p, m, re.S).group(1) if re.search(p, m, re.S) else None)
        out.append({"title": g(r"<title>(.*?)</title>"),
                    "published": g(r"<published>(.*?)</published>"),
                    "url": g(r'<link rel="alternate" href="(.*?)"')})
    return out

def main():
    hours = 24
    asof = None
    args = sys.argv[1:]
    for i, a in enumerate(args):
        if a == "--asof" and i + 1 < len(args): asof = args[i + 1]
        elif a.isdigit(): hours = int(a)
    IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
    now = dt.datetime.fromisoformat(asof) if asof else dt.datetime.now(IST)
    cutoff = now - dt.timedelta(hours=hours)
    print(f"WINDOW: {cutoff:%Y-%m-%d %H:%M} -> {now:%Y-%m-%d %H:%M} IST\n")
    hits = 0
    for f in FEEDS:
        print(f"--- {f['org']}  [{f['where']}]")
        for e in entries(f["channel_id"])[:8]:
            if "error" in e: print("    FEED ERROR:", e["error"]); continue
            p = dt.datetime.fromisoformat(e["published"]).astimezone(IST)
            import re as _re
            generic = bool(_re.search(r"(?i)\bis live\b|live now|live stream|^\s*$", e["title"] or "")) \
                      or (e["title"] or "").strip().upper() == f.get("org","").upper()
            mark = "  IN-WINDOW ->" if cutoff <= p <= now else "              "
            if cutoff <= p <= now:
                hits += 1
                tag = "  [GENERIC-DROP]" if generic else ""
                print(f"{mark} {p:%d %b %H:%M IST}  {e['title']}{tag}\n                {e['url']}")
        print()
    print(f"TOTAL IN-WINDOW (youtube): {hits}")
    print()
    import urllib.request as u
    WP_SITES=[
        {"org":"Ghatkopar Bhajan Samaj (Garodia Nagar)", "host":"https://bhajansamaj.org"},
    ]
    for site in WP_SITES:
        print(f"--- {site['org']} FLYERS via WordPress media API ---")
        api=(f"{site['host']}/wp-json/wp/v2/media"
             "?per_page=25&orderby=date&order=desc&media_type=image")
        req=u.Request(api, headers={"User-Agent":"Mozilla/5.0 (Macintosh; Intel Mac OS X "
            "10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
            "Accept":"application/json"})
        try:
            items=json.loads(u.urlopen(req,timeout=25).read().decode("utf-8","replace"))
        except Exception as e:
            print("    media API failed:",e); print(); continue
        fresh=[]
        for m in items:
            try: up=dt.datetime.fromisoformat(m["date"]).replace(tzinfo=IST)
            except Exception: continue
            title=re.sub("<[^>]+>","",m.get("title",{}).get("rendered",""))
            tag="  NEW ->" if cutoff <= up <= now else "        "
            if cutoff <= up <= now: fresh.append(m)
            print(f"{tag} {up:%d %b %H:%M}  {title[:40]:<40} {m['source_url']}")
        print(f"    uploaded in window: {len(fresh)}")
        print()
    print("    ACTION: download each in-window flyer and READ IT AS AN IMAGE for the event")
    print("    dates. Dates live inside the artwork - never infer from a filename.")


main()
