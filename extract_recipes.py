#!/usr/bin/env python3
"""
extract_recipes.py
------------------
One-shot migration: reads all recipes from meal_plan_generator.py
and writes one YAML file per recipe into recipes/

English fields are set to "TODO:" placeholders — fill them in Phase 4.

Run with:
    python3 extract_recipes.py
"""

import sys, yaml
from pathlib import Path

# Import the generator to access its in-memory data structures
sys.path.insert(0, str(Path(__file__).parent))
import meal_plan_generator as gen

OUTPUT_DIR = Path(__file__).parent / "recipes"
OUTPUT_DIR.mkdir(exist_ok=True)


# ── Custom YAML dumper: block style for strings, unicode-safe ─────────────────

class RecipeDumper(yaml.Dumper):
    pass

def _str_representer(dumper, data):
    """Use literal block scalar (|) for multi-line strings, plain for short ones."""
    if '\n' in data or len(data) > 80:
        return dumper.represent_scalar('tag:yaml.org,2002:str', data, style='|')
    return dumper.represent_scalar('tag:yaml.org,2002:str', data)

RecipeDumper.add_representer(str, _str_representer)


# ── Build YAML dict for one recipe ────────────────────────────────────────────

def recipe_to_yaml(recipe: dict, pool: str) -> dict:
    rid = recipe["id"]

    data = {
        "id":   rid,
        "pool": pool,
    }

    # Tags (lunch only)
    if pool == "lunch":
        data["healthy"]  = rid in gen.HEALTHY_LUNCH_IDS
        data["quick"]    = rid in gen.QUICK_LUNCH_IDS
        data["next_day"] = rid in gen.NEXT_DAY_LUNCH_IDS
        if rid in gen.QUICK_LUNCH_IDS:
            data["quick_minutes"] = gen.QUICK_READY_MINUTES.get(rid, 30)

    if recipe.get("meals"):
        data["meals"] = recipe["meals"]

    # German content
    de = {"title": recipe["title"]}
    if recipe.get("summary"):
        de["summary"] = recipe["summary"]
    if recipe.get("child_note"):
        de["child_note"] = recipe["child_note"]
    data["de"] = de

    # English placeholders
    data["en"] = {
        "title":   f"TODO: {recipe['title']}",
        "summary": f"TODO: {recipe.get('summary', '')}",
    }

    # Ingredients
    data["ingredients"] = [
        {
            "de_name":  ing["name"],
            "en_name":  f"TODO: {ing['name']}",
            "qty":      ing.get("qty"),
            "unit":     ing.get("unit", ""),
            "category": ing.get("category") or "Sonstiges",
        }
        for ing in recipe.get("ingredients", [])
    ]

    # Steps
    data["de_steps"] = recipe.get("steps", [])
    data["en_steps"] = [f"TODO: {s}" for s in recipe.get("steps", [])]

    return data


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    counts = {"lunch": 0, "dessert": 0, "skipped": 0}

    for pool_name, pool in [("lunch", gen.LUNCH_POOL), ("dessert", gen.DESSERT_POOL)]:
        for recipe in pool:
            rid = recipe.get("id")
            if not rid:
                counts["skipped"] += 1
                continue

            out_path = OUTPUT_DIR / f"{rid}.yaml"
            data = recipe_to_yaml(recipe, pool_name)

            with open(out_path, "w", encoding="utf-8") as f:
                yaml.dump(
                    data, f,
                    Dumper=RecipeDumper,
                    allow_unicode=True,
                    default_flow_style=False,
                    sort_keys=False,
                )
            counts[pool_name] += 1

    total = counts["lunch"] + counts["dessert"]
    print(f"Done: {counts['lunch']} lunch + {counts['dessert']} dessert = {total} recipes → {OUTPUT_DIR}")
    if counts["skipped"]:
        print(f"  Skipped {counts['skipped']} recipes with no id")


if __name__ == "__main__":
    main()
