#!/usr/bin/env python3
"""Scored discovery engine for the Garodia Nagar brief.

Same shape as UC1 / branch scoring: each candidate is scored on normalized 0-1
layers (proximity, recency, sector relevance, source reliability), combined by
normalized weights, then ranked within its signal_type. Hard gates zero-out a
candidate before ranking. No per-source special-casing lives in code — it all
comes from taxonomy.json.

  scoring.py --demo            # score the real 2026-09-06 candidate set
  (importable: score_candidates(candidates, asof) -> ranked dict per signal_type)
"""
import json, math, sys, datetime as dt

HERE = "__BOT_DIR__"
TAX = json.load(open(f"{HERE}/taxonomy.json"))
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))


def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1); dl = math.radians(lon2 - lon1)
    a = math.sin(dp/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return 2 * R * math.asin(math.sqrt(a))


def k_proximity(dist_km):
    """linear falloff, 1.0 at 0km -> 0.0 at radius; hard-cut beyond."""
    r = TAX["kernels"]["proximity"]["radius_km"]
    if dist_km is None:      # location unverifiable -> hard gate handles it
        return 0.0
    if dist_km > r:
        return 0.0
    return 1.0 - (dist_km / r)


def k_recency(age_h, window_h, past_window_h=None):
    """linear decay, 1.0 at age 0 -> 0.0 at window. Upcoming events have
    negative age (event in the future); clamp those to full freshness.
    past_window_h (optional) gives the POSITIVE-age side its own, shorter cutoff:
    used for imminent event_time items so a past 'today' event goes stale fast
    instead of lingering the full (future) window. Defaults to window_h."""
    if age_h is None:
        return 0.0
    if age_h < 0:            # event hasn't happened yet -> maximally 'fresh'
        return 1.0 if -age_h <= window_h else 0.0
    pw = window_h if past_window_h is None else past_window_h
    if pw <= 0 or age_h > pw:
        return 0.0
    return 1.0 - (age_h / pw)


def _norm_weights():
    w = TAX["weights"]; keys = ["proximity", "recency", "sector_relevance", "source_reliability"]
    tot = sum(w[k] for k in keys)
    return {k: w[k]/tot for k in keys}


def score_one(c, asof):
    """c: dict with sector, source, dist_km, and either post_time or event_time (ISO IST).
    Returns (composite 0-1, layer breakdown, gated_reason or None)."""
    sec = TAX["sectors"][c["sector"]]
    src = TAX["sources"].get(c["source"], {"reliability": 0.4})
    window = sec["recency_window_h"]
    past_window = None      # positive-age cutoff; set for imminent events so a past event decays fast

    # recency: announce_once = a real upcoming event, fresh across a long lead window until
    # it is sent once (dedup then suppresses). imminent = measured from event start (short
    # window). others = measured from post time.
    if sec.get("announce_once") and c.get("event_time"):
        t = dt.datetime.fromisoformat(c["event_time"])
        age_h = (asof - t).total_seconds() / 3600.0   # negative = upcoming
        window = sec.get("horizon_h", window)          # 30-day sanity bound; the two
        # touchpoints (announcement + eve-within-48h) are enforced by the discovery step
        # via per-touchpoint dedup keys, not by the recency kernel.
    elif sec.get("imminent") and c.get("event_time"):
        t = dt.datetime.fromisoformat(c["event_time"])
        age_h = (asof - t).total_seconds() / 3600.0
        # PAST-EVENT GATE: upcoming events keep the full window; once STARTED (positive age) an
        # imminent event stays fresh only imminent_past_grace_h (6h), then gates. Mirrors the 24h
        # post cap so a "happening today" event can't linger up to 48h after it's over (e.g. a
        # protest 14h past resurfacing as "protest today"). announce_once is untouched.
        past_window = TAX["kernels"]["recency"].get("imminent_past_grace_h", 6)
    elif c.get("post_time"):
        t = dt.datetime.fromisoformat(c["post_time"])
        age_h = (asof - t).total_seconds() / 3600.0
        # HARD news-freshness cap: a post_time REPORT on the news signal_type is stale past
        # news_post_max_age_h (24h), even if its sector carries a longer window. The 48h on the
        # imminent sectors (transport/civic/traffic/alerts/utilities) is only for UPCOMING events
        # reached via event_time above — not for old reports. Without this, a 25-48h-old report
        # slipped through; the 24h cut used to be enforced by hand in SKILL step 4 only.
        if sec["signal_type"] == "news":
            cap = TAX["kernels"]["recency"].get("news_post_max_age_h", 24)
            window = min(window, cap)
    else:
        age_h = None

    layers = {
        "proximity":          k_proximity(c.get("dist_km")),
        "recency":            k_recency(age_h, window, past_window),
        "sector_relevance":   sec["resident_weight"],
        "source_reliability": src["reliability"],
    }

    # hard gates -> drop
    if not c.get("timestamp_verified", True):  return 0.0, layers, "EXCLUDED_TIMESTAMP_UNVERIFIED"
    if layers["proximity"] == 0.0:             return 0.0, layers, "EXCLUDED_OUTSIDE_RADIUS_OR_LOC"
    if layers["recency"] == 0.0:               return 0.0, layers, "EXCLUDED_OUTSIDE_WINDOW"
    if c.get("duplicate"):                     return 0.0, layers, "EXCLUDED_DUPLICATE"

    W = _norm_weights()
    composite = sum(W[k] * layers[k] for k in W)
    return composite, layers, None



def _venue_key(c):
    import re as _re
    v = c.get("venue") or ""
    if not v:
        h = (c.get("head","") or "") + " " + (c.get("body","") or "")
        m = _re.search(r"\bat ([A-Z][^,.;\n]+)", h)
        v = m.group(1) if m else (c.get("head","") or "")
    return _re.sub(r"[^a-z0-9]+","-", v.lower()).strip("-")[:40]

def score_candidates(candidates, asof):
    """Score all, group by signal_type, rank, apply caps."""
    out = {st: [] for st in TAX["signal_types"]}
    dropped = []
    for c in candidates:
        comp, layers, gate = score_one(c, asof)
        st = TAX["sectors"][c["sector"]]["signal_type"]
        rec = {**c, "score": round(comp, 4), "layers": {k: round(v, 3) for k, v in layers.items()}, "gate": gate}
        if gate:
            dropped.append(rec)
        else:
            out[st].append(rec)
    for st, cfg in TAX["signal_types"].items():
        out[st].sort(key=lambda r: r["score"], reverse=True)
        mpv = cfg.get("max_per_venue")
        if mpv:
            seen = {}
            kept = []
            for r in out[st]:
                vk = _venue_key(r)
                if seen.get(vk, 0) >= mpv:
                    r["gate"] = "CAPPED_VENUE_DIVERSITY"; dropped.append(r); continue
                seen[vk] = seen.get(vk, 0) + 1
                kept.append(r)
            out[st] = kept
        out[st] = out[st][:cfg["cap"]]
    return out, dropped


# ---- demo: the real 2026-09-06 07:00 candidate set ----
DEMO = [
    {"title": "CSMT-Vidyavihar megablock today 10:55-15:55", "sector": "transport",
     "source": "central_railway", "dist_km": 1.2, "event_time": "2026-09-06T10:55:00+05:30"},
    {"title": "13 injured Govindas treated at Rajawadi", "sector": "environment",
     "source": "free_press_journal", "dist_km": 1.0, "post_time": "2026-09-06T00:30:00+05:30"},
    {"title": "CM Fadnavis at Ghatkopar W Dahi Handi", "sector": "events",
     "source": "free_press_journal", "dist_km": 2.0, "post_time": "2026-09-05T18:20:00+05:30"},
    {"title": "Kurla-BKC pod taxi crosses 100 piles", "sector": "civic",
     "source": "free_press_journal", "dist_km": 4.5, "post_time": "2026-09-05T21:00:00+05:30"},
    {"title": "Powai SIM-dealer arrest (admission scam)", "sector": "safety",
     "source": "free_press_journal", "dist_km": 5.2, "post_time": "2026-09-05T20:00:00+05:30"},
    {"title": "LBS Rd drunk-driving custody", "sector": "safety",
     "source": "free_press_journal", "dist_km": 1.5, "post_time": "2025-09-17T05:57:00+05:30",
     "timestamp_verified": True},   # 1yr old -> recency kernel zeroes it
    {"title": "Paryushan Sadhana Shibir 8-15 Sep", "sector": "rel_jain",
     "source": "parasdham", "dist_km": 0.9, "event_time": "2026-09-08T06:00:00+05:30"},
    {"title": "Shankaralayam Janmashtami Mahotsav (YouTube)", "sector": "rel_tambrahm",
     "source": "shankaralayam", "dist_km": 3.5, "post_time": "2026-09-05T09:07:00+05:30"},
    {"title": "Murugan temple daily live stream", "sector": "rel_tambrahm",
     "source": "murugan_temple", "dist_km": 3.5, "post_time": "2026-09-05T07:51:00+05:30"},
    {"title": "Tilak Marg BMC school inauguration", "sector": "bright",
     "source": "free_press_journal", "dist_km": 2.2, "post_time": "2026-08-16T10:00:00+05:30"},  # >72h
]


def main():
    asof = dt.datetime.fromisoformat("2026-09-06T07:00:00+05:30")
    ranked, dropped = score_candidates(DEMO, asof)
    for st in ["news", "religious", "bright_spot"]:
        cap = TAX["signal_types"][st]["cap"]
        print(f"\n=== {st.upper()}  (cap {cap}) ===")
        for r in ranked[st]:
            L = r["layers"]
            print(f"  {r['score']:.3f}  [{r['sector']:<12}] {r['title'][:44]}")
            print(f"         prox={L['proximity']} rec={L['recency']} "
                  f"sect={L['sector_relevance']} src={L['source_reliability']}")
    print("\n=== DROPPED (hard-gated) ===")
    for r in dropped:
        print(f"  {r['gate']:<32} {r['title'][:44]}")


if __name__ == "__main__":
    main()
