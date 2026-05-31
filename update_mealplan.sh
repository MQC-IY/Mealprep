#!/bin/zsh
set -eu

REPO_DIR="$HOME/Documents/Meal_prep"
cd "$REPO_DIR"

{
  echo "[$(/bin/date '+%Y-%m-%d %H:%M:%S')] Starte Wochenplan-Update"

  /usr/bin/python3 -B meal_plan_generator.py --json
  echo "[$(/bin/date '+%Y-%m-%d %H:%M:%S')] weeks.json generiert"

  git add weeks.json
  git diff --cached --quiet || git commit -m "Wochenplan Update $(/bin/date '+%Y-%m-%d')"
  git push origin main
  echo "[$(/bin/date '+%Y-%m-%d %H:%M:%S')] GitHub Pages aktualisiert"

} >> "$REPO_DIR/mealplan_update.log" 2>&1
