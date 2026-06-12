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

## Quick start (no terminal experience needed)

1. **Download:** click the green **Code** button above → **Download ZIP** → unzip it.
   (Or `git clone https://github.com/AnilEMaharjan/ai-job-pipeline.git` if you know git.)
2. **Set up:** open the Terminal app, type `cd ` (with a space), drag the unzipped folder onto the
   Terminal window, press Enter, then run:
   ```bash
   bash setup.sh
   ```
   It installs everything and asks for your Anthropic API key
   (get one at https://console.anthropic.com → API Keys).
3. **Add your resume:** the easiest way is [Claude Code](https://claude.com/claude-code) — open this
   folder in it and say *"set this up for me using SETUP.md"*, then hand it your resume PDF and say
   *"build my config/resume.json from this."* It will also tailor the company list and scoring to you.
4. **Run it:**
   ```bash
   bash run.sh update     # fetch jobs + score them + open the dashboard
   ```
   After that, `bash run.sh` opens the dashboard any time, and `bash run.sh update` pulls fresh jobs.

## Manual setup

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

Knowing someone at a company is the single best way to get your application seen, so the
pipeline can map your LinkedIn network onto your target companies.

**Getting your data out of LinkedIn:**
1. On LinkedIn: click your photo → **Settings & Privacy** → **Data privacy** →
   **Get a copy of your data**
2. Choose the option that includes **Connections** (the smaller archive arrives in ~10
   minutes; the "larger data archive" can take up to a day — either works)
3. LinkedIn emails you a download link — save the `.zip` to your Downloads folder
4. Run the matcher (it finds the file in Downloads automatically, or pass the path):

```bash
python connections_match.py
```

**What you get:** a ranked `referral_map.csv` (company → person, title, LinkedIn URL,
referral strength), and the dashboard automatically shows a 🤝 badge on every job where
you know someone, with the names in the job's Details panel. To flag former coworkers as
your warmest intros, list past employers in `config/personal.json` first.

**A note on what it can and can't see:** LinkedIn's export only includes each connection's
*current* employer, so the matcher can't find "used to work at X, now at your target" paths.
And company names in the export are messy ("Acme Inc" vs "Acme") — the matcher fuzzy-matches,
but skim the CSV for obvious misses.

## Before you send anything: spot-check the AI's output

The generator is instructed never to invent experience, but **you are responsible for what
you submit.** Real failure modes we've hit, in order of how much they can hurt you:

1. **Invented facts about the company.** AI text can confidently state specifics that are
   wrong (in testing, one letter claimed a company operated in "195 countries" — the real
   number was ~120). Check any number or claim about the company against their website,
   or delete it.
2. **Resume facts drifting from your LinkedIn.** Recruiters cross-reference. Verify the
   tailored resume kept your **exact dates and titles**, and that no overlap or gap appeared
   that doesn't match your profile. Tailoring should only reorder and rephrase bullets —
   if a bullet claims a tool, metric, or scope you don't recognize, fix `config/resume.json`
   and regenerate.
3. **Overclaimed skills.** If the job wants a tool you've never used, the letter should
   bridge honestly ("adjacent experience with X") — not claim it. Read paragraph 3 closely;
   that's where the generator handles gaps.
4. **Tone tells.** Scan for generic AI filler ("I'm ready to hit the ground running"),
   em dashes, and form-letter closers. The generator bans these, but belt and suspenders.

A 90-second read of both PDFs before each submission catches all of this. If the cover
letter mentions anything you couldn't defend in an interview, cut it.

## Customizing

- **Companies** — `config/companies.json` is a flat list of `{name, platform, slug}`. Verify a slug works by hitting the board API directly (e.g. `https://boards-api.greenhouse.io/v1/boards/{slug}/jobs`). Set `"active": false` to pause a company without deleting it.
- **Title filters** — `TITLE_KEYWORDS` / `TITLE_EXCLUDES` in `pipeline.py` control what reaches (paid) AI scoring.
- **Scoring rubric** — the prompt in `src/matcher.py` defines what "fit" means; edit it to match your own profile and dealbreakers.
- **Threshold** — `SCORE_THRESHOLD` in `.env` (default 70) sets the queue bar.

## Privacy

All personal data stays local and gitignored: `.env` (API key), `config/resume.json`, `config/personal.json`, `data/` (job database), `applications/` (generated materials), and `referral_map.csv`. The repo ships only code, the company list, and `.example` templates.
