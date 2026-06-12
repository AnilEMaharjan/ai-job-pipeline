"""Claude-powered resume tailoring and cover letter generation."""

import copy
import json
import os
import re
from typing import Any

import anthropic

MODEL = "claude-sonnet-4-6"


def _get_client() -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])


def _strip_dashes(text: str) -> str:
    """Remove em/en dashes (house style: commas/periods instead)."""
    if not isinstance(text, str):
        return text
    text = text.replace(" — ", ", ").replace(" – ", ", ").replace("—", ", ").replace("–", "-")
    text = re.sub(r",\s*,", ",", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()


def _walk_strip(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _walk_strip(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_walk_strip(v) for v in obj]
    return _strip_dashes(obj)


def tailor_resume(
    resume_json: dict[str, Any],
    job_description: str,
    strengths: list[str],
    client: anthropic.Anthropic | None = None,
) -> dict[str, Any]:
    """
    Rewrite the summary + experience bullets to emphasize what's relevant to this job.
    Returns a modified deep copy of resume_json. Does NOT invent new experience.
    """
    if client is None:
        client = _get_client()

    resume_copy = copy.deepcopy(resume_json)
    strengths_text = "\n".join(f"- {s}" for s in strengths)

    system = (
        "You are a senior technical resume writer tailoring a resume for one specific role. "
        "RULES:\n"
        "1. Do NOT invent experiences, companies, titles, dates, or metrics not in the original.\n"
        "2. You MAY reorder and rephrase bullets and lead with the most role-relevant ones.\n"
        "3. Rewrite the professional summary so its FIRST sentence speaks to this exact role's focus, "
        "weaving in the candidate's genuine differentiators (e.g., CPA/financial rigor) where relevant.\n"
        "4. Keep bullets concise, action-verb-first, quantified where the original had numbers.\n"
        "5. No em dashes. Use commas or periods.\n"
        "6. Respond ONLY with valid JSON: {\"summary\": \"...\", \"experience\": [...]}. "
        "Preserve the exact same number of experience entries and their company/title/dates."
    )

    prompt = f"""Job description:
<job_description>
{job_description[:6000]}
</job_description>

The candidate's strongest selling points for THIS role:
{strengths_text}

Current professional summary:
<summary>
{resume_copy.get('summary', '')}
</summary>

Current experience (JSON):
<experience>
{json.dumps(resume_copy['experience'], indent=2)}
</experience>

Return ONLY JSON: {{"summary": "<tailored summary, 3-4 sentences, leads with this role's focus>", "experience": [<same entries, bullets reordered/rephrased toward this role>]}}. No other text."""

    message = client.messages.create(
        model=MODEL,
        max_tokens=2600,
        system=system,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = message.content[0].text.strip()
    raw = re.sub(r"^```[a-z]*\n?", "", raw).rstrip("` \n")

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        data = json.loads(match.group()) if match else {}

    if isinstance(data, dict):
        if isinstance(data.get("summary"), str) and data["summary"].strip():
            resume_copy["summary"] = data["summary"].strip()
        if isinstance(data.get("experience"), list) and data["experience"]:
            resume_copy["experience"] = data["experience"]

    return _walk_strip(resume_copy)


# Generic closers we never want to end on.
_BANNED_CLOSERS = re.compile(
    r"(i am ready to move quickly|ready to move quickly|hit the ground running|"
    r"i would welcome the chance to talk\.?$|thank you for your (time|consideration))",
    re.I,
)


def generate_cover_letter(
    resume_json: dict[str, Any],
    job_description: str,
    company_name: str,
    role_title: str,
    strengths: list[str] | None = None,
    gaps: list[str] | None = None,
    client: anthropic.Anthropic | None = None,
) -> str:
    """
    Generate a tailored, four-paragraph cover letter body.
    Leads with a specific hook, preempts the top gap, ends on a concrete close.
    """
    if client is None:
        client = _get_client()

    experience_summary = "; ".join(
        f"{e['title']} at {e['company']}" for e in resume_json["experience"]
    )
    skills_summary = ", ".join(
        item for cat in resume_json["skills"].values() for item in cat
    )
    strengths_text = "\n".join(f"- {s}" for s in (strengths or [])) or "(none provided)"
    gaps_text = "\n".join(f"- {g}" for g in (gaps or [])) or "(none provided)"

    applicant_name = resume_json.get("name", "the candidate")
    applicant_summary = (resume_json.get("summary") or "").strip()

    system = (
        f"You write cover letters in the first person for {applicant_name}. "
        f"Candidate profile: {applicant_summary} "
        "You produce specific, confident, non-generic letters.\n"
        "CRITICAL RULES:\n"
        "1. Body paragraphs only: no header, contact info, salutation, or sign-off.\n"
        "2. First person always (I, my). Never third person.\n"
        "3. Never state a number of years of experience.\n"
        "4. Never open by describing the company back to itself.\n"
        "5. NO em dashes. Use commas, periods, or semicolons.\n"
        "6. Exactly FOUR short paragraphs. Under 230 words total.\n"
        "7. Do NOT end with generic filler like 'I am ready to move quickly', 'hit the ground "
        "running', or a bare 'I would welcome the chance to talk'. The closing line must be "
        "specific to this role and forward-looking.\n"
        "8. Plain text only, no markdown."
    )

    prompt = f"""Write the cover letter body for {role_title} at {company_name}.

Candidate background:
- Experience: {experience_summary}
- Skills: {skills_summary}

The candidate's strongest, most specific selling points for THIS role (use the best 2-3, with concrete detail):
{strengths_text}

Known gaps for this role (address the single most important one gracefully in paragraph 3, as a bridge, never apologize or dwell):
{gaps_text}

Job description:
{job_description[:4000]}

Structure (four paragraphs):
1. Open with the single strongest, most specific hook tying my current work to THIS role. When it fits, frame the role as work I already do. First sentence is about me, not the company.
2. One or two concrete achievements (drawn from the selling points above) that map directly to this role's core responsibilities, with specifics.
3. Connect my stack/skills to the role in its own terms, and bridge the top gap here if there is one.
4. A specific, forward-looking close tied to this role's actual problem or mission. Not generic filler."""

    message = client.messages.create(
        model=MODEL,
        max_tokens=700,
        system=system,
        messages=[{"role": "user", "content": prompt}],
    )
    text = _strip_dashes(message.content[0].text.strip())

    # Safety net: if the model still ended on a banned closer, drop that final sentence.
    sentences = re.split(r"(?<=[.!?])\s+", text)
    if sentences and _BANNED_CLOSERS.search(sentences[-1]):
        sentences = sentences[:-1]
        text = " ".join(sentences).strip()

    return text
