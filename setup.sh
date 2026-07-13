#!/usr/bin/env bash
# One-command setup for the job pipeline.
# Usage: ./setup.sh
set -e

cd "$(dirname "$0")"
echo "── Job Pipeline Setup ──────────────────────────────────"

# 1. Python
if ! command -v python3 >/dev/null 2>&1; then
  echo "✗ python3 not found. Install Python 3.10+ from https://www.python.org/downloads/ and re-run."
  exit 1
fi
echo "✓ $(python3 --version)"

# 2. Virtualenv + dependencies
if [ ! -d .venv ]; then
  echo "Creating virtual environment..."
  python3 -m venv .venv
fi
source .venv/bin/activate
echo "Installing dependencies (this can take a minute)..."
pip install -q --upgrade pip
pip install -q -r requirements.txt
echo "✓ dependencies installed"

# 3. Config files from templates
[ -f .env ] || cp .env.example .env
[ -f config/resume.json ] || cp config/resume.example.json config/resume.json
[ -f config/personal.json ] || cp config/personal.example.json config/personal.json
[ -f config/candidate_notes.md ] || cp config/candidate_notes.example.md config/candidate_notes.md
echo "✓ config files in place"
echo "  (title_filters.json / scoring_rules.md are optional -- without them, every job"
echo "   title is filtered out until you set them up via the dashboard's Profile page,"
echo "   or copy config/title_filters.example.json and config/scoring_rules.example.md)"

# 4. API key
if grep -q "sk-ant-\.\.\." .env; then
  echo ""
  read -r -p "Paste your Anthropic API key (or press Enter to add it to .env later): " KEY || KEY=""
  if [ -n "$KEY" ]; then
    # portable in-place edit (macOS + Linux)
    python3 - "$KEY" << 'PYEOF'
import sys, pathlib
p = pathlib.Path(".env")
p.write_text(p.read_text().replace("sk-ant-...", sys.argv[1]))
PYEOF
    echo "✓ API key saved to .env"
  else
    echo "… remember to edit .env and set ANTHROPIC_API_KEY before scoring."
  fi
fi

# 5. LaTeX (for PDF generation)
if command -v pdflatex >/dev/null 2>&1 || [ -x "$HOME/Library/TinyTeX/bin/universal-darwin/pdflatex" ]; then
  echo "✓ pdflatex found"
else
  echo ""
  read -r -p "pdflatex not found (needed for PDFs). Install TinyTeX now? [y/N] " yn || yn="n"
  if [ "$yn" = "y" ] || [ "$yn" = "Y" ]; then
    curl -sL "https://yihui.org/tinytex/install-bin-unix.sh" | sh
    TLMGR="$HOME/Library/TinyTeX/bin/universal-darwin/tlmgr"
    [ -x "$TLMGR" ] || TLMGR="$HOME/.TinyTeX/bin/x86_64-linux/tlmgr"
    "$TLMGR" install roboto fontaxes needspace parskip || true
    echo "✓ TinyTeX installed"
  else
    echo "… skipping. Fetch/score/dashboard work without it; PDF generation won't."
  fi
fi

echo ""
echo "── Done! Next steps ────────────────────────────────────"
echo "1. Put YOUR resume into config/resume.json"
echo "   (easiest: open this folder in Claude Code, hand it your resume PDF,"
echo "    and say: 'build my config/resume.json from this resume')"
echo "2. source .venv/bin/activate"
echo "3. python pipeline.py fetch      # pull jobs (~5 min first run)"
echo "4. python pipeline.py score      # AI-score them"
echo "5. python pipeline.py dashboard  # review at http://localhost:8766"
