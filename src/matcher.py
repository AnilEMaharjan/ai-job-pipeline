"""Claude-powered job scoring with prompt caching."""

import json
import os
import re
import time
from typing import Any

import anthropic

MODEL = "claude-sonnet-4-6"

SYSTEM_PROMPT_TEMPLATE = """You are an expert technical recruiter evaluating fit between a candidate and a job posting.

Here is the candidate's resume (treat this as cached context — it does not change between evaluations):

<resume>
{resume_text}
</resume>

When given a job description, respond ONLY with a valid JSON object in this exact shape:
{{
  "score": <integer 0-100>,
  "missing": [<list of genuinely important skills or experience the candidate lacks>],
  "strengths": [<list of specific resume points that match the job well>],
  "summary": "<2-3 sentence explanation of the score>"
}}

Scoring guide:
- 85-100: Excellent match. Candidate's background maps directly to this role. Would likely get an interview.
- 70-84: Strong match. Core skills and experience align well. Minor gaps are learnable on the job.
- 55-69: Partial match. Meaningful overlap but real gaps in domain, seniority, or key tools.
- 0-54: Poor match. Fundamentally different role, domain, or required experience.

Important calibration rules:
- The candidate is an analytics engineer / data engineer who is ALSO a strong GTM-strategy and revenue-operations operator (ran a CPQ + ARR migration, overhauled outcomes-focused leadership reporting). Score relative to that hybrid persona, not a generic software engineer.
- Do NOT penalize for location. All jobs in this pipeline are remote-eligible; any state restrictions in the job description should be ignored.
- Do NOT penalize for minor tool gaps (e.g. AWS Glue, Spark, Presto). These are learnable; only flag them in "missing" if they are clearly central to the role.
- Do NOT penalize for being 1-2 years short of a stated years-of-experience requirement. Depth of experience matters more than raw years.
- DO heavily penalize (score below 40) if the role requires in-office or hybrid attendance — e.g. "X days per week in office", "hybrid", "onsite required", "must be located in [city]". The candidate requires fully remote.
- DO penalize for fundamental domain mismatches: e.g. a pure ML research role, a healthcare fraud investigator role, a financial planning analyst role, or a software infrastructure role with no data/analytics component.
- DO heavily penalize (score below 55) roles whose CORE responsibility is RevOps operations administration rather than data/analytics/strategy — specifically: running or overseeing a Deal Desk, owning quote-to-cash / revenue lifecycle DESIGN, CPQ administration, or sales-commission/territory operations as the primary function. The candidate did a CPQ migration as a project but does NOT want a deal-desk-operator or revenue-lifecycle-design role. A role that merely MENTIONS these among many duties is fine; only penalize when they are clearly central.
- A score of 70+ means: "this candidate would plausibly get a phone screen for this role."

Only output JSON — no preamble, no markdown fences."""


def _resume_to_text(resume_json: dict[str, Any]) -> str:
    """Convert resume JSON to a readable text representation."""
    lines = []
    lines.append(f"Name: {resume_json['name']}")
    lines.append(f"Email: {resume_json['email']}")
    lines.append(f"Location: {resume_json['location']}")
    lines.append(f"\nSummary:\n{resume_json['summary']}")

    lines.append("\nSkills:")
    for category, items in resume_json["skills"].items():
        lines.append(f"  {category.capitalize()}: {', '.join(items)}")

    lines.append("\nExperience:")
    for exp in resume_json["experience"]:
        lines.append(
            f"\n  {exp['title']} at {exp['company']} ({exp['start_date']} – {exp['end_date']})"
        )
        for bullet in exp["bullets"]:
            lines.append(f"    • {bullet}")

    lines.append("\nEducation:")
    for edu in resume_json["education"]:
        lines.append(
            f"  {edu['degree']}, {edu['institution']} ({edu['graduation_year']})"
        )

    lines.append("\nCertifications:")
    for cert in resume_json.get("certifications", []):
        lines.append(f"  • {cert}")

    lines.append("\nProjects:")
    for proj in resume_json.get("projects", []):
        lines.append(f"  {proj['name']}: {proj['description']}")
        lines.append(f"    Tech: {', '.join(proj['tech'])}")

    return "\n".join(lines)


def score_job(
    resume_json: dict[str, Any],
    job: dict[str, Any],
    client: anthropic.Anthropic | None = None,
    feedback: str = "",
) -> dict[str, Any]:
    """
    Score a single job against the resume.
    Uses prompt caching so the resume system prompt is cached across calls.

    Returns dict with keys: score, missing, strengths, summary
    """
    if client is None:
        client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    resume_text = _resume_to_text(resume_json)
    system_prompt = SYSTEM_PROMPT_TEMPLATE.format(resume_text=resume_text)

    job_description = job.get("description", "")[:8000]  # Trim very long JDs
    title = job.get("title", "Unknown Role")
    company = job.get("company", "Unknown Company")

    feedback_block = f"\n\n<candidate_rejection_feedback>\n{feedback}\n</candidate_rejection_feedback>" if feedback else ""
    user_content = f"Please evaluate this job posting:\n\nRole: {title}\nCompany: {company}\n\nJob Description:\n{job_description}{feedback_block}"

    def _call_and_parse() -> dict:
        message = client.messages.create(
            model=MODEL,
            max_tokens=1024,
            system=[
                {
                    "type": "text",
                    "text": system_prompt,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": user_content}],
        )
        raw = message.content[0].text.strip()
        # Strip markdown code fences
        raw = re.sub(r"^```[a-z]*\n?", "", raw).rstrip("` \n")
        # Try direct parse first
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass
        # Try extracting JSON object from surrounding text
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            return json.loads(match.group())
        raise ValueError(f"No parseable JSON in response: {raw[:200]}")

    # Retry on both parse failures AND transient API errors (Claude down,
    # overloaded, rate limited, network blip) with a short backoff.
    last_err = None
    result = None
    for attempt in range(3):
        try:
            result = _call_and_parse()
            break
        except (json.JSONDecodeError, ValueError) as e:
            last_err = e
            if attempt < 2:
                print(f"    Parse attempt {attempt + 1} failed, retrying...")
        except Exception as e:  # API errors: overloaded, rate limit, connection
            last_err = e
            if attempt < 2:
                print(f"    API call attempt {attempt + 1} failed ({type(e).__name__}), retrying...")
                time.sleep(2 * (attempt + 1))

    if result is None:
        # All attempts failed. Flag as failed so the caller leaves the job
        # UNSCORED (score stays NULL) and a later run retries it, rather than
        # burying it as a score-0 reject.
        print(f"    All 3 attempts failed: {last_err}")
        return {
            "score": 0,
            "missing": [],
            "strengths": [],
            "summary": "Scoring failed — will retry on next run.",
            "failed": True,
        }

    return {
        "score": int(result.get("score", 0)),
        "missing": result.get("missing", []),
        "strengths": result.get("strengths", []),
        "summary": result.get("summary", ""),
        "failed": False,
    }


def score_jobs_batch(
    resume_json: dict[str, Any],
    jobs: list[dict[str, Any]],
    threshold: int = 70,
) -> list[dict[str, Any]]:
    """
    Score a list of jobs. Returns all results (caller decides what to do with scores).
    The resume is cached in the system prompt via cache_control ephemeral.
    """
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    results = []

    # Learn from the candidate's own rejections (with reasons) to steer scoring.
    try:
        from src.database import get_rejection_feedback
        feedback = get_rejection_feedback()
        if feedback:
            print("  (applying feedback from your past rejections)")
    except Exception:
        feedback = ""

    for i, job in enumerate(jobs, 1):
        print(f"  Scoring [{i}/{len(jobs)}]: {job.get('company')} – {job.get('title')}")
        try:
            result = score_job(resume_json, job, client=client, feedback=feedback)
            result["job_id"] = job.get("id")
            results.append(result)
        except Exception as exc:
            print(f"    Error scoring job {job.get('id')}: {exc}")
            results.append(
                {
                    "job_id": job.get("id"),
                    "score": 0,
                    "missing": [],
                    "strengths": [],
                    "summary": "Scoring failed — will retry on next run.",
                    "failed": True,
                }
            )

    return results
