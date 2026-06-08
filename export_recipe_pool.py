#!/usr/bin/env python3
"""Export all YAML recipes into recipe_pool.json for the frontend full-pool search."""

import sys
import json
import yaml
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

# Import generator for format_qty utility (avoids reimplementing German number formatting)
sys.path.insert(0, str(BASE_DIR))
import meal_plan_generator as gen


def main():
    recipes_dir = BASE_DIR / "recipes"
    if not recipes_dir.exists():
        raise FileNotFoundError(f"recipes/ not found at {recipes_dir}")

    pool = []
    for path in sorted(recipes_dir.glob("*.yaml")):
        r = yaml.safe_load(path.read_text(encoding="utf-8"))
        recipe_id = str(r["id"])

        recipe = {
            "id":         recipe_id,
            "pool":       r.get("pool", "lunch"),
            "healthy":    bool(r.get("healthy", False)),
            "quick":      bool(r.get("quick", False)),
            "next_day":   bool(r.get("next_day", False)),
            "meals":      r.get("meals", 2),
            "title":      r["de"]["title"],
            "title_en":   r.get("en", {}).get("title", ""),
            "summary":    r["de"].get("summary", ""),
            "summary_en": r.get("en", {}).get("summary", ""),
            "ingredients": [
                {
                    "name":        item["de_name"],
                    "name_en":     item.get("en_name", ""),
                    "qty":         item.get("qty"),
                    "unit":        item.get("unit", ""),
                    "qty_display": gen.format_qty(item.get("qty"), item.get("unit", "")),
                    "category":    item.get("category", ""),
                }
                for item in r.get("ingredients", [])
            ],
            "steps":    r.get("de_steps", []),
            "steps_en": r.get("en_steps", []),
        }

        if r["de"].get("child_note"):
            recipe["child_note"] = r["de"]["child_note"]

        pool.append(recipe)

    out_path = BASE_DIR / "recipe_pool.json"
    out_path.write_text(json.dumps(pool, ensure_ascii=False, indent=2), encoding="utf-8")
    counts = {"lunch": sum(1 for r in pool if r["pool"] == "lunch"),
              "dessert": sum(1 for r in pool if r["pool"] == "dessert")}
    print(f"Exported {len(pool)} recipes ({counts['lunch']} lunch, {counts['dessert']} dessert) → {out_path}")


if __name__ == "__main__":
    main()
