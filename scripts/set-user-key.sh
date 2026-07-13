#!/usr/bin/env bash
# Switch a provisioned user between the shared host key and their own
# Anthropic key — at any time, without reprovisioning. Only that user's
# instance is affected; others are untouched.
#
# Usage:
#   scripts/set-user-key.sh <username> sk-ant-...   # give them their own key (they pay)
#   scripts/set-user-key.sh <username> --shared      # revert to the shared host key (host pays)
set -euo pipefail

USER_NAME="${1:?usage: set-user-key.sh <username> <sk-ant-...|--shared>}"
KEY_ARG="${2:?provide an sk-ant-... key or --shared}"

ROOT="$HOME/jobpipe"
DEST="$ROOT/users/$USER_NAME"
SHARED_ENV="$ROOT/shared.env"
ENV_FILE="$DEST/.env"

[ -d "$DEST" ] || { echo "No instance for '$USER_NAME' at $DEST"; exit 1; }

if [ "$KEY_ARG" = "--shared" ]; then
  [ -f "$SHARED_ENV" ] || { echo "Missing $SHARED_ENV"; exit 1; }
  cp "$SHARED_ENV" "$ENV_FILE"
  echo "==> '$USER_NAME' reverted to the SHARED host key (host pays)."
else
  case "$KEY_ARG" in
    sk-ant-*) : ;;
    *) echo "That doesn't look like an Anthropic key (expected sk-ant-...). Aborting."; exit 1 ;;
  esac
  printf 'ANTHROPIC_API_KEY=%s\n' "$KEY_ARG" > "$ENV_FILE"
  echo "==> '$USER_NAME' now uses THEIR OWN key (they pay). Your shared budget is off the hook for them."
fi
chmod 600 "$ENV_FILE"

# Restart the dashboard so an in-process client picks up the new key. The daily
# fetch/score is a fresh process each run, so it reads the new key automatically.
launchctl kickstart -k "gui/$(id -u)/com.jobpipe.$USER_NAME.dashboard" 2>/dev/null \
  && echo "==> Restarted $USER_NAME's dashboard." \
  || echo "(dashboard service not loaded; it'll use the new key next start)"

echo "Done. New key takes effect immediately for the daily run and any new scoring."
