#!/usr/bin/env python3
"""Convert a friend's resume (PDF or text) into a valid config/resume.json using
Claude, so you don't hand-author the JSON. Run inside a provisioned user's clone
(it reads that instance's .env for the key), or pass --out to target any path.

Usage:
  cd ~/jobpipe/users/alice
  ./.venv/bin/python scripts/import_resume.py ~/Downloads/alice_resume.pdf
  # or specify output explicitly:
  ./.venv/bin/python scripts/import_resume.py resume.txt --out config/resume.json
"""
import base64
import json
import os
import sys
from pathlib import Path

import anthropic
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env", override=False)  # optional; Infisical/env may already provide the key

REQUIRED_KEYS = {"name", "email", "location", "summary", "skills", "experience", "education"}


def build_message(resume_path: Path, example: str):
    """Return the content blocks: the example schema + the resume (PDF or text)."""
    instructions = (
        "Convert the attached resume into JSON that matches EXACTLY the structure, "
        "keys, and types of this example (same schema, same field names):\n\n"
        f"{example}\n\n"
        "Rules: use ONLY information present in the resume; never invent employers, "
        "titles, dates, or metrics. Keep the same top-level keys as the example even "
        "if some arrays end up shorter. Respond with ONLY the JSON, no prose, no code fences."
    )
    if resume_path.suffix.lower() == ".pdf":
        data = base64.standard_b64encode(resume_path.read_bytes()).decode()
        return [
            {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": data}},
            {"type": "text", "text": instructions},
        ]
    text = resume_path.read_text(encoding="utf-8", errors="ignore")
    return [{"type": "text", "text": instructions + "\n\nRESUME:\n" + text}]


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

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("No ANTHROPIC_API_KEY (checked .env and environment).")
        return 1
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    print(f"Parsing {resume_path.name} with Claude...")
    msg = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4000,
        messages=[{"role": "user", "content": build_message(resume_path, example)}],
    )
    raw = msg.content[0].text.strip()
    raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"Claude did not return valid JSON ({e}). Raw start:\n{raw[:300]}")
        return 1
    missing = REQUIRED_KEYS - set(data)
    if missing:
        print(f"WARNING: parsed JSON is missing expected keys: {sorted(missing)} — review before using.")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, indent=2) + "\n")
    print(f"✅ Wrote {out}. REVIEW IT — verify titles/dates/metrics match the real resume before scoring.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
