#!/usr/bin/env python3
"""
fetch_calories.py
-----------------
Fetches per-person calorie data from Edamam Nutrition Analysis API for all recipes.
→ recipe_calories.json  {recipe_id: kcal_per_person}

Resumable: skips already-fetched IDs (including those that returned None).
Rate-aware: 1.5 s between requests; on 429 sleeps until next reset.

Run:
    pip install pyyaml   # (once, if not installed)
    python3 fetch_calories.py
"""

import json, time, urllib.request, urllib.parse, urllib.error
from pathlib import Path

import yaml

# ── Credentials ────────────────────────────────────────────────────────────────
APP_ID  = "5b7aa509"
APP_KEY = "bf657c02b4218ff791187fc9c6f77f13"
API_URL = "https://api.edamam.com/api/nutrition-details"

# ── Paths / config ─────────────────────────────────────────────────────────────
RECIPES_DIR = Path(__file__).parent / "recipes"
OUT         = Path(__file__).parent / "recipe_calories.json"
SERVINGS    = 4      # every batch feeds 4 adults
REQUEST_GAP = 1.5    # seconds between requests (stay well under free-tier limits)

# ── German unit → English ──────────────────────────────────────────────────────
UNIT_MAP = {
    "g":       "g",
    "ml":      "ml",
    "EL":      "tbsp",
    "TL":      "tsp",
    "Stk":     "",        # piece — en_name carries the noun
    "Zehen":   "",        # garlic "cloves" already in en_name
    "Zehe":    "",        # singular
    "Bund":    "bunch",
    "Dose":    "can",
    "Dosen":   "cans",
    "Glas":    "jar",
    "Stange":  "stalk",
    "Stangen": "stalks",
    "Liter":   "liter",
    "cm":      "cm",
    "Prise":   "pinch",
    "Packung": "package",
}


def ing_str(ing: dict) -> str:
    """Format one ingredient dict as a string Edamam's parser understands."""
    qty  = ing.get("qty", 1)
    unit = ing.get("unit", "")
    name = ing.get("en_name") or ing.get("de_name", "")

    unit_en = UNIT_MAP.get(unit, unit)

    if unit in ("g", "ml"):
        return f"{qty}{unit_en} {name}"   # e.g. "900g chicken thighs"
    elif unit_en:
        return f"{qty} {unit_en} {name}"  # e.g. "2 tbsp soy sauce"
    else:
        return f"{qty} {name}"            # e.g. "3 garlic cloves"


def fetch_calories(title_en: str, ingr: list) -> int | None:
    """POST recipe to Edamam; return total kcal for the whole batch or None."""
    body   = json.dumps({"title": title_en, "ingr": ingr}).encode()
    params = urllib.parse.urlencode({
        "app_id":          APP_ID,
        "app_key":         APP_KEY,
        "nutrition-type":  "cooking",
    })
    req = urllib.request.Request(
        f"{API_URL}?{params}",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = json.loads(resp.read())

    # Sum ENERC_KCAL across all parsed ingredient entries
    total = 0.0
    for ing in data.get("ingredients", []):
        for parsed in ing.get("parsed", []):
            total += parsed.get("nutrients", {}).get("ENERC_KCAL", {}).get("quantity", 0)
    return round(total) if total else None


def load_recipes() -> list:
    recipes = []
    for path in sorted(RECIPES_DIR.glob("*.yaml")):
        with open(path, encoding="utf-8") as f:
            recipe = yaml.safe_load(f)
        recipes.append(recipe)
    return recipes


def main():
    existing: dict = {}
    if OUT.exists():
        existing = json.loads(OUT.read_text())

    # Skip IDs already attempted (including None = API returned nothing)
    recipes  = load_recipes()
    to_fetch = [r for r in recipes if r["id"] not in existing]
    total    = len(to_fetch)

    print(f"Already fetched : {len(existing)}")
    print(f"Need to fetch   : {total} recipes")
    if not total:
        print("Nothing to do.")
        return

    done = 0
    for recipe in to_fetch:
        rid      = recipe["id"]
        title_en = (recipe.get("en") or {}).get("title", rid)
        ingr     = [ing_str(i) for i in recipe.get("ingredients", [])]

        print(f"[{done+1}/{total}] {rid:<55} … ", end="", flush=True)

        retry = True
        while retry:
            retry = False
            try:
                total_kcal = fetch_calories(title_en, ingr)
                if not total_kcal:
                    existing[rid] = None
                    print("✗ no calories returned")
                else:
                    per_person = round(total_kcal / SERVINGS)
                    existing[rid] = per_person
                    print(f"✓  {per_person} kcal/person  (total {total_kcal})")

            except urllib.error.HTTPError as e:
                body_text = ""
                try:
                    body_text = e.read().decode()
                except Exception:
                    pass

                if e.code == 422:
                    # Unprocessable — ingredient list not understood; store None and move on
                    existing[rid] = None
                    print(f"✗ 422 Unprocessable")
                elif e.code == 429:
                    print(f"\n⏳ Rate-limited — sleeping 3600 s …")
                    time.sleep(3600)
                    retry = True   # retry same recipe
                    continue
                else:
                    existing[rid] = None
                    print(f"✗ HTTP {e.code}  {body_text[:120]}")

            except Exception as exc:
                existing[rid] = None
                print(f"✗ {exc}")

        OUT.write_text(json.dumps(existing, indent=2, ensure_ascii=False))
        done += 1
        time.sleep(REQUEST_GAP)

    success = sum(1 for v in existing.values() if v is not None)
    print(f"\nDone. {success}/{len(existing)} recipes with calories → {OUT}")


if __name__ == "__main__":
    main()
