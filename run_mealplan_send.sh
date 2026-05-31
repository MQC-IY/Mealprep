#!/bin/zsh
set -eu

REPO_DIR="$HOME/Documents/Meal_prep"
cd "$REPO_DIR"

{
  echo "[$(/bin/date '+%Y-%m-%d %H:%M:%S')] Starte wöchentlichen Meal-Prep-Lauf"

  # 1. Regenerate weeks.json (current week + 3 ahead)
  echo "[$(/bin/date '+%Y-%m-%d %H:%M:%S')] Generiere weeks.json …"
  /usr/bin/python3 -B meal_plan_generator.py --json

  # 2. Push updated data to GitHub Pages
  echo "[$(/bin/date '+%Y-%m-%d %H:%M:%S')] Pushe weeks.json nach GitHub …"
  git add weeks.json
  git diff --cached --quiet || git commit -m "Wochenplan Update $(/bin/date '+%Y-%m-%d')"
  git push origin main

  echo "[$(/bin/date '+%Y-%m-%d %H:%M:%S')] Fertig."
} >> "$REPO_DIR/mealprep_automation.log" 2>&1
