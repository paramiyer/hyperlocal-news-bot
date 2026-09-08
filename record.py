#!/usr/bin/env python3
"""Deterministic write path for state.db — closes the dedup-drift defect.

Every SELECTED item that is actually sent MUST be recorded here, with a stable
fingerprint, so the next morning's dedup sees it. The old prose-SQL step under-recorded
(no parasdham rows, partial news rows) and dedup silently leaned on the skill's timeline
instead of the DB. This makes the write complete and idempotent.

  record.py --dry    /tmp/garodia-selected.json   # print rows that WOULD be written
  record.py --commit /tmp/garodia-selected.json   # write execution row + sent_stories rows

selected.json = {"day":"YYYY-MM-DD","execution":{...counts...},
                 "items":[{fp, head, url, location, when, ...}, ...]}
Each item's `fp` is the stable fingerprint the discovery step computed and deduped on.
If `fp` is missing, one is derived from sector+head+date (last-resort; discovery should set it).
"""
import sys, json, re, sqlite3

DB = "__BOT_DIR__/state.db"


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")[:60]


def fingerprint(it):
    if it.get("fp"):
        return it["fp"]
    # last-resort deterministic key: sector | head-slug | date
    date = (it.get("event_time") or it.get("post_time") or "")[:10]
    return f"{it.get('sector','?')}|{slug(it.get('head'))}|{date}"


def main():
    if len(sys.argv) < 3 or sys.argv[1] not in ("--dry", "--commit"):
        print(__doc__); return 1
    mode, path = sys.argv[1], sys.argv[2]
    obj = json.load(open(path))
    day = obj["day"]
    ex = obj.get("execution", {})
    rows = []
    for it in obj["items"]:
        fp = fingerprint(it)
        rows.append((fp, it.get("url", ""), it.get("head", ""),
                     it.get("location", it.get("org", "")),
                     it.get("event_time") or it.get("post_time") or "",
                     day, day, f"{day} (sent)"))
    exec_row = (f"garodia-news-{day}", f"{day} 07:00 IST",
                ex.get("cutoff", ""), ex.get("candidates", 0), ex.get("excluded_24h", 0),
                ex.get("excluded_ts", 0), ex.get("excluded_geo", 0), ex.get("excluded_loc", 0),
                ex.get("duplicates", 0), ex.get("qualified", 0), ex.get("selected", len(rows)),
                "__GROUP_JID__", "SUCCESS", ex.get("duration_s", 0))

    if mode == "--dry":
        print(f"WOULD WRITE — execution: garodia-news-{day}  selected={len(rows)}")
        for r in rows:
            print(f"  sent_stories: {r[0]}")
        print("  (no DB write; --commit to persist)")
        return 0

    con = sqlite3.connect(DB); cur = con.cursor()
    cur.execute("INSERT OR REPLACE INTO executions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", exec_row)
    cur.executemany("INSERT OR REPLACE INTO sent_stories VALUES (?,?,?,?,?,?,?,?)", rows)
    con.commit(); con.close()
    print(f"COMMITTED — execution garodia-news-{day} + {len(rows)} sent_stories rows.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
