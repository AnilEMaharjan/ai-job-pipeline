# Assistant Setup Guide

> **If you are an AI assistant (Claude Code, etc.) reading this:** the user wants this
> job-application pipeline set up and personalized. They may be non-technical.
> Follow these steps, run the commands for them, and verify each one before moving on.

## What this project does

Scrapes 1,000+ company job boards for remote US jobs, scores each posting 0–100
against the user's resume using the Anthropic API, surfaces strong matches in a
local web dashboard, and generates tailored resume + cover letter PDFs.

## Setup steps

### 1. Environment

Run `./setup.sh` (or perform its steps manually: create `.venv`, `pip install -r
requirements.txt`, copy the three `.example` config files). If the user is on
Windows, do the equivalent manually — the script is bash-only.

Ask the user for their **Anthropic API key** and put it in `.env` as
`ANTHROPIC_API_KEY=...`. Never commit this file.

### 2. Build their resume.json (the important step)

`config/resume.json` drives everything: scoring accuracy, resume tailoring, cover
letters, and PDF filenames. Ask the user for their current resume (PDF, Word, or
LinkedIn profile text) and build `config/resume.json` from it, matching the schema
in `config/resume.example.json` exactly.

Guidelines while building it:
- Transcribe faithfully — **never invent experience, dates, titles, or metrics.**
- Confirm employment dates and titles with the user; mismatches with their
  LinkedIn will hurt them with recruiters.
- The `summary` field matters most: 3–4 sentences covering career arc, core
  skills, and genuine differentiators. Draft it, then ask the user to approve.
- Put every tool/skill they actually use in `skills` — the scorer treats missing
  tools as gaps.
- Recent roles get 4–7 bullets; older roles 2–3.

### 3. Personalize the search

- **Companies:** `config/companies.json` ships with ~1,100 tech companies. Ask the
  user about target industries and add/remove accordingly. To add a company, find
  its board slug and verify it returns jobs:
  - Greenhouse: `https://boards-api.greenhouse.io/v1/boards/{slug}/jobs`
  - Ashby: `https://api.ashbyhq.com/posting-api/job-board/{slug}`
  - Lever: `https://api.lever.co/v0/postings/{slug}?mode=json`
- **Title filters:** `TITLE_KEYWORDS` / `TITLE_EXCLUDES` in `pipeline.py` control
  which jobs reach paid AI scoring. Tune them to the user's target roles — the
  defaults are tuned for analytics/data/GTM roles.
- **Scoring rubric:** the prompt in `src/matcher.py` defines what a good fit means.
  Rewrite its rules for the user's profile (level, dealbreakers, location limits).
- **Threshold:** `SCORE_THRESHOLD` in `.env` (default 70).

### 4. Smoke test

```bash
source .venv/bin/activate
python pipeline.py fetch       # expect: thousands of jobs found, some 404s are normal
python pipeline.py score       # expect: pre-filter skips most; the rest get scored
python pipeline.py dashboard   # expect: dashboard at http://localhost:8765
```

If scoring errors with an auth message, the API key in `.env` is wrong.
If PDFs fail, `pdflatex` is missing — install TinyTeX and run
`tlmgr install roboto fontaxes needspace parskip`.

### 5. Show the user around the dashboard

- **Queued** = scored at/above threshold, worth reviewing
- **Generate** builds a tailored resume + cover letter PDF for that job.
  **Teach the user to spot-check before sending** (walk them through it on their
  first generated pair): (1) any factual claim about the company may be invented —
  verify or delete; (2) dates/titles on the resume must exactly match their
  LinkedIn; (3) the letter must not claim skills they don't have; (4) cut anything
  they couldn't defend in an interview. See README "Before you send anything." 
- **✓ Applied** tracks submissions; **✕** rejects (reversible via the
  "Rejected" filter)
- Optional: a LinkedIn data export + `python connections_match.py <export.zip>`
  adds 🤝 badges showing jobs where the user knows someone

### 6. Optional: daily automation

Offer to set up a cron job that runs `python pipeline.py run` each morning so new
jobs are fetched and scored before the user wakes up.
