# AI-Powered Job Application Pipeline

An end-to-end job search automation system: scrapes 1,000+ company job boards, scores every posting against your resume with Claude, generates tailored resume + cover letter PDFs, maps your LinkedIn network to target companies, and tracks everything in a local web dashboard.

## How it works

```
fetch  →  score  →  review (dashboard)  →  generate  →  apply
```

1. **Fetch** — pulls remote US jobs from Greenhouse, Lever, Ashby, Recruitee, and Workable boards for every company in `config/companies.json` (async, ~1,100 companies in a few minutes). Extracts salary where available, detects hybrid/in-office postings, and archives stale listings.
2. **Score** — a title/location pre-filter screens obvious mismatches, then Claude scores each remaining job 0–100 against your resume (prompt caching keeps cost low). Jobs at or above `SCORE_THRESHOLD` land in your queue with strengths, gaps, and a fit summary.
3. **Review** — a FastAPI dashboard (`localhost:8765`) with multi-select status filters, score/salary ranges, full-text search, a personal reject flag, and 🤝 badges showing jobs at companies where you have LinkedIn connections.
4. **Generate** — one click produces a role-tailored resume and a four-paragraph cover letter (leads with your strongest hook, bridges your top gap, bans em dashes and generic closers), rendered to PDF via LaTeX.
5. **Referral map** — `connections_match.py` cross-references your LinkedIn data export against your target companies, ranks contacts by seniority and role relevance, and flags ex-colleagues.

## Setup

### 1. Install dependencies

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

PDF generation requires `pdflatex`. The cheapest way to get it is [TinyTeX](https://yihui.org/tinytex/), plus a few packages:

```bash
tlmgr install roboto fontaxes needspace parskip
```

### 2. Configure your environment

```bash
cp .env.example .env                                   # add your Anthropic API key
cp config/resume.example.json config/resume.json       # fill in your resume
cp config/personal.example.json config/personal.json   # optional: former employers for the referral matcher
```

Your resume JSON drives everything: scoring, tailoring, cover letters, and PDF filenames. Be accurate — the generator is instructed never to invent experience, so what you put here is what gets used.

### 3. Run it

```bash
python pipeline.py fetch        # pull jobs from all company boards
python pipeline.py score        # AI-score the new ones
python pipeline.py dashboard    # review at http://localhost:8765
python pipeline.py run          # fetch + score in one shot (good for cron)
```

### 4. (Optional) LinkedIn referral map

Export your connections from LinkedIn (Settings → Data Privacy → Get a copy of your data → Connections), then:

```bash
python connections_match.py ~/Downloads/Basic_LinkedInDataExport.zip
```

This writes `referral_map.csv` and the dashboard picks it up automatically — every job at a company where you know someone gets a 🤝 badge and a connections panel.

## Customizing

- **Companies** — `config/companies.json` is a flat list of `{name, platform, slug}`. Verify a slug works by hitting the board API directly (e.g. `https://boards-api.greenhouse.io/v1/boards/{slug}/jobs`). Set `"active": false` to pause a company without deleting it.
- **Title filters** — `TITLE_KEYWORDS` / `TITLE_EXCLUDES` in `pipeline.py` control what reaches (paid) AI scoring.
- **Scoring rubric** — the prompt in `src/matcher.py` defines what "fit" means; edit it to match your own profile and dealbreakers.
- **Threshold** — `SCORE_THRESHOLD` in `.env` (default 70) sets the queue bar.

## Privacy

All personal data stays local and gitignored: `.env` (API key), `config/resume.json`, `config/personal.json`, `data/` (job database), `applications/` (generated materials), and `referral_map.csv`. The repo ships only code, the company list, and `.example` templates.
