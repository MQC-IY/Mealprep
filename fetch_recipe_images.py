#!/usr/bin/env python3
"""
fetch_recipe_images.py
----------------------
Fetches Unsplash photos for all 300 recipes → recipe_images.json
Resumable: skips already-fetched IDs.
Rate-aware: bursts up to 48 per slot, then sleeps until the hour resets.

Run once and leave it — completes all 300 in ~6 hours overnight.
    python3 fetch_recipe_images.py
"""

import json, re, time, urllib.request, urllib.parse
from pathlib import Path
from datetime import datetime

# Load from .env (UNSPLASH_ACCESS_KEY=...) or environment variable
import os as _os
_env = Path(__file__).parent / ".env"
if _env.exists():
    for _l in _env.read_text().splitlines():
        if _l.startswith("UNSPLASH_ACCESS_KEY="):
            _os.environ.setdefault("UNSPLASH_ACCESS_KEY", _l.split("=", 1)[1].strip())
ACCESS_KEY = _os.environ.get("UNSPLASH_ACCESS_KEY", "")
if not ACCESS_KEY:
    raise SystemExit("Set UNSPLASH_ACCESS_KEY=<key> in .env or environment")
GENERATOR  = Path(__file__).parent / "meal_plan_generator.py"
OUT        = Path(__file__).parent / "recipe_images.json"
BURST_SIZE = 48          # leave 2 spare per hour slot as safety buffer
BURST_GAP  = 2.5        # seconds between requests within a burst

# ── Search term overrides ─────────────────────────────────────────────────────
# For IDs where the raw snake_case → English translation gives poor image results.
OVERRIDES = {
    "zosui_chicken_rice_porridge":   "japanese rice porridge okayu",
    "yosenabe_tofu_chicken":         "japanese hot pot nabe",
    "dak_galbi_cheese_bake":         "korean cheese chicken bake",
    "tteokbokki_gnocchi_pan":        "korean spicy rice cake tteokbokki",
    "kongnamul_chicken_rice":        "korean bean sprout rice bowl",
    "yukgaejang_beef_soup":          "korean spicy beef soup",
    "sundubu_jjigae_tofu":           "korean soft tofu stew",
    "doenjang_jjigae":               "korean fermented soybean stew",
    "bun_bo_nam_bo":                 "vietnamese beef noodle salad",
    "canh_chua_fish_soup":           "vietnamese sour fish soup",
    "bo_luc_lac_wok_beef":           "vietnamese shaking beef wok",
    "san_bei_ji_chicken":            "three cup chicken taiwanese",
    "mapo_tofu_pork":                "mapo tofu sichuan",
    "dan_dan_noodles":               "dan dan noodles chinese",
    "ghormeh_sabzi":                 "persian herb lamb stew",
    "fesenjaan_chicken":             "persian walnut pomegranate chicken",
    "koshari_egyptian":              "egyptian koshari lentil rice",
    "kafta_tomato_potato":           "middle eastern meatball tomato",
    "mujaddara_lentil_rice":         "lentil rice caramelised onion",
    "arabic_machboos_chicken":       "spiced arabian rice chicken",
    "ribollita_tuscan_soup":         "tuscan bread vegetable soup",
    "pasta_e_fagioli":               "italian pasta bean soup",
    "soupe_au_pistou":               "french provencal vegetable soup",
    "tegamaccio_fish_stew":          "italian fish stew seafood",
    "salsiccia_lentils_kale":        "italian sausage lentil kale",
    "gnocchi_amatriciana":           "pasta amatriciana tomato",
    "blanquette_de_poulet":          "french creamy chicken stew",
    "poulet_provencale":             "provencal chicken herbs olives",
    "cassoulet_french":              "french cassoulet bean duck",
    "boeuf_bourguignon_chicken":     "french red wine chicken stew",
    "pollo_catalana":                "catalan chicken almond olive",
    "arroz_caldoso_chicken":         "spanish soupy rice chicken",
    "fabada_white_bean_stew":        "spanish white bean chorizo stew",
    "pasta_con_sarde":               "pasta sardines sicilian",
    "patlican_musakka":              "turkish eggplant moussaka",
    "hunkar_begendi":                "turkish chicken eggplant puree",
    "imam_bayildi_chicken":          "turkish stuffed eggplant",
    "kuru_fasulye_beans":            "turkish white bean stew",
    "turkish_guvec_chicken":         "turkish clay pot chicken stew",
    "turkish_beyran_chicken":        "turkish meat rice soup",
    "turkish_kisir_bowl":            "turkish bulgur salad bowl",
    "greek_giouvetsi":               "greek chicken orzo bake",
    "greek_fassolada":               "greek white bean soup",
    "greek_revithia":                "greek chickpea stew",
    "greek_pastitsio":               "greek pasta bake bechamel",
    "swabian_lentils_spaetzle":      "german lentils spaetzle",
    "german_sauerbraten_chicken":    "german pot roast gravy",
    "german_barley_vegetable_stew":  "barley vegetable soup",
    "polish_bigos":                  "polish hunter stew sauerkraut",
    "polish_zurek_soup":             "polish sour rye soup egg",
    "romanian_chicken_mamaliga":     "chicken polenta",
    "czech_svickova_chicken":        "czech cream sauce roast",
    "bulgarian_kavarma_chicken":     "bulgarian chicken stew",
    "austrian_chicken_cream_stew":   "austrian cream chicken",
    "hungarian_chicken_paprikas":    "hungarian chicken paprika",
    "pozole_rojo_chicken":           "mexican pozole red soup",
    "chicken_tinga_chipotle":        "mexican shredded chipotle chicken",
    "sopa_de_lima":                  "mexican lime chicken soup",
    "lomo_saltado_peru":             "peruvian stir fry beef potato",
    "ajiaco_colombiano":             "colombian chicken potato soup",
    "chicken_mole_rojo":             "mexican mole chicken sauce",
    "west_african_jollof_rice":      "jollof rice west african",
    "ghanaian_peanut_chicken_stew":  "african peanut groundnut chicken stew",
    "ethiopian_doro_wat":            "ethiopian chicken stew spiced",
    "ethiopian_misir_wot":           "ethiopian red lentil stew",
    "south_african_bobotie":         "south african bobotie minced meat",
    "nigerian_suya_chicken":         "nigerian suya grilled chicken",
    "south_african_chicken_potjie":  "south african potjie stew",
    "kenyan_chicken_plantain":       "african chicken coconut plantain",
    "tanzanian_pilau_rice_chicken":  "east african spiced pilau rice",
    "sabich_chicken_bowl":           "israeli sabich eggplant tahini bowl",
    "fatteh_chicken_bowl":           "levantine chickpea flatbread bowl",
    "carnitas_bowl_mexican":         "mexican carnitas pork bowl",
    "zhug_chicken_rice":             "yemeni green chili sauce chicken",
    "achiote_chicken_tacos":         "achiote chicken tacos mexican",
    "jerk_chicken_coconut_rice":     "jamaican jerk chicken coconut rice",
    "rendang_chicken_jasmine_rice":  "indonesian rendang chicken rice",
    "quick_tikka_bowl":              "tikka masala chicken bowl",
    "quick_pho_bowl":                "vietnamese pho noodle soup bowl",
    "adana_chicken_bulgur":          "turkish adana grilled chicken",
    "black_sesame_chicken_soba":     "sesame chicken soba noodles",
    "chicken_kofta_tabbouleh":       "middle eastern kofta tabbouleh",
    "ras_el_hanout_chicken_eggplant":"moroccan spiced chicken eggplant",
    "berbere_chicken_couscous":      "ethiopian berbere chicken couscous",
    "shawarma_chicken_bowl":         "shawarma chicken bowl hummus",
    "souvlaki_chicken_bowl":         "greek souvlaki chicken bowl",
    "hayashi_rice_chicken":          "japanese hayashi rice demi-glace",
    "nikujaga_potato_stew":          "japanese meat potato stew",
    "karaage_chicken_rice":          "japanese fried chicken karaage",
    "miso_ramen_chicken":            "miso ramen noodle soup",
    "katsu_curry_chicken":           "japanese katsu curry rice",
    "kongnamul_chicken_rice":        "korean bean sprout rice",
    "bibimbap_chicken_veg":          "bibimbap korean rice bowl",
    "dakgalbi_spicy_chicken":        "korean spicy chicken stir fry",
    "bulgogi_rice_bowl":             "korean bulgogi beef rice",
    "japchae_glass_noodles":         "korean glass noodles stir fry",
    "kimchi_fried_rice_chicken":     "kimchi fried rice",
    "gochujang_chicken_sesame_rice": "korean gochujang chicken rice",
    "dak_galbi_cheese_bake":         "korean cheese chicken bake",
    "pad_thai_chicken":              "pad thai noodles",
    "pad_krapao_chicken":            "thai basil chicken stir fry",
    "thai_basil_fried_rice":         "thai basil fried rice",
    "tom_kha_gai":                   "thai coconut chicken soup",
    "massaman_curry_chicken":        "massaman curry thai",
    "pho_ga_chicken":                "vietnamese chicken pho",
    "vietnamese_lemongrass_chicken": "vietnamese lemongrass chicken",
    "kung_pao_chicken":              "kung pao chicken sichuan",
    "chinese_cashew_chicken":        "chinese cashew chicken stir fry",
    "chinese_beef_broccoli":         "chinese beef broccoli",
    "chinese_beef_daikon_stew":      "chinese braised beef daikon",
    "congee_chicken":                "chicken congee rice porridge",
    "chinese_chicken_glass_noodles": "chinese chicken glass noodles",
    "chinese_pork_tofu_pan":         "chinese pork tofu stir fry",
    "butter_chicken_basmati":        "butter chicken murgh makhani",
    "palak_chicken":                 "palak chicken spinach curry",
    "chicken_tikka_masala":          "chicken tikka masala curry",
    "saag_aloo":                     "saag aloo spinach potato",
    "rajma_curry":                   "rajma kidney bean curry",
    "indian_yogurt_chicken_spinach": "indian yogurt chicken spinach",
    "aloo_gobi":                     "aloo gobi cauliflower potato",
    "chicken_biryani":               "chicken biryani rice",
    "moroccan_chicken_tagine":       "moroccan chicken tagine olives",
    "moroccan_harira":               "moroccan harira lentil soup",
    "chermoula_chicken_couscous":    "moroccan chermoula chicken couscous",
    "tunisian_shakshuka_chicken":    "shakshuka eggs tomato",
    "zaatar_chicken_rice":           "zaatar chicken levantine",
    "libanesische_fatteh_bowl":      "levantine chickpea fatteh",
    "coq_au_vin":                    "coq au vin french",
    "poulet_basquaise":              "basque chicken peppers",
    "lentil_soup_auvergnat":         "french lentil soup",
    "pollo_al_ajillo":               "spanish garlic chicken",
    "spanish_paella_chicken":        "paella spanish rice",
    "spanish_chicken_chorizo":       "spanish chicken chorizo stew",
    "pisto_manchego_chicken":        "spanish ratatouille chicken",
    "pollo_alla_cacciatore":         "chicken cacciatore italian",
    "chicken_scaloppine_capers":     "chicken scaloppine lemon capers",
    "chicken_ossobuco_style":        "braised chicken italian white wine",
    "iskender_kebab_style":          "iskender kebab yogurt",
    "greek_souvlaki_chicken":        "greek souvlaki grilled chicken",
    "hungarian_beef_goulash":        "hungarian beef goulash",
    "serbian_pasulj":                "serbian bean stew",
    "enchiladas_rojas_chicken":      "enchiladas rojas mexican",
    "arroz_con_pollo":               "arroz con pollo rice chicken",
    "lomo_saltado_peru":             "peruvian lomo saltado stir fry",
    "philippine_chicken_adobo":      "filipino chicken adobo",
    "indonesian_rendang_chicken":    "indonesian rendang beef chicken",
    "malaysian_laksa_chicken":       "malaysian laksa noodle soup",
    "hainanese_chicken_rice":        "hainanese chicken rice singapore",
    "sambal_chicken_coconut_rice":   "sambal chicken coconut rice",
    "soto_ayam_indonesia":           "soto ayam indonesian chicken soup",
    "korean_buddha_bowl":            "korean buddha bowl healthy",
    "teriyaki_bowl_edamame":         "teriyaki bowl edamame",
    "moroccan_harissa_chicken_bowl": "moroccan harissa chicken bowl",
    "southeast_asian_peanut_chicken":"peanut satay chicken bowl",
    "thai_green_curry_tofu":         "thai green curry tofu",
    "massaman_chicken_bowl":         "massaman curry chicken bowl",
    "chermoula_chicken_quinoa_bowl": "chermoula chicken quinoa bowl",
    "teriyaki_glass_noodles_chicken":"teriyaki glass noodles chicken",
    "tikka_chicken_bowl":            "tikka chicken rice bowl",
}


def id_to_query(recipe_id: str) -> str:
    """Convert recipe ID to an Unsplash search query."""
    if recipe_id in OVERRIDES:
        return OVERRIDES[recipe_id]
    q = recipe_id.replace("_", " ")
    # Strip redundant trailing words that crowd search results
    for suffix in [" style", " inspired", " veg"]:
        if q.endswith(suffix):
            q = q[:-len(suffix)]
    return q.strip()


def fetch_photo(query: str):
    """Return (result_dict, remaining, reset_ts) or raise."""
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
        remaining  = int(resp.headers.get("X-Ratelimit-Remaining", 50))
        reset_ts   = int(resp.headers.get("X-Ratelimit-Reset", 0))
        data       = json.loads(resp.read())

    results = data.get("results", [])
    if not results:
        return None, remaining, reset_ts

    photo = results[0]
    raw   = photo["urls"]["raw"]       # base URL — append &w=...&h=...&fit=crop
    credit      = photo["user"]["name"]
    credit_url  = (photo["user"]["links"]["html"]
                   + "?utm_source=mahlzeit_app&utm_medium=referral")
    return {"raw": raw, "credit": credit, "credit_url": credit_url}, remaining, reset_ts


def extract_ids() -> list[str]:
    """Return unique recipe IDs from LUNCH_POOL in the generator."""
    src  = GENERATOR.read_text()
    ids  = re.findall(r'"id":\s*"([^"]+)"', src)
    seen, unique = set(), []
    for i in ids:
        if i not in seen:
            seen.add(i)
            unique.append(i)
    return unique


def main():
    existing: dict = {}
    if OUT.exists():
        existing = json.loads(OUT.read_text())
    print(f"Already fetched: {len(existing)}")

    all_ids  = extract_ids()
    to_fetch = [i for i in all_ids if i not in existing]
    total    = len(to_fetch)
    print(f"Need to fetch:   {total} recipes")
    if not total:
        print("Nothing to do.")
        return

    done = 0
    while to_fetch:
        # Burst: fetch up to BURST_SIZE before sleeping
        burst = to_fetch[:BURST_SIZE]
        for recipe_id in burst:
            query = id_to_query(recipe_id)
            print(f"[{done+1}/{total}] {recipe_id:<45} '{query}' … ", end="", flush=True)
            try:
                result, remaining, reset_ts = fetch_photo(query)
                if result:
                    existing[recipe_id] = result
                    print(f"✓  (rate: {remaining} left)")
                else:
                    # Fallback: generic food + first word
                    fallback = "food " + query.split()[0]
                    result2, remaining, reset_ts = fetch_photo(fallback)
                    if result2:
                        existing[recipe_id] = result2
                        print(f"✓ (fallback '{fallback}')  (rate: {remaining} left)")
                    else:
                        existing[recipe_id] = None
                        print(f"✗ no image")
            except urllib.error.HTTPError as e:
                if e.code == 429:
                    print("⏳ rate-limited — sleeping 3600 s")
                    time.sleep(3600)
                    continue   # retry same ID
                else:
                    print(f"✗ HTTP {e.code}")
                    existing[recipe_id] = None
            except Exception as e:
                print(f"✗ {e}")
                existing[recipe_id] = None

            OUT.write_text(json.dumps(existing, indent=2, ensure_ascii=False))
            done += 1
            to_fetch.pop(0)

            if remaining <= 1 and to_fetch:
                # Determine how long to sleep
                now = int(time.time())
                if reset_ts and reset_ts > now:
                    sleep_for = reset_ts - now + 5
                else:
                    sleep_for = 3600
                wake = datetime.fromtimestamp(now + sleep_for).strftime('%H:%M:%S')
                print(f"\n  ⏳  Rate slot exhausted — sleeping {sleep_for}s (until ~{wake})")
                print(f"  Progress: {done}/{total} done, {len(to_fetch)} remaining\n")
                time.sleep(sleep_for)
                break  # restart outer while → next burst

            time.sleep(BURST_GAP)

    success = sum(1 for v in existing.values() if v)
    print(f"\nDone. {success}/{len(existing)} images fetched → {OUT}")


if __name__ == "__main__":
    main()
