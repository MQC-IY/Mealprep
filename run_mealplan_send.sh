#!/bin/zsh
set -eu

REPO_DIR="$HOME/Documents/Meal_prep"
cd "$REPO_DIR"

{
  echo "[$(/bin/date '+%Y-%m-%d %H:%M:%S')] Starte Meal-Prep-Versand"
  /usr/bin/python3 -B send_meal_plan.py
  echo "[$(/bin/date '+%Y-%m-%d %H:%M:%S')] Meal-Prep-Versand beendet"
} >> "$REPO_DIR/mealprep_automation.log" 2>&1
