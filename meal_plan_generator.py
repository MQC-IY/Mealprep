#!/usr/bin/env python3
"""Generate the weekly family-friendly meal prep plan."""

from __future__ import annotations

import json
import argparse
from collections import defaultdict
from datetime import date, datetime, timedelta
from html import escape
from itertools import combinations
from math import ceil
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
STATE_PATH = BASE_DIR / "meal_plan_state.json"
PLAN_PATH = BASE_DIR / "mealprep_wochenplan.md"
RECIPES_PATH = BASE_DIR / "rezepte_mealprep.md"
SHOPPING_HTML_PATH = BASE_DIR / "einkaufsliste.html"
NEWSLETTER_PATH = BASE_DIR / "newsletter_mealprep.html"
GENERATOR_VERSION = "variants-v6"
DEFAULT_VARIANT = "standard"
PLAN_VARIANTS = {
    "standard": {
        "label": "Standard",
        "description": "familienfreundlich, abwechslungsreich und normaler Aufwand",
    },
    "gesund": {
        "label": "Gesund",
        "description": "mehr Gemüse, Hülsenfrüchte, Vollkorn und leichte Saucen",
    },
    "schnell": {
        "label": "Schnell",
        "description": "weniger aktive Kochzeit, einfache Schritte und alltagstaugliche Gerichte",
    },
}
WEEKLY_NEXT_DAY_DISHES = 2
WEEKLY_SAME_DAY_DISHES = 3
WEEKLY_UNIQUE_LUNCHES = WEEKLY_NEXT_DAY_DISHES + WEEKLY_SAME_DAY_DISHES
TARGET_GLOBAL_LUNCH_POOL = 300
TARGET_VARIANT_LUNCH_POOL = 100
TARGET_VARIANT_NEXT_DAY_POOL = 40
TARGET_VARIANT_SAME_DAY_POOL = 60
STATE_MEMORY_WEEKS = 8   # how many past weeks to remember (avoids dish repetition)

# ── YAML recipe loader ────────────────────────────────────────────────────────

def ing(name: str, qty: float | int | None, unit: str, category: str) -> dict[str, object]:
    """Build an ingredient entry. Kept as utility for manual recipe work."""
    return {"name": name, "qty": qty, "unit": unit, "category": category}


# Populated at startup by load_recipes()
LUNCH_POOL:           list[dict[str, object]] = []
DESSERT_POOL:         list[dict[str, object]] = []
HEALTHY_LUNCH_IDS:    set[str]               = set()
QUICK_LUNCH_IDS:      set[str]               = set()
NEXT_DAY_LUNCH_IDS:   set[str]               = set()
QUICK_READY_MINUTES:  dict[str, int]         = {}


def load_recipes() -> None:
    """Load all recipes from recipes/*.yaml into module-level pools and tag sets."""
    import yaml

    global LUNCH_POOL, DESSERT_POOL
    global HEALTHY_LUNCH_IDS, QUICK_LUNCH_IDS, NEXT_DAY_LUNCH_IDS, QUICK_READY_MINUTES

    recipes_dir = BASE_DIR / "recipes"
    if not recipes_dir.exists():
        raise FileNotFoundError(f"recipes/ directory not found at {recipes_dir}")

    lunch_pool:    list[dict[str, object]] = []
    dessert_pool:  list[dict[str, object]] = []
    healthy:       set[str]               = set()
    quick:         set[str]               = set()
    next_day:      set[str]               = set()
    quick_minutes: dict[str, int]         = {}

    for path in sorted(recipes_dir.glob("*.yaml")):
        r = yaml.safe_load(path.read_text(encoding="utf-8"))

        recipe_id = str(r["id"])
        recipe: dict[str, object] = {
            "id":         recipe_id,
            "title":      r["de"]["title"],
            "title_en":   r.get("en", {}).get("title", ""),
            "summary":    r["de"].get("summary", ""),
            "summary_en": r.get("en", {}).get("summary", ""),
            "meals":      r.get("meals", 2),
            "ingredients": [
                {
                    "name":     item["de_name"],
                    "name_en":  item.get("en_name", ""),
                    "qty":      item.get("qty"),
                    "unit":     item.get("unit", ""),
                    "category": item.get("category", ""),
                }
                for item in r.get("ingredients", [])
            ],
            "steps":    r.get("de_steps", []),
            "steps_en": r.get("en_steps", []),
        }
        if r["de"].get("child_note"):
            recipe["child_note"] = r["de"]["child_note"]

        if r.get("pool") == "dessert":
            dessert_pool.append(recipe)
        else:
            lunch_pool.append(recipe)
            if r.get("healthy"):
                healthy.add(recipe_id)
            if r.get("quick"):
                quick.add(recipe_id)
                quick_minutes[recipe_id] = int(r.get("quick_minutes", 30))
            if r.get("next_day"):
                next_day.add(recipe_id)

    LUNCH_POOL          = lunch_pool
    DESSERT_POOL        = dessert_pool
    HEALTHY_LUNCH_IDS   = healthy
    QUICK_LUNCH_IDS     = quick
    NEXT_DAY_LUNCH_IDS  = next_day
    QUICK_READY_MINUTES = quick_minutes


load_recipes()

WHOLE_UNITS = {
    "Stk",
    "Dose",
    "Dosen",
    "Glas",
    "Packung",
    "Bund",
    "Laib",
    "Zehe",
    "Zehen",
    "Stange",
    "Stangen",
    "Flasche",
}
SMALL_MEASURE_UNITS = {"EL", "TL"}
CANONICAL_UNITS = {
    "Dosen": "Dose",
    "Zehen": "Zehe",
    "Stangen": "Stange",
    "Liter": "ml",
}
UNIT_PLURALS = {
    "Dose": "Dosen",
    "Glas": "Gläser",
    "Zehe": "Zehen",
    "Stange": "Stangen",
}
PANTRY_PURCHASE_UNITS = {
    ("Basilikum", "TL"): ("Basilikum", 1, "Packung"),
    ("Currypulver", "TL"): ("Currypulver", 1, "Packung"),
    ("Kräuter der Provence", "TL"): ("Kräuter der Provence", 1, "Packung"),
    ("Kreuzkümmel", "TL"): ("Kreuzkümmel", 1, "Packung"),
    ("Minze, getrocknet", "TL"): ("Minze, getrocknet", 1, "Packung"),
    ("Olivenöl", "EL"): ("Olivenöl", 1, "Flasche"),
    ("Oregano", "TL"): ("Oregano", 1, "Packung"),
    ("Paprika edelsüß", "TL"): ("Paprika edelsüß", 1, "Packung"),
    ("Rapsöl", "EL"): ("Rapsöl", 1, "Flasche"),
    ("Sesam", "TL"): ("Sesam", 1, "Packung"),
    ("Sesamöl", "TL"): ("Sesamöl", 1, "Flasche"),
    ("Honig", "EL"): ("Honig", 1, "Glas"),
    ("Reisessig", "EL"): ("Reisessig", 1, "Flasche"),
    ("Zimt", "TL"): ("Zimt", 1, "Packung"),
    ("Sojasauce salzreduziert", "EL"): ("Sojasauce salzreduziert", 1, "Flasche"),
}


BREAKFASTS = [
    "Overnight Oats mit Haferflocken, Skyr, Beeren und Chiasamen",
    "Overnight Oats mit Banane und Zimt",
    "Overnight Oats mit Beeren",
    "Skyr-Becher mit Haferflocken, Birne und Sonnenblumenkernen",
    "Overnight Oats mit Apfel und Zimt",
    "Rührei mit Vollkornbrot und Tomaten",
    "Naturjoghurt mit Obst und Nussmix",
]

SNACKS = [
    "Apfel und eine Handvoll Mandeln",
    "Möhrensticks mit Hummus",
    "Skyr mit etwas Obst",
    "Paprikastreifen und Hummus",
    "Eine Banane und Walnüsse",
    "Trauben oder Beeren",
    "Gurkensticks mit Kräuterquark",
]

BREAKFASTS_EN = [
    "Overnight oats with rolled oats, skyr, berries and chia seeds",
    "Overnight oats with banana and cinnamon",
    "Overnight oats with berries",
    "Skyr with rolled oats, pear and sunflower seeds",
    "Overnight oats with apple and cinnamon",
    "Scrambled eggs with wholegrain bread and tomatoes",
    "Natural yoghurt with fruit and nut mix",
]

SNACKS_EN = [
    "Apple and a handful of almonds",
    "Carrot sticks with hummus",
    "Skyr with a bit of fruit",
    "Bell pepper strips and hummus",
    "A banana and walnuts",
    "Grapes or berries",
    "Cucumber sticks with herb quark",
]


IMAGES = {
    "lunch_primary": "images/chicken_bowl.png",
    "light_dinner": "images/lentil_curry.png",
    "lunch_secondary": "images/turkey_pot.png",
}


def validate_variant(variant: str) -> str:
    if variant not in PLAN_VARIANTS:
        choices = ", ".join(PLAN_VARIANTS)
        raise ValueError(f"Unbekannte Variante: {variant}. Erlaubt sind: {choices}")
    return variant


def output_paths(variant: str) -> dict[str, Path]:
    validate_variant(variant)
    if variant == DEFAULT_VARIANT:
        return {
            "plan": PLAN_PATH,
            "recipes": RECIPES_PATH,
            "shopping": SHOPPING_HTML_PATH,
            "newsletter": NEWSLETTER_PATH,
        }
    return {
        "plan": BASE_DIR / f"mealprep_wochenplan_{variant}.md",
        "recipes": BASE_DIR / f"rezepte_mealprep_{variant}.md",
        "shopping": BASE_DIR / f"einkaufsliste_{variant}.html",
        "newsletter": BASE_DIR / f"newsletter_{variant}.html",
    }


def alias_paths(variant: str) -> list[dict[str, Path]]:
    paths = [output_paths(variant)]
    if variant == DEFAULT_VARIANT:
        paths.append(
            {
                "plan": BASE_DIR / "mealprep_wochenplan_standard.md",
                "recipes": BASE_DIR / "rezepte_mealprep_standard.md",
                "shopping": BASE_DIR / "einkaufsliste_standard.html",
                "newsletter": BASE_DIR / "newsletter_standard.html",
            }
        )
    return paths


def filtered_lunch_pool(variant: str) -> list[dict[str, object]]:
    validate_variant(variant)
    if variant == "gesund":
        return [dish for dish in LUNCH_POOL if dish["id"] in HEALTHY_LUNCH_IDS]
    if variant == "schnell":
        return [dish for dish in LUNCH_POOL if dish["id"] in QUICK_LUNCH_IDS and QUICK_READY_MINUTES[str(dish["id"])] <= 30]
    # standard: exclude health-tagged dishes — they belong in gesund
    return [dish for dish in LUNCH_POOL if dish["id"] not in HEALTHY_LUNCH_IDS]


def lunch_pool_report() -> dict[str, object]:
    all_ids = {str(dish["id"]) for dish in LUNCH_POOL}
    variant_reports: dict[str, dict[str, int]] = {}

    for variant in PLAN_VARIANTS:
        pool = filtered_lunch_pool(variant)
        next_day_count = sum(1 for dish in pool if dish["id"] in NEXT_DAY_LUNCH_IDS)
        same_day_count = len(pool) - next_day_count
        variant_reports[variant] = {
            "total": len(pool),
            "next_day": next_day_count,
            "same_day": same_day_count,
            "target_total": TARGET_VARIANT_LUNCH_POOL,
            "target_next_day": TARGET_VARIANT_NEXT_DAY_POOL,
            "target_same_day": TARGET_VARIANT_SAME_DAY_POOL,
            "repeat_safe_total_min": WEEKLY_UNIQUE_LUNCHES * 2,
            "repeat_safe_next_day_min": WEEKLY_NEXT_DAY_DISHES * 2,
            "repeat_safe_same_day_min": WEEKLY_SAME_DAY_DISHES * 2,
            "headroom_total": len(pool) - (WEEKLY_UNIQUE_LUNCHES * 2),
            "headroom_next_day": next_day_count - (WEEKLY_NEXT_DAY_DISHES * 2),
            "headroom_same_day": same_day_count - (WEEKLY_SAME_DAY_DISHES * 2),
            "gap_total": max(0, TARGET_VARIANT_LUNCH_POOL - len(pool)),
            "gap_next_day": max(0, TARGET_VARIANT_NEXT_DAY_POOL - next_day_count),
            "gap_same_day": max(0, TARGET_VARIANT_SAME_DAY_POOL - same_day_count),
        }

    return {
        "global_total": len(all_ids),
        "global_target": TARGET_GLOBAL_LUNCH_POOL,
        "global_weekly_unique_min": WEEKLY_UNIQUE_LUNCHES * len(PLAN_VARIANTS),
        "global_headroom": len(all_ids) - (WEEKLY_UNIQUE_LUNCHES * len(PLAN_VARIANTS)),
        "global_gap": max(0, TARGET_GLOBAL_LUNCH_POOL - len(all_ids)),
        "variants": variant_reports,
    }


def assert_lunch_pool_health() -> None:
    report = lunch_pool_report()
    errors: list[str] = []

    if report["global_total"] < report["global_weekly_unique_min"]:
        errors.append(
            "Gesamtpool zu klein für überschneidungsfreie Varianten "
            f"({report['global_total']} vorhanden, {report['global_weekly_unique_min']} benötigt)."
        )

    for variant, variant_report in report["variants"].items():
        if variant_report["total"] < variant_report["repeat_safe_total_min"]:
            errors.append(
                f"{variant}: zu wenige Lunches für zwei Wochen ohne Wiederholung "
                f"({variant_report['total']} vorhanden, {variant_report['repeat_safe_total_min']} benötigt)."
            )
        if variant_report["next_day"] < variant_report["repeat_safe_next_day_min"]:
            errors.append(
                f"{variant}: zu wenige Next-Day-Gerichte "
                f"({variant_report['next_day']} vorhanden, {variant_report['repeat_safe_next_day_min']} benötigt)."
            )
        if variant_report["same_day"] < variant_report["repeat_safe_same_day_min"]:
            errors.append(
                f"{variant}: zu wenige Same-Day-Gerichte "
                f"({variant_report['same_day']} vorhanden, {variant_report['repeat_safe_same_day_min']} benötigt)."
            )

    if errors:
        raise RuntimeError("Pool-Kapazität unzureichend:\n- " + "\n- ".join(errors))


def format_lunch_pool_report() -> str:
    report = lunch_pool_report()
    lines = [
        "Lunch-Pool-Report",
        f"Gesamtpool: {report['global_total']} Gerichte",
        (
            "Benötigt für 3 überschneidungsfreie Varianten pro Woche: "
            f"{report['global_weekly_unique_min']} (Reserve: {report['global_headroom']})"
        ),
        "",
        "Variante | Gesamt | Next-Day | Same-Day | Reserve Gesamt | Reserve Next-Day | Reserve Same-Day",
        "-" * 92,
    ]
    for variant, variant_report in report["variants"].items():
        lines.append(
            f"{variant:8} | "
            f"{variant_report['total']:6} | "
            f"{variant_report['next_day']:8} | "
            f"{variant_report['same_day']:8} | "
            f"{variant_report['headroom_total']:13} | "
            f"{variant_report['headroom_next_day']:16} | "
            f"{variant_report['headroom_same_day']:16}"
        )
    lines.extend(
        [
            "",
            "Ausbauziel",
            f"Gesamtziel: {report['global_target']} (fehlen aktuell: {report['global_gap']})",
            (
                "Variantenziel je Plan: "
                f"{TARGET_VARIANT_LUNCH_POOL} Gesamt, "
                f"{TARGET_VARIANT_NEXT_DAY_POOL} Next-Day, "
                f"{TARGET_VARIANT_SAME_DAY_POOL} Same-Day"
            ),
            "",
            "Variante | Fehlend Gesamt | Fehlend Next-Day | Fehlend Same-Day",
            "-" * 66,
        ]
    )
    for variant, variant_report in report["variants"].items():
        lines.append(
            f"{variant:8} | "
            f"{variant_report['gap_total']:14} | "
            f"{variant_report['gap_next_day']:16} | "
            f"{variant_report['gap_same_day']:16}"
        )
    return "\n".join(lines)




def load_state() -> dict[str, object]:
    if not STATE_PATH.exists():
        return {}
    return json.loads(STATE_PATH.read_text(encoding="utf-8"))


def save_state(state: dict[str, object]) -> None:
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def current_week_key(today: date) -> str:
    iso = today.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def variant_seed(today: date, variant: str) -> int:
    seed = today.isocalendar().week
    if variant != DEFAULT_VARIANT:
        seed += list(PLAN_VARIANTS).index(variant) * 11
    return seed


def rotate_items(items: list[dict[str, object]], seed: int) -> list[dict[str, object]]:
    if not items:
        return []
    start = seed % len(items)
    return items[start:] + items[:start]


def ordered_pool(pool: list[dict[str, object]], exclude: set[str], seed: int) -> list[dict[str, object]]:
    preferred = rotate_items([item for item in pool if item["id"] not in exclude], seed)
    fallback = rotate_items([item for item in pool if item["id"] in exclude], seed + 5)
    return preferred + fallback


def rotate_select(pool: list[dict[str, object]], count: int, exclude: set[str], seed: int) -> list[dict[str, object]]:
    candidates = [item for item in pool if item["id"] not in exclude]
    if len(candidates) < count:
        candidates = pool[:]
    start = seed % len(candidates)
    rotated = candidates[start:] + candidates[:start]
    return rotated[:count]


def select_from_pool(pool: list[dict[str, object]], count: int, exclude: set[str], seed: int) -> list[dict[str, object]]:
    selected = rotate_select(pool, count, exclude, seed)
    if len(selected) >= count:
        return selected
    selected_ids = {item["id"] for item in selected}
    for item in rotate_select(pool, len(pool), set(), seed + 5):
        if item["id"] not in selected_ids:
            selected.append(item)
            selected_ids.add(item["id"])
        if len(selected) == count:
            break
    return selected


def candidate_lunch_sets(
    next_day_pool: list[dict[str, object]],
    same_day_pool: list[dict[str, object]],
    last_lunch_ids: set[str],
    reserved_lunch_ids: set[str],
    seed: int,
):
    next_day_candidates = [
        item for item in ordered_pool(next_day_pool, last_lunch_ids, seed)
        if item["id"] not in reserved_lunch_ids
    ]
    same_day_candidates = [
        item for item in ordered_pool(same_day_pool, last_lunch_ids, seed + 3)
        if item["id"] not in reserved_lunch_ids
    ]

    next_day_fresh = [item for item in next_day_candidates if item["id"] not in last_lunch_ids]
    next_day_repeat = [item for item in next_day_candidates if item["id"] in last_lunch_ids]
    same_day_fresh = [item for item in same_day_candidates if item["id"] not in last_lunch_ids]
    same_day_repeat = [item for item in same_day_candidates if item["id"] in last_lunch_ids]

    # Yield combinations in ascending repeat-penalty order instead of materializing
    # the full search space, which grows into the millions for larger lunch pools.
    for next_day_repeat_count in range(min(2, len(next_day_repeat)) + 1):
        next_day_fresh_count = 2 - next_day_repeat_count
        if len(next_day_fresh) < next_day_fresh_count:
            continue

        for next_day_fresh_choice in combinations(next_day_fresh, next_day_fresh_count):
            for next_day_repeat_choice in combinations(next_day_repeat, next_day_repeat_count):
                next_day_choice = [*next_day_fresh_choice, *next_day_repeat_choice]
                next_day_ids = {item["id"] for item in next_day_choice}
                filtered_same_day_fresh = [
                    item for item in same_day_fresh if item["id"] not in next_day_ids
                ]
                filtered_same_day_repeat = [
                    item for item in same_day_repeat if item["id"] not in next_day_ids
                ]

                for same_day_repeat_count in range(min(3, len(filtered_same_day_repeat)) + 1):
                    same_day_fresh_count = 3 - same_day_repeat_count
                    if len(filtered_same_day_fresh) < same_day_fresh_count:
                        continue

                    for same_day_fresh_choice in combinations(
                        filtered_same_day_fresh,
                        same_day_fresh_count,
                    ):
                        for same_day_repeat_choice in combinations(
                            filtered_same_day_repeat,
                            same_day_repeat_count,
                        ):
                            lunches = [
                                *next_day_choice,
                                *same_day_fresh_choice,
                                *same_day_repeat_choice,
                            ]
                            penalty = next_day_repeat_count + same_day_repeat_count
                            yield lunches, {"penalty": penalty}


def canonical_unit(unit: str) -> str:
    return CANONICAL_UNITS.get(unit, unit)


def canonical_qty_unit(qty: object, unit: str) -> tuple[object, str]:
    if unit == "Liter" and isinstance(qty, (int, float)):
        return qty * 1000, "ml"
    return qty, canonical_unit(unit)


def display_unit(value: float | int | None, unit: str) -> str:
    unit = canonical_unit(unit)
    if value is None:
        return unit
    if isinstance(value, (int, float)) and abs(float(value)) != 1 and unit in UNIT_PLURALS:
        return UNIT_PLURALS[unit]
    return unit


def format_fractional_piece(value: float, unit: str) -> str:
    unit = canonical_unit(unit)
    whole = int(value)
    fraction = value - whole
    if fraction < 0.15:
        return f"{whole} {display_unit(whole, unit)}".strip()
    if fraction < 0.4:
        fraction_text = "1/3"
    elif fraction < 0.6:
        fraction_text = "1/2"
    elif fraction < 0.85:
        fraction_text = "2/3"
    else:
        rounded = whole + 1
        return f"{rounded} {display_unit(rounded, unit)}".strip()
    if whole:
        return f"ca. {whole} {fraction_text} {display_unit(value, unit)}".strip()
    return f"ca. {fraction_text} {display_unit(1, unit)}".strip()


def normalize_decimal(value: float, unit: str) -> float | int:
    if unit in {"g", "ml"}:
        return int(round(value / 10) * 10)
    if unit in SMALL_MEASURE_UNITS:
        return round(value * 2) / 2
    if value.is_integer():
        return int(value)
    return round(value, 2)


def format_qty(value: float | int | None, unit: str) -> str:
    unit = canonical_unit(unit)
    if value is None:
        return unit
    if isinstance(value, (int, float)):
        numeric_value = float(value)
        if unit in WHOLE_UNITS and not numeric_value.is_integer():
            return format_fractional_piece(numeric_value, unit)
        value = normalize_decimal(numeric_value, unit)
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    if isinstance(value, float):
        qty_text = str(value).replace(".", ",")
    else:
        qty_text = str(value)
    return f"{qty_text} {display_unit(value, unit)}".strip()


def format_ml_qty(value: float | int) -> str:
    numeric_value = float(value)
    if numeric_value >= 1000 and numeric_value % 500 == 0:
        liters = numeric_value / 1000
        if liters.is_integer():
            return f"{int(liters)} Liter"
        return f"{str(liters).replace('.', ',')} Liter"
    return f"{int(numeric_value)} ml"


def format_shopping_qty(value: float | int | None, unit: str) -> str:
    unit = canonical_unit(unit)
    if value is None:
        return unit
    if isinstance(value, (int, float)):
        numeric_value = float(value)
        if unit == "ml":
            return format_ml_qty(numeric_value)
        if unit in WHOLE_UNITS:
            value = ceil(numeric_value)
        else:
            value = normalize_decimal(numeric_value, unit)
    return format_qty(value, unit)


def assemble_week(
    today: date,
    variant: str,
    variant_state: dict[str, object],
    selected_lunches: list[dict[str, object]],
) -> dict[str, object]:
    seed = variant_seed(today, variant)
    dessert = rotate_select(DESSERT_POOL, 1, set(variant_state.get("last_dessert_ids", [])), seed + 7)[0]

    lunch_plan = [
        (selected_lunches[0], "heute kochen, morgen mittags nochmal essen"),
        (selected_lunches[0], "Rest vom Vortag zum Mittag"),
        (selected_lunches[2], "frisch kochen und mittags aufessen"),
        (selected_lunches[1], "heute kochen, morgen mittags nochmal essen"),
        (selected_lunches[1], "Rest vom Vortag zum Mittag"),
        (selected_lunches[3], "frisch kochen und mittags aufessen"),
        (selected_lunches[4], "frisch kochen und mittags aufessen"),
    ]

    _DAYS_DE = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]
    _DAYS_EN = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

    days = []
    for index, (dish, lunch_note) in enumerate(lunch_plan):
        days.append(
            {
                "day":          _DAYS_DE[index],
                "day_en":       _DAYS_EN[index],
                "breakfast":    BREAKFASTS[index],
                "breakfast_en": BREAKFASTS_EN[index],
                "lunch":        dish["title"],
                "lunch_en":     dish.get("title_en", ""),
                "lunch_id":     dish["id"],
                "lunch_note":   lunch_note,
                "dinner":       "Kein Abendessen geplant; bei Hunger Reste vom Mittag.",
                "snack":        SNACKS[index],
                "snack_en":     SNACKS_EN[index],
            }
        )

    lunch_counts: dict[str, int] = {}
    for dish, _note in lunch_plan:
        lunch_counts[str(dish["id"])] = lunch_counts.get(str(dish["id"]), 0) + 1

    return {
        "variant": variant,
        "variant_label": PLAN_VARIANTS[variant]["label"],
        "variant_description": PLAN_VARIANTS[variant]["description"],
        "lunches": selected_lunches,
        "lunch_counts": lunch_counts,
        "dessert": dessert,
        "days": days,
        "week_key": current_week_key(today),
    }


def build_week(today: date, variant: str = DEFAULT_VARIANT, reserved_lunch_ids: set[str] | None = None) -> dict[str, object]:
    validate_variant(variant)
    state = load_state()
    week_key = current_week_key(today)
    variant_state = state.get("variants", {}).get(variant, {})
    if (
        variant_state.get("last_generated_week") == week_key
        and variant_state.get("generator_version") == GENERATOR_VERSION
        and all(path.exists() for path_group in alias_paths(variant) for path in path_group.values())
    ):
        return {"reused": True}

    last_lunch_ids = set(variant_state.get("last_lunch_ids", []))
    seed = variant_seed(today, variant)
    lunch_pool = filtered_lunch_pool(variant)
    next_day_pool = [dish for dish in lunch_pool if dish["id"] in NEXT_DAY_LUNCH_IDS]
    same_day_pool = [dish for dish in lunch_pool if dish["id"] not in NEXT_DAY_LUNCH_IDS]
    first = next(
        candidate_lunch_sets(
            next_day_pool,
            same_day_pool,
            last_lunch_ids,
            reserved_lunch_ids or set(),
            seed,
        ),
        None,
    )
    if first is None:
        raise RuntimeError(f"Keine überschneidungsfreie Lunch-Auswahl für Variante {variant} gefunden.")

    lunches = first[0]
    week = assemble_week(today, variant, variant_state, lunches)

    # Rolling memory: prepend this week's ids, keep last STATE_MEMORY_WEEKS weeks
    max_ids = STATE_MEMORY_WEEKS * WEEKLY_UNIQUE_LUNCHES
    new_lunch_ids = [item["id"] for item in lunches]
    old_lunch_ids = [i for i in variant_state.get("last_lunch_ids", []) if i not in new_lunch_ids]
    rolling_lunch_ids = (new_lunch_ids + old_lunch_ids)[:max_ids]

    new_dessert_id = week["dessert"]["id"]
    old_dessert_ids = [i for i in variant_state.get("last_dessert_ids", []) if i != new_dessert_id]
    rolling_dessert_ids = ([new_dessert_id] + old_dessert_ids)[:STATE_MEMORY_WEEKS]

    variants = dict(state.get("variants", {}))
    variants[variant] = {
            "last_generated_week": week_key,
            "generator_version": GENERATOR_VERSION,
            "last_lunch_ids": rolling_lunch_ids,
            "last_dessert_ids": rolling_dessert_ids,
    }
    state["variants"] = variants
    if variant == DEFAULT_VARIANT:
        state.update(variants[variant])
    state.pop("last_dinner_ids", None)
    save_state(state)
    return week


def join_ingredients(items: list[dict[str, object]]) -> dict[str, list[tuple[str, float | int | None, str]]]:
    grouped: dict[str, dict[tuple[str, str], float | int | None]] = defaultdict(dict)

    for item in items:
        category = str(item["category"])
        name = str(item["name"])
        qty, unit = canonical_qty_unit(item["qty"], str(item["unit"]))
        key = (name, unit)
        current = grouped[category].get(key)
        if qty is None or current is None:
            grouped[category][key] = qty
        elif isinstance(qty, (int, float)) and isinstance(current, (int, float)):
            grouped[category][key] = current + qty
        else:
            grouped[category][key] = qty

    ordered: dict[str, list[tuple[str, float | int | None, str]]] = {}
    for category, values in grouped.items():
        ordered[category] = sorted(
            [(name, qty, unit) for (name, unit), qty in values.items()],
            key=lambda entry: entry[0].lower(),
        )
    return ordered


def scale_ingredient(item: dict[str, object], factor: float) -> dict[str, object]:
    scaled = dict(item)
    qty = scaled["qty"]
    if isinstance(qty, (int, float)):
        scaled["qty"] = round(qty * factor, 2)
    return scaled


def normalize_shopping_items(items: list[dict[str, object]]) -> list[dict[str, object]]:
    normalized: list[dict[str, object]] = []
    purchase_replacements: dict[tuple[str, str], dict[str, object]] = {}

    for item in items:
        name = str(item["name"])
        qty, unit = canonical_qty_unit(item["qty"], str(item["unit"]))
        replacement = PANTRY_PURCHASE_UNITS.get((name, unit))
        if replacement:
            replacement_name, replacement_qty, replacement_unit = replacement
            key = (replacement_name, canonical_unit(replacement_unit))
            purchase_replacements[key] = ing(
                replacement_name,
                replacement_qty,
                replacement_unit,
                str(item["category"]),
            )
            continue
        normalized_item = dict(item)
        normalized_item["qty"] = qty
        normalized_item["unit"] = unit
        normalized.append(normalized_item)

    existing_keys = {
        (str(item["name"]), canonical_qty_unit(item["qty"], str(item["unit"]))[1])
        for item in normalized
    }
    for key, item in purchase_replacements.items():
        if key not in existing_keys:
            normalized.append(item)
    return normalized


def build_shopping_groups(selected_lunches: list[dict[str, object]], lunch_counts: dict[str, int], dessert: dict[str, object]) -> dict[str, list[tuple[str, float | int | None, str]]]:
    items: list[dict[str, object]] = []
    for dish in selected_lunches:
        planned_meals = lunch_counts[str(dish["id"])]
        base_meals = float(dish.get("meals", planned_meals))
        factor = planned_meals / base_meals
        items.extend(scale_ingredient(ingredient, factor) for ingredient in dish["ingredients"])
    items.extend(dessert["ingredients"])

    breakfast_basics = [
        ing("Haferflocken", 1000, "g", "Kohlenhydrate und Sattmacher"),
        ing("Skyr oder griechischer Joghurt", 2000, "g", "Protein und Milchprodukte"),
        ing("Milch oder Haferdrink", 1, "Liter", "Protein und Milchprodukte"),
        ing("Chiasamen", 1, "Packung", "Konserven und Vorrat"),
        ing("Bananen", 6, "Stk", "Obst"),
        ing("Äpfel", 6, "Stk", "Obst"),
        ing("Birnen", 4, "Stk", "Obst"),
        ing("Beeren, frisch oder TK", 500, "g", "Obst"),
        ing("Trauben", 500, "g", "Obst"),
        ing("Mandeln", 200, "g", "Konserven und Vorrat"),
        ing("Walnüsse", 200, "g", "Konserven und Vorrat"),
        ing("Sonnenblumenkerne", 1, "Packung", "Konserven und Vorrat"),
        ing("Eier", 10, "Stk", "Protein und Milchprodukte"),
        ing("Vollkornbrot", 1, "Laib", "Kohlenhydrate und Sattmacher"),
        ing("Hummus", 1, "Packung", "Protein und Milchprodukte"),
        ing("Magerquark oder Kräuterquark", 500, "g", "Protein und Milchprodukte"),
        ing("Paprikastreifen", None, "", "Gemüse und Salat"),
        ing("Honig", 1, "Glas", "Konserven und Vorrat"),
        ing("Zimt", 1, "Packung", "Gewürze"),
        ing("Salz", 1, "Packung", "Gewürze"),
        ing("Pfeffer", 1, "Packung", "Gewürze"),
        ing("Chili", 1, "Packung", "Gewürze"),
        ing("Knoblauchpulver", 1, "Packung", "Gewürze"),
    ]
    items.extend(breakfast_basics)
    items = normalize_shopping_items(items)
    grouped = join_ingredients(items)

    if "Gemüse und Salat" in grouped:
        grouped["Gemüse und Salat"] = [
            entry for entry in grouped["Gemüse und Salat"] if entry[0] != "Paprikastreifen"
        ]
    return grouped


def _serialize_recipe(recipe: dict[str, object]) -> dict[str, object]:
    return {
        "id":         recipe["id"],
        "title":      recipe["title"],
        "title_en":   recipe.get("title_en", ""),
        "meals":      recipe.get("meals"),
        "summary":    recipe.get("summary", ""),
        "summary_en": recipe.get("summary_en", ""),
        "child_note": recipe.get("child_note", ""),
        "ingredients": [
            {
                "name":        str(item["name"]),
                "name_en":     str(item.get("name_en", "")),
                "qty_display": format_shopping_qty(item["qty"], str(item["unit"])),
                "category":    str(item["category"]) if item.get("category") else None,
            }
            for item in recipe.get("ingredients", [])
        ],
        "steps":    recipe.get("steps", []),
        "steps_en": recipe.get("steps_en", []),
    }


_SHOPPING_CATEGORY_ORDER = [
    "Gemüse und Salat",
    "Obst",
    "Protein und Milchprodukte",
    "Kohlenhydrate und Sattmacher",
    "Konserven und Vorrat",
    "Gewürze",
]


def _serialize_shopping(
    grouped: dict[str, list[tuple[str, float | int | None, str]]],
) -> list[dict[str, object]]:
    result = []
    seen: set[str] = set()
    for category in _SHOPPING_CATEGORY_ORDER:
        if category in grouped:
            result.append({
                "category": category,
                "items": [
                    {"name": name, "qty_display": format_shopping_qty(qty, unit)}
                    for name, qty, unit in grouped[category]
                ],
            })
            seen.add(category)
    for category, entries in grouped.items():
        if category not in seen:
            result.append({
                "category": category,
                "items": [
                    {"name": name, "qty_display": format_shopping_qty(qty, unit)}
                    for name, qty, unit in entries
                ],
            })
    return result


def build_plan_markdown(week: dict[str, object]) -> str:
    lunches = week["lunches"]
    days = week["days"]
    lunch_counts = week["lunch_counts"]
    dessert = week["dessert"]
    variant = week.get("variant", DEFAULT_VARIANT)
    variant_label = week.get("variant_label", PLAN_VARIANTS[DEFAULT_VARIANT]["label"])
    variant_description = week.get("variant_description", PLAN_VARIANTS[DEFAULT_VARIANT]["description"])
    recipes_filename = output_paths(str(variant))["recipes"].name
    shopping = build_shopping_groups(lunches, lunch_counts, dessert)

    lines = [
        f"# Meal-Prep-Wochenplan: {variant_label}",
        "",
        f"**Variante:** {variant_description}.",
        "",
        "Dieser Wochenplan ist auf euren Familienalltag in Deutschland ausgelegt: geplant wird nur ein Hauptgericht für das Mittagessen, damit möglichst nichts übrig bleibt oder weggeworfen wird.",
        "",
        f"Die ausformulierten Einzelrezepte findet ihr in [`{recipes_filename}`](./{recipes_filename}).",
        "",
        "Die Rezepte sind als vollständige Familienrezepte aufgebaut. Wenn ihr für euren Sohn mitkocht, könnt ihr bei Bedarf eine Portion früher abnehmen oder einzelne Komponenten milder halten.",
        "",
        f"**Dessert der Woche:** {dessert['title']} - {dessert['summary']}",
        "",
        "## Grundidee der Woche",
        "",
        "- **Meal-Prep-Session 1:** Sonntag, ca. 90 bis 120 Minuten",
        "- **Meal-Prep-Session 2:** Mittwochabend, ca. 45 bis 60 Minuten",
        "- **Ziel:** Nur Mittagessen planen; abends nur essen, wenn wirklich Hunger da ist",
        "- **Resteregel:** Eintöpfe, Currys und Ofengerichte dürfen am nächsten Tag nochmal zum Mittag gegessen werden; frischere Pfannen und Bowls werden für einen Mittag geplant",
    ]
    if variant == "schnell":
        lines.append("- **Schnell-Regel:** Alle Hauptgerichte dieser Variante sind auf maximal 30 Minuten Gesamtzeit ausgelegt")
    lines.extend(
        [
            "",
            "## Familienanpassung für das Mittagessen",
            "",
            "- Kocht die Gerichte grundsätzlich als vollständiges Rezept.",
            "- Für euren Sohn könnt ihr bei Bedarf eine Portion früher abnehmen oder einzelne Zutaten separat halten.",
            "- Gemüse für Kinderportionen weicher garen und Fleisch fein schneiden oder zupfen.",
            "- Schärfe bleibt optional und kann wie bisher erst am Tisch oder am Ende ergänzt werden.",
            "",
            "## Vorbereitung am Sonntag",
            "",
            f"1. {days[0]['lunch']} für Montag und Dienstag vorbereiten",
            f"2. {days[2]['lunch']} für Mittwoch einplanen",
            "3. Overnight Oats für Montag bis Mittwoch vorbereiten",
            "4. Snacks portionieren",
            "",
            "## Vorbereitung am Mittwoch",
            "",
            f"1. {days[3]['lunch']} für Donnerstag und Freitag vorbereiten",
            f"2. {days[5]['lunch']} und {days[6]['lunch']} für das Wochenende einplanen",
            "3. Overnight Oats für Donnerstag bis Sonntag vorbereiten",
            "4. Keine festen Abendessen einkaufen; nur vorhandene Reste nutzen",
            "",
            "---",
            "",
            "## Wochenplan",
            "",
        ]
    )

    for day in days:
        lunch_note = ", bei Bedarf kindgerecht anpassen" if day["day"] in {"Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag"} else ""
        lines.extend(
            [
                f"### {day['day']}",
                "",
                f"- **Frühstück:** {day['breakfast']}",
                f"- **Mittagessen:** {day['lunch']}{lunch_note}",
                f"- **Hinweis:** {day['lunch_note']}",
                f"- **Abendessen:** {day['dinner']}",
                f"- **Snack:** {day['snack']}",
                "",
            ]
        )

    lines.extend(
        [
            "---",
            "",
            "## Meal-Prep-Rezepte in Kurzform",
            "",
        ]
    )

    for index, dish in enumerate(lunches, start=1):
        lines.append(f"### {index}. {dish['title']}")
        lines.append("")
        planned_meals = lunch_counts[str(dish["id"])]
        lines.append(f"Für {planned_meals} Mittagessen:")
        if variant == "schnell":
            lines.append(f"Maximal ca. {QUICK_READY_MINUTES[str(dish['id'])]} Minuten Gesamtzeit.")
        lines.append("")
        factor = planned_meals / float(dish.get("meals", planned_meals))
        for ingredient in dish["ingredients"]:
            scaled = scale_ingredient(ingredient, factor)
            lines.append(f"- {format_qty(scaled['qty'], str(scaled['unit']))} {scaled['name']}".strip())
        lines.append("")
        lines.append(dish["steps"][0] if dish["steps"] else dish["summary"])
        lines.append("")

    lines.append(f"### Dessert der Woche: {dessert['title']}")
    lines.append("")
    lines.append(f"{dessert['summary']}")
    lines.append("")
    lines.append(f"Ergibt {dessert['servings']}:")
    lines.append("")
    for ingredient in dessert["ingredients"]:
        lines.append(f"- {format_qty(ingredient['qty'], str(ingredient['unit']))} {ingredient['name']}".strip())
    lines.append("")
    lines.append(dessert["steps"][0])
    lines.append("")

    lines.extend(
        [
            "---",
            "",
            "## Einkaufsliste für Deutschland",
            "",
        ]
    )

    category_order = [
        "Gemüse und Salat",
        "Obst",
        "Protein und Milchprodukte",
        "Kohlenhydrate und Sattmacher",
        "Konserven und Vorrat",
        "Gewürze",
    ]
    for category in category_order:
        entries = shopping.get(category)
        if not entries:
            continue
        lines.append(f"### {category}")
        lines.append("")
        for name, qty, unit in entries:
            lines.append(f"- {format_shopping_qty(qty, unit)} {name}".strip())
        lines.append("")

    lines.extend(
        [
            "---",
            "",
            "## Lagerung und Haltbarkeit",
            "",
            "- Gekochten Reis und gegartes Fleisch innerhalb von 3 bis 4 Tagen verbrauchen.",
            "- Kinderportionen möglichst direkt nach dem Kochen separat abfüllen.",
            "- Gerichte, die für zwei Mittagessen geplant sind, direkt nach dem Kochen in zwei Lunch-Portionen aufteilen.",
            "- Abends nur vorhandene Reste essen; es wird kein zusätzliches Abendessen eingeplant.",
            "",
            "## Warum dieser Plan gut funktioniert",
            "",
            "- Es wird nur ein Hauptgericht pro Tag geplant.",
            "- Gute Restegerichte werden maximal für den nächsten Mittag weitergenutzt.",
            "- Abends entstehen keine zusätzlichen geplanten Reste.",
            "",
        ]
    )

    return "\n".join(lines)


def build_recipes_markdown(week: dict[str, object]) -> str:
    lunch_counts = week["lunch_counts"]
    dessert = week["dessert"]
    variant = week.get("variant", DEFAULT_VARIANT)
    variant_label = week.get("variant_label", PLAN_VARIANTS[DEFAULT_VARIANT]["label"])
    selected_breakfasts = [
        {
            "title": "Overnight Oats Basis",
            "servings": "2",
            "ingredients": [
                "120 g Haferflocken",
                "300 g Skyr oder griechischer Joghurt",
                "200 ml Milch oder Haferdrink",
                "2 TL Chiasamen",
                "Obst nach Wahl",
            ],
            "steps": [
                "Alles verrühren, in Gläser füllen und über Nacht kalt stellen.",
            ],
        },
        {
            "title": "Rührei mit Vollkornbrot und Tomaten",
            "servings": "2",
            "ingredients": [
                "6 Eier",
                "1 EL Milch",
                "4 Scheiben Vollkornbrot",
                "3 Tomaten",
            ],
            "steps": [
                "Eier mit Milch verquirlen und langsam stocken lassen.",
                "Mit Brot und Tomaten servieren.",
            ],
        },
    ]

    lines = [
        f"# Rezepte zum Meal-Prep-Wochenplan: {variant_label}",
        "",
        "Die Mengen sind jeweils für 2 Erwachsene gerechnet, sofern nicht anders angegeben.",
        "",
        "Die Hauptgerichte sind als vollständige Familienrezepte geschrieben. Wenn ihr für euren Sohn mitkocht, könnt ihr einzelne Komponenten milder halten oder eine Portion früher abnehmen.",
        "",
        "## Familienanpassung für euren 11 Monate alten Sohn",
        "",
        "- Rezepte grundsätzlich vollständig kochen; Kinderportionen nur bei Bedarf separat anpassen.",
        "- Gemüse für Kinderportionen weicher garen und Fleisch fein schneiden oder zupfen.",
        "- Schärfere Komponenten könnt ihr bei Bedarf separat ergänzen oder weglassen.",
        "",
    ]

    for index, recipe in enumerate(selected_breakfasts, start=1):
        lines.extend(
            [
                f"## {index}. {recipe['title']}",
                "",
                f"**Portionen:** {recipe['servings']}",
                "",
                "### Zutaten",
                "",
            ]
        )
        for item in recipe["ingredients"]:
            lines.append(f"- {item}")
        lines.extend(["", "### Zubereitung", ""])
        for step_index, step in enumerate(recipe["steps"], start=1):
            lines.append(f"{step_index}. {step}")
        lines.append("")

    start_index = len(selected_breakfasts) + 1
    for index, dish in enumerate(week["lunches"], start=start_index):
        planned_meals = lunch_counts[str(dish["id"])]
        factor = planned_meals / float(dish.get("meals", planned_meals))
        lines.extend(
            [
                f"## {index}. {dish['title']}",
                "",
                f"**Geplant für:** {planned_meals} Mittagessen für 2 Erwachsene plus Kinderportion",
                *((f"**Zeit:** maximal ca. {QUICK_READY_MINUTES[str(dish['id'])]} Minuten Gesamtzeit",) if variant == "schnell" else ()),
                "",
                "### Zutaten",
                "",
            ]
        )
        for ingredient in dish["ingredients"]:
            scaled = scale_ingredient(ingredient, factor)
            lines.append(f"- {format_qty(scaled['qty'], str(scaled['unit']))} {scaled['name']}".strip())
        lines.extend(["", "### Zubereitung", ""])
        for step_index, step in enumerate(dish["steps"], start=1):
            lines.append(f"{step_index}. {step}")
        if "child_note" in dish:
            lines.extend(["", f"**Kinder-Anpassung bei Bedarf:** {dish['child_note']}"])
        lines.append("")

    dessert_index = start_index + len(week["lunches"])
    lines.extend(
        [
            f"## {dessert_index}. Dessert der Woche: {dessert['title']}",
            "",
            f"**Ergibt:** {dessert['servings']}",
            "",
            f"{dessert['summary']} {dessert['prep_note']}",
            "",
            "### Zutaten",
            "",
        ]
    )
    for ingredient in dessert["ingredients"]:
        lines.append(f"- {format_qty(ingredient['qty'], str(ingredient['unit']))} {ingredient['name']}".strip())
    lines.extend(["", "### Zubereitung", ""])
    for step_index, step in enumerate(dessert["steps"], start=1):
        lines.append(f"{step_index}. {step}")
    lines.append("")

    return "\n".join(lines)


def build_shopping_html(plan_markdown: str) -> str:
    shopping_lines = plan_markdown.split("## Einkaufsliste für Deutschland", 1)[1].split("---", 1)[0].strip().splitlines()
    html = [
        "<!DOCTYPE html>",
        '<html lang="de"><head><meta charset="UTF-8" /><meta name="viewport" content="width=device-width, initial-scale=1.0" />',
        "<title>Einkaufsliste für Deutschland</title>",
        "<style>body{font-family:Arial,Helvetica,sans-serif;background:#f4ede3;color:#2f241c;margin:0;} .page{max-width:860px;margin:0 auto;padding:32px 20px;} .hero{background:linear-gradient(135deg,#cf7d46,#e7c4a0);color:#fff;padding:28px;border-radius:18px;} .card{background:#fffaf4;border:1px solid #e7d8c7;border-radius:16px;padding:18px 20px;margin-top:18px;} h1,h2{font-family:Georgia,'Times New Roman',serif;color:#5b4335;} .hero h1{color:#fff;margin:0 0 8px;} ul{padding-left:20px;line-height:1.7;}</style>",
        "</head><body><div class=\"page\"><section class=\"hero\"><h1>Einkaufsliste für Deutschland</h1><p>Automatisch aus dem aktuellen Wochenplan erzeugt.</p></section>",
    ]
    current_list = False
    for raw in shopping_lines:
        line = raw.strip()
        if not line:
            continue
        if line.startswith("### "):
            if current_list:
                html.append("</ul></section>")
            html.append(f"<section class=\"card\"><h2>{escape(line[4:])}</h2><ul>")
            current_list = True
            continue
        if line.startswith("- "):
            html.append(f"<li>{escape(line[2:])}</li>")
    if current_list:
        html.append("</ul></section>")
    html.append("</div></body></html>")
    return "".join(html)


def build_inspiration_note(lunches: list[dict[str, object]], dessert: dict[str, object]) -> tuple[str, str]:
    lunch_ids = {str(dish["id"]) for dish in lunches}
    balkan_ids = {"mild_djuvec_chicken", "stuffed_pepper_pot", "balkan_musaka", "chicken_bulgur_skilet"}
    italian_ids = {"italian_turkey_meatballs", "italian_minestrone", "italian_tomato_risotto_chicken"}
    japanese_ids = {"japanese_oyakodon_mild", "japanese_soboro_bowl", "japanese_udon_chicken_veg"}
    turkish_ids = {"turkish_lentil_bulgur_pot", "turkish_chicken_veg_stew", "turkish_manti_style_pasta"}
    french_ids = {"french_lentil_carrot_stew", "french_chicken_ratatouille", "french_quiche_potato_veg"}
    one_pot_ids = {
        "turkey_veg_pot",
        "lentil_coconut_curry",
        "mild_pasta_bolognese",
        "stuffed_pepper_pot",
        "italian_minestrone",
        "turkish_lentil_bulgur_pot",
        "turkish_chicken_veg_stew",
        "french_lentil_carrot_stew",
        "french_chicken_ratatouille",
    }

    if len(lunch_ids & balkan_ids) >= 2:
        return (
            "Inspiration: Balkan-Familienküche",
            (
                "Diese Woche lehnt sich an die Balkan-Küche an: einfache Zutaten, viel Paprika, Reis, "
                "Tomate und Gerichte, die nicht empfindlich sind, wenn sie einen Tag durchziehen. "
                "Dazu gehören aber auch echte Aromen wie Paprika, Knoblauch, Zwiebel, Joghurt und Kräuter. "
                "Kinder lassen sich bei Bedarf anpassen, aber die Zielrezepte bleiben bewusst vollständiger."
            ),
        )

    if len(lunch_ids & italian_ids) >= 2:
        return (
            "Inspiration: Italienische Familienküche",
            (
                "Diese Woche nimmt sich Italien nicht als Restaurantküche, sondern als Familienküche zum Vorbild: "
                "Tomate, Pasta, Reis, Knoblauch, Kräuter und Parmesan werden so kombiniert, dass die Gerichte "
                "auch im Alltag rund und vollständig schmecken. Für Kinder könnt ihr bei Bedarf separat anpassen, "
                "aber das Zielrezept selbst bleibt aromatisch und vollwertig. Das ist genau die Art Küche, "
                "die ohne viel Theater nach Zuhause schmeckt."
            ),
        )

    if len(lunch_ids & japanese_ids) >= 2:
        return (
            "Inspiration: Japanische Alltagsküche",
            (
                "Die japanische Idee dieser Woche ist nicht Sushi, sondern Donburi und einfache Nudelschalen: "
                "Reis oder weiche Nudeln, Ei, Gemüse und typische Aromen wie Sojasauce, Ingwer, Frühlingszwiebel "
                "und etwas Sesam. Für Kinder könnt ihr bei Bedarf eine Portion früher abnehmen, aber das Zielrezept "
                "selbst bleibt voll gewürzt und näher an der Alltagsküche."
            ),
        )

    if len(lunch_ids & turkish_ids) >= 2:
        return (
            "Inspiration: Türkische Hausmannsküche",
            (
                "Diese Woche schaut in die türkische Familienküche: Linsen, Bulgur, Joghurt, Tomate und Paprika "
                "machen Gerichte, die sättigen, aber nicht kompliziert sind. Dazu gehören aber auch echte Aromen "
                "wie Minze, Kreuzkümmel, Knoblauch, Joghurt und Zitrone. Kinder lassen sich bei Bedarf anpassen, "
                "aber die Grundrezepte bleiben bewusst vollständiger und näher an der Alltagsküche."
            ),
        )

    if len(lunch_ids & french_ids) >= 2:
        return (
            "Inspiration: Französische Landküche",
            (
                "Die französische Seite dieser Woche ist eher Landküche als feines Restaurant: Linsen, Kartoffeln, "
                "Gemüse, Knoblauch, Kräuter und Ofengerichte, die warm, ruhig und unkompliziert wirken. "
                "Das passt gut zu Meal Prep, weil die Gerichte nicht perfekt aussehen müssen, sondern gut "
                "durchziehen dürfen und trotzdem aromatisch bleiben."
            ),
        )

    if len(lunch_ids & one_pot_ids) >= 2:
        return (
            "Inspiration: Der gute Topf auf dem Herd",
            (
                "Die Idee dieser Woche kommt aus der klassischen Vorratsküche: ein Topf, eine Pfanne, "
                "wenige gute Zutaten und Gerichte, die am nächsten Mittag nicht müde schmecken. "
                "Das Dessert greift den gleichen Gedanken auf: etwas Süßes, das vorbereitet ist und "
                "auch als Frühstück oder Snack funktioniert."
            ),
        )

    return (
        "Inspiration: Alltag ohne Küchenakrobatik",
        (
            "Diese Woche ist bewusst bodenständig gedacht: vertraute Familiengerichte, etwas Abwechslung "
            "durch Gewürze und ein Dessert, das süß wirkt, ohne in Richtung schwere Torte zu gehen. "
            "Der Plan soll euch nicht beeindrucken, sondern den Kühlschrank sinnvoll füllen."
        ),
    )


def build_newsletter_html(week: dict[str, object]) -> str:
    lunches = week["lunches"]
    days = week["days"]
    lunch_counts = week["lunch_counts"]
    dessert = week["dessert"]
    variant = week.get("variant", DEFAULT_VARIANT)
    variant_label = week.get("variant_label", PLAN_VARIANTS[DEFAULT_VARIANT]["label"])
    highlights = lunches[:3]
    inspiration_title, inspiration_text = build_inspiration_note(lunches, dessert)
    second_highlight_note = (
        "Für den nächsten Mittag geeignet, weil es sich gut aufwärmen lässt."
        if lunch_counts[str(highlights[1]["id"])] > 1
        else "Als frisches Einzelgericht geplant, damit keine unnötigen Reste entstehen."
    )

    week_rows = "\n".join(
        (
            f'<p style="margin:0 0 8px 0;font-size:15px;line-height:1.7;">'
            f"<strong>{escape(day['day'])}:</strong> {escape(day['lunch'])} "
            f'<span style="color:#7b6454;">({escape(day["lunch_note"])})</span></p>'
        )
        for day in days
    )
    quick_rule_html = (
        '<p style="margin:0 0 8px 0;font-size:15px;line-height:1.7;"><strong>Schnell:</strong> jedes Hauptgericht maximal ca. 30 Minuten Gesamtzeit</p>'
        if variant == "schnell"
        else ""
    )

    return f"""<!DOCTYPE html>
<html lang="de">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Meal-Prep-Newsletter</title>
  </head>
  <body style="margin:0;padding:0;background:#efe7dc;font-family:Arial,Helvetica,sans-serif;color:#2f241c;">
    <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#efe7dc;margin:0;padding:24px 0;">
      <tr><td align="center">
        <table role="presentation" width="680" cellspacing="0" cellpadding="0" style="width:680px;max-width:680px;background:#fffaf4;border-collapse:collapse;">
          <tr><td style="padding:0;background:linear-gradient(135deg,#cf7d46,#e8c7a4);">
            <div style="padding:44px 46px 34px 46px;">
              <div style="font-size:13px;letter-spacing:2px;text-transform:uppercase;color:#fff4e8;">Wochenplanung für eure Familie</div>
              <h1 style="margin:10px 0 12px 0;font-family:Georgia,'Times New Roman',serif;font-size:40px;line-height:1.1;color:#fffaf4;">Meal Prep Newsletter</h1>
              <p style="margin:0;font-size:17px;line-height:1.6;color:#fff4eb;">{escape(variant_label)}-Plan mit familienfreundlichen Mittagsgerichten, ohne geplante Abendessen und mit bewusst kleinen Restemengen.</p>
            </div>
          </td></tr>
          <tr><td style="padding:28px 40px 8px 40px;">
            <div style="background:#f6efe5;border-radius:18px;padding:24px 26px;">
              <h2 style="margin:0 0 12px 0;font-family:Georgia,'Times New Roman',serif;font-size:28px;color:#5b4335;">Diese Woche im Fokus</h2>
              <div style="font-size:12px;letter-spacing:1.6px;text-transform:uppercase;color:#a36a3d;margin-bottom:8px;">{escape(inspiration_title)}</div>
              <p style="margin:0;font-size:16px;line-height:1.7;">{escape(inspiration_text)}</p>
            </div>
          </td></tr>
          <tr><td style="padding:20px 40px 4px 40px;">
            <h2 style="margin:0 0 16px 0;font-family:Georgia,'Times New Roman',serif;font-size:30px;color:#5b4335;">Highlights</h2>
          </td></tr>
          <tr><td style="padding:0 40px 8px 40px;">
            <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#fff;border:1px solid #ead8c6;margin-bottom:18px;">
              <tr>
                <td width="42%" style="padding:0;"><img src="{IMAGES['lunch_primary']}" alt="{escape(highlights[0]['title'])}" width="252" style="display:block;width:100%;max-width:252px;height:auto;" /></td>
                <td width="58%" style="padding:22px 24px;vertical-align:top;">
                  <h3 style="margin:0 0 10px 0;font-family:Georgia,'Times New Roman',serif;font-size:24px;color:#5b4335;">{escape(highlights[0]['title'])}</h3>
                  <p style="margin:0 0 10px 0;font-size:15px;line-height:1.7;">{escape(highlights[0]['summary'])}</p>
                  <p style="margin:0;font-size:14px;line-height:1.7;color:#7b6454;">{escape(highlights[0]['child_note'])}</p>
                </td>
              </tr>
            </table>
            <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#fff;border:1px solid #ead8c6;margin-bottom:18px;">
              <tr>
                <td width="42%" style="padding:0;"><img src="{IMAGES['light_dinner']}" alt="{escape(highlights[1]['title'])}" width="252" style="display:block;width:100%;max-width:252px;height:auto;" /></td>
                <td width="58%" style="padding:22px 24px;vertical-align:top;">
                  <h3 style="margin:0 0 10px 0;font-family:Georgia,'Times New Roman',serif;font-size:24px;color:#5b4335;">{escape(highlights[1]['title'])}</h3>
                  <p style="margin:0 0 10px 0;font-size:15px;line-height:1.7;">{escape(highlights[1]['summary'])}</p>
                  <p style="margin:0;font-size:14px;line-height:1.7;color:#7b6454;">{second_highlight_note}</p>
                </td>
              </tr>
            </table>
            <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#fff;border:1px solid #ead8c6;">
              <tr>
                <td width="42%" style="padding:0;"><img src="{IMAGES['lunch_secondary']}" alt="{escape(highlights[2]['title'])}" width="252" style="display:block;width:100%;max-width:252px;height:auto;" /></td>
                <td width="58%" style="padding:22px 24px;vertical-align:top;">
                  <h3 style="margin:0 0 10px 0;font-family:Georgia,'Times New Roman',serif;font-size:24px;color:#5b4335;">{escape(highlights[2]['title'])}</h3>
                  <p style="margin:0 0 10px 0;font-size:15px;line-height:1.7;">{escape(highlights[2]['summary'])}</p>
                  <p style="margin:0;font-size:14px;line-height:1.7;color:#7b6454;">{escape(highlights[2]['child_note'])}</p>
                </td>
              </tr>
            </table>
          </td></tr>
          <tr><td style="padding:28px 40px 10px 40px;">
            <div style="background:#fff3df;border:1px solid #ead8c6;padding:24px 26px;margin-bottom:22px;">
              <div style="font-size:12px;letter-spacing:1.8px;text-transform:uppercase;color:#a36a3d;margin-bottom:8px;">Dessert der Woche</div>
              <h2 style="margin:0 0 10px 0;font-family:Georgia,'Times New Roman',serif;font-size:30px;color:#5b4335;">{escape(dessert['title'])}</h2>
              <p style="margin:0 0 10px 0;font-size:16px;line-height:1.7;">{escape(dessert['summary'])}</p>
              <p style="margin:0;font-size:14px;line-height:1.7;color:#7b6454;">{escape(dessert['prep_note'])} Das Rezept ist in den Anhängen enthalten und die Zutaten sind in der Einkaufsliste eingerechnet.</p>
            </div>
            <table role="presentation" width="100%" cellspacing="0" cellpadding="0">
              <tr>
                <td width="50%" style="padding-right:10px;vertical-align:top;">
                  <div style="background:#f8f1e8;border:1px solid #ead8c6;padding:22px;">
                    <h3 style="margin:0 0 10px 0;font-family:Georgia,'Times New Roman',serif;font-size:24px;color:#5b4335;">Wochenüberblick</h3>
                    {week_rows}
                    <p style="margin:12px 0 0 0;font-size:15px;line-height:1.7;"><strong>Abends:</strong> kein Essen geplant, nur vorhandene Reste bei Hunger.</p>
                  </div>
                </td>
                <td width="50%" style="padding-left:10px;vertical-align:top;">
                  <div style="background:#f8f1e8;border:1px solid #ead8c6;padding:22px;">
                    <h3 style="margin:0 0 10px 0;font-family:Georgia,'Times New Roman',serif;font-size:24px;color:#5b4335;">Wichtige Regeln</h3>
                    <p style="margin:0 0 8px 0;font-size:15px;line-height:1.7;"><strong>Kindgerecht:</strong> mild kochen, erst danach für Erwachsene würzen</p>
                    <p style="margin:0 0 8px 0;font-size:15px;line-height:1.7;"><strong>Abwechslung:</strong> keine Wiederholung zur Vorwoche</p>
                    {quick_rule_html}
                    <p style="margin:0 0 8px 0;font-size:15px;line-height:1.7;"><strong>Meal Prep:</strong> ein Gericht maximal am nächsten Mittag nochmal essen</p>
                    <p style="margin:0 0 8px 0;font-size:15px;line-height:1.7;"><strong>Weniger Reste:</strong> Mengen werden auf die geplanten Mittagessen heruntergerechnet</p>
                    <p style="margin:0;font-size:15px;line-height:1.7;"><strong>Abends:</strong> kein festes Gericht, nur vorhandene Reste bei Hunger</p>
                  </div>
                </td>
              </tr>
            </table>
          </td></tr>
        </table>
      </td></tr>
    </table>
  </body>
</html>
"""


def write_variant_files(variant: str, plan_markdown: str, recipes_markdown: str, shopping_html: str, newsletter_html: str) -> dict[str, Path]:
    primary_paths = output_paths(variant)
    for paths in alias_paths(variant):
        paths["plan"].write_text(plan_markdown, encoding="utf-8")
        paths["recipes"].write_text(recipes_markdown, encoding="utf-8")
        paths["shopping"].write_text(shopping_html, encoding="utf-8")
        paths["newsletter"].write_text(newsletter_html, encoding="utf-8")
    return primary_paths


def generate_weekly_files(today: date | None = None, variant: str = DEFAULT_VARIANT) -> dict[str, Path]:
    today = today or date.today()
    validate_variant(variant)
    assert_lunch_pool_health()
    week = build_week(today, variant)
    if week.get("reused"):
        return output_paths(variant)

    plan_markdown = build_plan_markdown(week)
    recipes_markdown = build_recipes_markdown(week)
    shopping_html = build_shopping_html(plan_markdown)
    newsletter_html = build_newsletter_html(week)

    return write_variant_files(variant, plan_markdown, recipes_markdown, shopping_html, newsletter_html)


def generate_all_variants(today: date | None = None) -> dict[str, dict[str, Path]]:
    today = today or date.today()
    assert_lunch_pool_health()
    week_key = current_week_key(today)
    state = load_state()
    if all(
        state.get("variants", {}).get(variant, {}).get("last_generated_week") == week_key
        and state.get("variants", {}).get(variant, {}).get("generator_version") == GENERATOR_VERSION
        and all(path.exists() for path_group in alias_paths(variant) for path in path_group.values())
        for variant in PLAN_VARIANTS
    ):
        return {variant: output_paths(variant) for variant in PLAN_VARIANTS}

    reserved_lunch_ids: set[str] = set()
    selected_weeks: dict[str, dict[str, object]] = {}
    variant_order = sorted(PLAN_VARIANTS, key=lambda variant: len(filtered_lunch_pool(variant)))

    def backtrack(index: int) -> bool:
        if index == len(variant_order):
            return True

        variant = variant_order[index]
        variant_state = state.get("variants", {}).get(variant, {})
        last_lunch_ids = set(variant_state.get("last_lunch_ids", []))
        seed = variant_seed(today, variant)
        lunch_pool = filtered_lunch_pool(variant)
        next_day_pool = [dish for dish in lunch_pool if dish["id"] in NEXT_DAY_LUNCH_IDS]
        same_day_pool = [dish for dish in lunch_pool if dish["id"] not in NEXT_DAY_LUNCH_IDS]

        for lunches, _meta in candidate_lunch_sets(
            next_day_pool,
            same_day_pool,
            last_lunch_ids,
            reserved_lunch_ids,
            seed,
        ):
            selected_weeks[variant] = assemble_week(today, variant, variant_state, lunches)
            reserved_lunch_ids.update(item["id"] for item in lunches)
            if backtrack(index + 1):
                return True
            reserved_lunch_ids.difference_update(item["id"] for item in lunches)
            selected_weeks.pop(variant, None)
        return False

    if not backtrack(0):
        raise RuntimeError("Keine überschneidungsfreie Lunch-Auswahl für alle Varianten gefunden.")

    output_map: dict[str, dict[str, Path]] = {}
    variants_state = dict(state.get("variants", {}))
    for variant in PLAN_VARIANTS:
        week = selected_weeks[variant]
        plan_markdown = build_plan_markdown(week)
        recipes_markdown = build_recipes_markdown(week)
        shopping_html = build_shopping_html(plan_markdown)
        newsletter_html = build_newsletter_html(week)
        output_map[variant] = write_variant_files(
            variant,
            plan_markdown,
            recipes_markdown,
            shopping_html,
            newsletter_html,
        )
        max_ids = STATE_MEMORY_WEEKS * WEEKLY_UNIQUE_LUNCHES
        prev = variants_state.get(variant, {})
        new_l = [item["id"] for item in week["lunches"]]
        old_l = [i for i in prev.get("last_lunch_ids", []) if i not in new_l]
        new_d = week["dessert"]["id"]
        old_d = [i for i in prev.get("last_dessert_ids", []) if i != new_d]
        variants_state[variant] = {
            "last_generated_week": week_key,
            "generator_version": GENERATOR_VERSION,
            "last_lunch_ids": (new_l + old_l)[:max_ids],
            "last_dessert_ids": ([new_d] + old_d)[:STATE_MEMORY_WEEKS],
        }

    state["variants"] = variants_state
    state.update(variants_state[DEFAULT_VARIANT])
    state.pop("last_dinner_ids", None)
    save_state(state)
    return output_map


def export_weeks_json(weeks_ahead: int = 3, out_path: Path | None = None) -> Path:
    """Export current week + weeks_ahead future weeks to weeks.json for the web app."""
    assert_lunch_pool_health()
    today = date.today()
    out_path = out_path or BASE_DIR / "weeks.json"

    this_monday = today - timedelta(days=today.weekday())
    state = load_state()
    weeks_output: list[dict[str, object]] = []

    for week_offset in range(weeks_ahead + 1):
        monday = this_monday + timedelta(weeks=week_offset)
        sunday = monday + timedelta(days=6)
        week_key = current_week_key(monday)

        reserved_lunch_ids: set[str] = set()
        selected_weeks: dict[str, dict[str, object]] = {}
        variant_order = sorted(PLAN_VARIANTS, key=lambda v: len(filtered_lunch_pool(v)))

        def backtrack(index: int) -> bool:
            if index == len(variant_order):
                return True
            variant = variant_order[index]
            variant_state = state.get("variants", {}).get(variant, {})
            last_lunch_ids = set(variant_state.get("last_lunch_ids", []))
            seed = variant_seed(monday, variant)
            lunch_pool = filtered_lunch_pool(variant)
            next_day_pool = [d for d in lunch_pool if d["id"] in NEXT_DAY_LUNCH_IDS]
            same_day_pool = [d for d in lunch_pool if d["id"] not in NEXT_DAY_LUNCH_IDS]
            for lunches, _meta in candidate_lunch_sets(
                next_day_pool, same_day_pool, last_lunch_ids, reserved_lunch_ids, seed,
            ):
                selected_weeks[variant] = assemble_week(monday, variant, variant_state, lunches)
                reserved_lunch_ids.update(item["id"] for item in lunches)
                if backtrack(index + 1):
                    return True
                reserved_lunch_ids.difference_update(item["id"] for item in lunches)
                selected_weeks.pop(variant, None)
            return False

        if not backtrack(0):
            raise RuntimeError(f"Keine überschneidungsfreie Lunch-Auswahl für {week_key} gefunden.")

        variants_state = dict(state.get("variants", {}))
        max_ids = STATE_MEMORY_WEEKS * WEEKLY_UNIQUE_LUNCHES
        for variant in PLAN_VARIANTS:
            w = selected_weeks[variant]
            prev = variants_state.get(variant, {})
            new_l = [item["id"] for item in w["lunches"]]
            old_l = [i for i in prev.get("last_lunch_ids", []) if i not in new_l]
            new_d = w["dessert"]["id"]
            old_d = [i for i in prev.get("last_dessert_ids", []) if i != new_d]
            variants_state[variant] = {
                "last_generated_week": week_key,
                "generator_version": GENERATOR_VERSION,
                "last_lunch_ids": (new_l + old_l)[:max_ids],
                "last_dessert_ids": ([new_d] + old_d)[:STATE_MEMORY_WEEKS],
            }

        if week_offset == 0:
            real_state = dict(state)
            real_state["variants"] = variants_state
            real_state.update(variants_state[DEFAULT_VARIANT])
            real_state.pop("last_dinner_ids", None)
            save_state(real_state)

        state = dict(state)
        state["variants"] = variants_state

        week_entry: dict[str, object] = {
            "week_key": week_key,
            "monday": monday.isoformat(),
            "sunday": sunday.isoformat(),
            "variants": {},
        }
        for variant in PLAN_VARIANTS:
            w = selected_weeks[variant]
            shopping_groups = build_shopping_groups(w["lunches"], w["lunch_counts"], w["dessert"])
            week_entry["variants"][variant] = {  # type: ignore[index]
                "label": PLAN_VARIANTS[variant]["label"],
                "description": PLAN_VARIANTS[variant]["description"],
                "days": w["days"],
                "lunches": [_serialize_recipe(r) for r in w["lunches"]],
                "dessert": _serialize_recipe(w["dessert"]),
                "shopping": _serialize_shopping(shopping_groups),
            }
        weeks_output.append(week_entry)

    result: dict[str, object] = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "weeks": weeks_output,
    }
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Meal-Prep-Wochenplan generieren.")
    parser.add_argument(
        "--variant",
        choices=[*PLAN_VARIANTS, "all"],
        default=DEFAULT_VARIANT,
        help="Welche Plan-Variante erzeugt werden soll.",
    )
    parser.add_argument(
        "--pool-report",
        action="store_true",
        help="Kapazitätsbericht für den aktuellen Gerichtspool ausgeben.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="weeks.json für die Web-App exportieren (aktuelle + Folgewochen).",
    )
    parser.add_argument(
        "--weeks-ahead",
        type=int,
        default=3,
        metavar="N",
        help="Anzahl der Folgewochen für --json (Standard: 3).",
    )
    args = parser.parse_args()
    if args.pool_report:
        print(format_lunch_pool_report())
    elif args.json:
        out = export_weeks_json(weeks_ahead=args.weeks_ahead)
        print(f"weeks.json geschrieben: {out}")
    elif args.variant == "all":
        generate_all_variants()
    else:
        generate_weekly_files(variant=args.variant)
