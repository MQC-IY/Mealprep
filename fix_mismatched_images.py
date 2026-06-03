#!/usr/bin/env python3
"""
fix_mismatched_images.py
------------------------
Re-fetches Unsplash photos for recipes where the current image is a mismatch.
Run once; updates recipe_images.json in-place.
    python3 fix_mismatched_images.py
"""

import json, time, urllib.request, urllib.parse, os
from pathlib import Path

_env = Path(__file__).parent / ".env"
if _env.exists():
    for _l in _env.read_text().splitlines():
        if _l.startswith("UNSPLASH_ACCESS_KEY="):
            os.environ.setdefault("UNSPLASH_ACCESS_KEY", _l.split("=", 1)[1].strip())
ACCESS_KEY = os.environ.get("UNSPLASH_ACCESS_KEY", "")
if not ACCESS_KEY:
    raise SystemExit("Set UNSPLASH_ACCESS_KEY in .env or environment")

OUT = Path(__file__).parent / "recipe_images.json"

# Remaining mismatches — run 2 (after rate limit reset)
# 13 with better fallback queries + 35 that were rate-limited in run 1
FIXES = {
    "czech_svickova_chicken":       "roast beef cream gravy dumplings",
    "austrian_chicken_cream_stew":  "chicken cream stew pot cooked",
}


def fetch_photo(query: str):
    params = urllib.parse.urlencode({
        "query": query,
        "per_page": 1,
        "orientation": "landscape",
        "content_filter": "high",
    })
    req = urllib.request.Request(
        f"https://api.unsplash.com/search/photos?{params}",
        headers={"Authorization": f"Client-ID {ACCESS_KEY}", "Accept-Version": "v1"},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        remaining = int(resp.headers.get("X-Ratelimit-Remaining", 50))
        reset_ts  = int(resp.headers.get("X-Ratelimit-Reset", 0))
        data      = json.loads(resp.read())

    results = data.get("results", [])
    if not results:
        return None, remaining, reset_ts

    photo = results[0]
    return {
        "raw":        photo["urls"]["raw"],
        "credit":     photo["user"]["name"],
        "credit_url": photo["user"]["links"]["html"]
                      + "?utm_source=mahlzeit_app&utm_medium=referral",
    }, remaining, reset_ts


def main():
    existing = json.loads(OUT.read_text())
    total = len(FIXES)
    print(f"Re-fetching {total} mismatched images …\n")

    done = 0
    for recipe_id, query in FIXES.items():
        print(f"[{done+1}/{total}] {recipe_id:<45} '{query}' … ", end="", flush=True)
        try:
            result, remaining, reset_ts = fetch_photo(query)
            if result:
                existing[recipe_id] = result
                print(f"✓  (rate: {remaining} left)")
            else:
                print(f"✗  no result — keeping old")
        except urllib.error.HTTPError as e:
            if e.code == 429:
                import time as _t
                print(f"\n⏳ rate-limited — sleeping 3600s"); _t.sleep(3600)
                continue
            else:
                print(f"✗ HTTP {e.code}")
        except Exception as e:
            print(f"✗ {e}")

        OUT.write_text(json.dumps(existing, indent=2, ensure_ascii=False))
        done += 1
        time.sleep(2.5)

    print(f"\nDone. Updated {done}/{total} entries in {OUT}")


if __name__ == "__main__":
    main()
