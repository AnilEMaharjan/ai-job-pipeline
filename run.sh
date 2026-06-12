#!/usr/bin/env bash
# Friendly launcher — no Python/venv knowledge needed.
#   ./run.sh             → open the dashboard
#   ./run.sh fetch       → pull new jobs
#   ./run.sh score       → AI-score new jobs
#   ./run.sh update      → fetch + score, then open the dashboard
set -e
cd "$(dirname "$0")"

if [ ! -d .venv ]; then
  echo "First run setup hasn't happened yet — running ./setup.sh for you..."
  ./setup.sh
fi
source .venv/bin/activate

case "${1:-dashboard}" in
  dashboard) python pipeline.py dashboard ;;
  fetch)     python pipeline.py fetch ;;
  score)     python pipeline.py score ;;
  update)    python pipeline.py fetch && python pipeline.py score && python pipeline.py dashboard ;;
  *)         python pipeline.py "$@" ;;
esac
