#!/usr/bin/env bash
# Provision a new per-user job-pipeline instance on the always-on Mac.
# Each user is an independent git clone with its own config/, data/, port, and
# launchd services. All instances share ONE Anthropic key (the host pays).
#
# Usage:
#   scripts/new-user.sh <username> <port> <tailscale_ip>
# Example:
#   scripts/new-user.sh alice 8767 100.101.102.103
#
# Prereqs on the host Mac: git, python3.11+, tailscale (logged in), and a
# shared key file at ~/jobpipe/shared.env containing:  ANTHROPIC_API_KEY=sk-ant-...
set -euo pipefail

USER_NAME="${1:?usage: new-user.sh <username> <port> <tailscale_ip>}"
PORT="${2:?need a port, e.g. 8767}"
TS_IP="${3:?need the Mac's Tailscale IP (tailscale ip -4)}"

REPO_URL="https://github.com/AnilEMaharjan/ai-job-pipeline.git"
ROOT="$HOME/jobpipe"
DEST="$ROOT/users/$USER_NAME"
SHARED_ENV="$ROOT/shared.env"

[ -f "$SHARED_ENV" ] || { echo "Missing $SHARED_ENV (put ANTHROPIC_API_KEY=... there, chmod 600)"; exit 1; }
[ -e "$DEST" ] && { echo "$DEST already exists — pick a new name or remove it first."; exit 1; }

echo "==> Cloning into $DEST"
mkdir -p "$ROOT/users"
git clone --depth 1 "$REPO_URL" "$DEST"
cd "$DEST"

echo "==> Python venv + deps"
python3 -m venv .venv
./.venv/bin/pip install --quiet --upgrade pip
./.venv/bin/pip install --quiet -r requirements.txt

echo "==> Seeding config from templates (user fills these in)"
cp config/resume.example.json config/resume.json
cp config/personal.example.json config/personal.json
cp config/candidate_notes.example.md config/candidate_notes.md

echo "==> Wiring the shared Anthropic key (host pays)"
cp "$SHARED_ENV" .env            # pipeline.py loads .env as an optional fallback
chmod 600 .env

echo "==> Writing launchd services"
LA="$HOME/Library/LaunchAgents"
mkdir -p "$LA"
PY="$DEST/.venv/bin/python"

# Dashboard: always running, bound to the Tailscale IP (tailnet-only reachable).
cat > "$LA/com.jobpipe.$USER_NAME.dashboard.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.jobpipe.$USER_NAME.dashboard</string>
  <key>ProgramArguments</key>
    <array><string>$PY</string><string>pipeline.py</string><string>dashboard</string>
    <string>--host</string><string>$TS_IP</string><string>--port</string><string>$PORT</string></array>
  <key>WorkingDirectory</key><string>$DEST</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>$DEST/dashboard.log</string>
  <key>StandardErrorPath</key><string>$DEST/dashboard.log</string>
</dict></plist>
PLIST

# Daily fetch + score at 6am (host pays for this user's scoring).
cat > "$LA/com.jobpipe.$USER_NAME.daily.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.jobpipe.$USER_NAME.daily</string>
  <key>ProgramArguments</key>
    <array><string>/bin/bash</string><string>-lc</string>
    <string>cd $DEST && $PY pipeline.py fetch && $PY pipeline.py score</string></array>
  <key>StartCalendarInterval</key><dict><key>Hour</key><integer>6</integer><key>Minute</key><integer>0</integer></dict>
  <key>StandardOutPath</key><string>$DEST/daily.log</string>
  <key>StandardErrorPath</key><string>$DEST/daily.log</string>
</dict></plist>
PLIST

launchctl unload "$LA/com.jobpipe.$USER_NAME.dashboard.plist" 2>/dev/null || true
launchctl unload "$LA/com.jobpipe.$USER_NAME.daily.plist" 2>/dev/null || true
launchctl load "$LA/com.jobpipe.$USER_NAME.dashboard.plist"
launchctl load "$LA/com.jobpipe.$USER_NAME.daily.plist"

cat <<DONE

✅ Provisioned '$USER_NAME'
   Dashboard: http://$TS_IP:$PORT   (reachable by anyone on your tailnet)
   Folder:    $DEST

Next:
  1. Fill in their profile:
       $DEST/config/resume.json, personal.json, candidate_notes.md
  2. Seed data (first run):
       cd $DEST && ./.venv/bin/python pipeline.py fetch && ./.venv/bin/python pipeline.py score
  3. Invite them to your Tailscale network, then send them the URL above.

Logs: $DEST/dashboard.log , $DEST/daily.log
DONE
