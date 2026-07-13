#!/usr/bin/env python3
"""Convert a friend's resume (PDF or text) into a valid config/resume.json using
Claude, so you don't hand-author the JSON. Run inside a provisioned user's clone
(it reads that instance's .env for the key), or pass --out to target any path.

Usage:
  cd ~/jobpipe/users/alice
  ./.venv/bin/python scripts/import_resume.py ~/Downloads/alice_resume.pdf
  # or specify output explicitly:
  ./.venv/bin/python scripts/import_resume.py resume.txt --out config/resume.json

(The dashboard's Profile page offers the same conversion through the browser —
this script is for host-side / scripted setup.)
"""
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env", override=False)  # optional; Infisical/env may already provide the key

from src.resume_import import ResumeParseError, parse_resume  # noqa: E402


def main() -> int:
    args = [a for a in sys.argv[1:] if a != "--out"]
    out = None
    if "--out" in sys.argv:
        i = sys.argv.index("--out")
        out = Path(sys.argv[i + 1])
        args = [a for a in args if a != str(out)]
    if not args:
        print(__doc__)
        return 2
    resume_path = Path(args[0]).expanduser()
    if not resume_path.exists():
        print(f"No such file: {resume_path}")
        return 1
    out = out or (ROOT / "config" / "resume.json")
    example = (ROOT / "config" / "resume.example.json").read_text()

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("No ANTHROPIC_API_KEY (checked .env and environment).")
        return 1

    print(f"Parsing {resume_path.name} with Claude...")
    is_pdf = resume_path.suffix.lower() == ".pdf"
    try:
        data, missing = parse_resume(
            example,
            pdf_bytes=resume_path.read_bytes() if is_pdf else None,
            text=None if is_pdf else resume_path.read_text(encoding="utf-8", errors="ignore"),
            api_key=api_key,
        )
    except ResumeParseError as e:
        print(str(e))
        return 1

    if missing:
        print(f"WARNING: parsed JSON is missing expected keys: {missing} — review before using.")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, indent=2) + "\n")
    print(f"✅ Wrote {out}. REVIEW IT — verify titles/dates/metrics match the real resume before scoring.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
