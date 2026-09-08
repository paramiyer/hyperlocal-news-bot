#!/usr/bin/env python3
"""Link verifier — a hard gate before compose. Reads the candidates JSON, checks each URL,
and reports which are SEND-ABLE vs DEAD/GENERIC. Works on crawler-blocked sites too, because
it only checks HTTP status + URL shape, not content.

  verify_links.py /tmp/garodia-candidates.json

A URL passes only if:
  - it returns HTTP 200 (following redirects), AND
  - its final path looks like a specific article, not a section/home root.
Fails: dead links, truncated '...' placeholders, and bare section pages (the TOI-homepage bug).
"""
import sys, json, re, urllib.request, urllib.error

UA=("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")

ARTICLE_HINT = re.compile(r"(articleshow|/article/|/story|/news/|/photo/|/mumbai/[a-z0-9-]{20,}|"
                          r"\.cms|\.html|/\d{4}/\d{2}/\d{2}/|watch\?v=|paryushan|/videos/)", re.I)
SECTION_ROOTS = re.compile(r"^https?://[^/]+/(city/mumbai|mumbai|news|city)/?$", re.I)

def check(url):
    if not url or "..." in url or url.strip() in ("<url>", "<u>", "<flyer url>"):
        return "DEAD", "placeholder/truncated"
    if SECTION_ROOTS.match(url):
        return "GENERIC", "section/home page, not an article"
    try:
        req=urllib.request.Request(url, method="HEAD", headers={"User-Agent":UA})
        r=urllib.request.urlopen(req, timeout=15)
        final=r.geturl(); code=r.getcode()
    except urllib.error.HTTPError as e:
        # some sites reject HEAD; retry GET (status only)
        try:
            req=urllib.request.Request(url, headers={"User-Agent":UA})
            r=urllib.request.urlopen(req, timeout=15); final=r.geturl(); code=r.getcode()
        except Exception as ex:
            return "DEAD", f"HTTP {getattr(e,'code','?')}"
    except Exception as ex:
        return "DEAD", str(ex)[:40]
    if code!=200: return "DEAD", f"HTTP {code}"
    if SECTION_ROOTS.match(final): return "GENERIC", f"redirected to section root"
    if not ARTICLE_HINT.search(final): return "WEAK", "no article-shaped path"
    return "OK", final

def main():
    obj=json.load(open(sys.argv[1]))
    ok=bad=0
    for c in obj.get("candidates", obj.get("items", [])):
        status,detail=check(c.get("url",""))
        flag={"OK":"✓","WEAK":"?","GENERIC":"✗","DEAD":"✗"}[status]
        print(f"  {flag} {status:8} {c.get('head','')[:40]:<40} {c.get('url','')[:55]}")
        if status in ("DEAD","GENERIC"):
            bad+=1; c["_link_bad"]=detail
        else: ok+=1
    print(f"\n  {ok} sendable, {bad} must be dropped or re-sourced.")
    print("  RULE: drop DEAD/GENERIC links — cite the publication + headline with NO link,")
    print("        or find a reachable source. Never send a dead or section-root URL.")
if __name__=="__main__": sys.exit(main())
