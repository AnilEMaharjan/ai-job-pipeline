#!/usr/bin/env bash
# Pull the latest code + deps into every provisioned user instance, then
# restart their dashboards. Config/data/.env are gitignored, so they're untouched.
set -euo pipefail
ROOT="$HOME/jobpipe/users"
[ -d "$ROOT" ] || { echo "No users at $ROOT"; exit 0; }

for dir in "$ROOT"/*/; do
  name="$(basename "$dir")"
  echo "==> Updating $name"
  cd "$dir"
  git pull --ff-only
  ./.venv/bin/pip install --quiet -r requirements.txt
  launchctl kickstart -k "gui/$(id -u)/com.jobpipe.$name.dashboard" 2>/dev/null || true
done
echo "✅ All instances updated and dashboards restarted."
