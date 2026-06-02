# Mahlzeit — Familien Meal-Prep App

A private progressive web app (PWA) for weekly meal planning. The app shows this week's meal plan and upcoming weeks, replacing the weekly email. Opens in any browser, installs like a native app on iPhone or Android — no App Store needed.

**Live URL:** https://mqc-iy.github.io/Mealprep/

---

## What the app does

Each week the app shows a full **Mon–Sun meal plan** with breakfast, lunch, snack, and a dessert of the week. There is no dinner — evenings use leftovers by design. Plans are generated for 4 adults.

Three plan variants are available:

| Variant | Description |
|---|---|
| **Standard** | Family-friendly, normal effort |
| **Gesund** | More vegetables, legumes, wholegrains, light sauces |
| **Schnell** | Main dishes under ~30 minutes |

Each variant includes a **shopping list** organised by category. Items can be ticked off as you shop, and the full list can be copied to the clipboard.

The **Rezepte** view shows all recipes across all weeks as a searchable card grid with photos, prep times, and **calorie values per serving**.

### Language

The app is available in **German (DE)** and **English (EN)**. Use the language toggle in the header to switch. All UI labels, meal category names, and shopping list categories switch instantly — no reload needed.

---

## Install on iPhone (Add to Home Screen)

1. Open **Safari** on your iPhone and go to:
   ```
   https://mqc-iy.github.io/Mealprep/
   ```
2. Tap the **Share** button (box with an arrow pointing up) at the bottom of the screen.
3. Scroll down and tap **"Add to Home Screen"**.
4. Keep the name **Mahlzeit** and tap **Add** in the top-right corner.

The Mahlzeit icon now appears on your home screen. Tap it to open the app in full-screen mode, just like a native app. It works offline after the first load.

> **Note:** Installation only works in **Safari** on iPhone. Chrome and Firefox on iOS do not support PWA installation.

---

## Install on Android (Add to Home Screen)

1. Open **Chrome** on your Android device and go to:
   ```
   https://mqc-iy.github.io/Mealprep/
   ```
2. Tap the **three-dot menu** (⋮) in the top-right corner.
3. Tap **"Add to Home screen"**.
4. Confirm by tapping **Add**.

The Mahlzeit icon will appear on your home screen and launcher. It opens in standalone mode without browser chrome, just like a native app.

> **Note:** Chrome is recommended. Other Android browsers may also support installation but behaviour varies.

---

## How the meal plan is updated

A GitHub Actions job runs automatically every **Monday at 07:00 UTC** and regenerates `weeks.json` with a fresh plan for the coming week. The app picks up the new data on next open (network-first caching). No action needed from users.

---

## Tech stack

- Single-page HTML/JS app — no framework, no build step
- Data served as static JSON from GitHub Pages
- Service worker for offline support and fast repeat loads
- Recipe pool: 300 recipes (Standard), 186 (Gesund), 138 (Schnell)

---

## Local development

```bash
# Serve locally on port 8787
python3 -m http.server 8787
# Then open: http://localhost:8787
```

To regenerate the meal plan manually:

```bash
python3 meal_plan_generator.py
```
