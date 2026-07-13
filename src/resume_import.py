"""Convert a resume (PDF bytes or plain text) into the app's resume.json schema
using Claude. Shared by scripts/import_resume.py (CLI) and the dashboard's
self-service profile editor, so there is exactly one parsing implementation."""
from __future__ import annotations

import base64
import json
from typing import Any

import anthropic

REQUIRED_KEYS = {"name", "email", "location", "summary", "skills", "experience", "education"}


class ResumeParseError(Exception):
    pass


def _build_content(example_schema: str, *, pdf_bytes: bytes | None, text: str | None) -> list[dict]:
    instructions = (
        "Convert the attached resume into JSON that matches EXACTLY the structure, "
        "keys, and types of this example (same schema, same field names):\n\n"
        f"{example_schema}\n\n"
        "Rules: use ONLY information present in the resume; never invent employers, "
        "titles, dates, or metrics. Keep the same top-level keys as the example even "
        "if some arrays end up shorter. Respond with ONLY the JSON, no prose, no code fences."
    )
    if pdf_bytes is not None:
        data = base64.standard_b64encode(pdf_bytes).decode()
        return [
            {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": data}},
            {"type": "text", "text": instructions},
        ]
    return [{"type": "text", "text": instructions + "\n\nRESUME:\n" + (text or "")}]


def parse_resume(
    example_schema: str,
    *,
    pdf_bytes: bytes | None = None,
    text: str | None = None,
    api_key: str,
) -> tuple[dict[str, Any], list[str]]:
    """Parse a resume (give either pdf_bytes or text) into the resume.json schema.
    Returns (parsed_dict, missing_required_keys). Raises ResumeParseError on failure."""
    if not pdf_bytes and not text:
        raise ResumeParseError("No resume content provided.")
    client = anthropic.Anthropic(api_key=api_key)
    msg = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4000,
        messages=[{"role": "user", "content": _build_content(example_schema, pdf_bytes=pdf_bytes, text=text)}],
    )
    raw = msg.content[0].text.strip()
    raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ResumeParseError(f"Claude did not return valid JSON ({e}). Raw start: {raw[:300]}") from e
    missing = sorted(REQUIRED_KEYS - set(data))
    return data, missing
