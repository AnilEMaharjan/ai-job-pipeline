# Contributing — First-Day Setup

A start-to-finish checklist to get productive on the job-pipeline. For deeper
context, see `README.md` (architecture) and `SETUP.md` (onboarding a new user's
profile). AI-assistant conventions live in `CLAUDE.md`.

## 0. Prerequisites
- **Python 3.11+** (developed on 3.11.9)
- **git**, and access to the repo (`AnilEMaharjan/ai-job-pipeline`)
- **Infisical CLI** — secrets live in Infisical, not a `.env`. Install: `brew install infisical/get-cli/infisical`
- **TinyTeX** (only if you'll generate resume/cover-letter PDFs): install TinyTeX, then
  `tlmgr install roboto fontaxes needspace parskip`

## 1. Clone + environment
```bash
git clone https://github.com/AnilEMaharjan/ai-job-pipeline.git
cd ai-job-pipeline
./setup.sh          # creates .venv, pip installs, copies the .example config files
source .venv/bin/activate
```
`setup.sh` copies `config/resume.example.json` → `resume.json` and
`config/personal.example.json` → `personal.json`. Also copy the notes template:
```bash
cp config/candidate_notes.example.md config/candidate_notes.md
```

## 2. Fill in your own config (all gitignored — never committed)
- `config/resume.json` — drives scoring, tailoring, and PDF output. The most important file.
- `config/personal.json` — name/contact/links.
- `config/candidate_notes.md` — living memory the generator reads each run.
> The repo ships code only. `config/*.json`, `config/candidate_notes.md`, `data/`,
> `applications/`, and `referral_map.csv` are gitignored, so you start with your own.

## 3. Secrets (Infisical — this is the #1 gotcha)
There is **no `.env`**. Every command runs through Infisical, which injects
`ANTHROPIC_API_KEY` (and others) into the environment:
```bash
infisical login                                   # one-time, needs a real terminal (~10-day token)
infisical secrets --path=/job-pipeline            # verify you can see ANTHROPIC_API_KEY
```
Then prefix every run:
```bash
infisical run --path=/job-pipeline -- python pipeline.py <command>
```
**FOOTGUN:** the `--path=/job-pipeline` is required. Without it Infisical injects
the wrong (root) secrets. Bare `python pipeline.py …` starts but fails at scoring
(no key). If you don't have Infisical access, set `ANTHROPIC_API_KEY` yourself.

## 4. Smoke test (confirms your setup end-to-end)
```bash
infisical run --path=/job-pipeline -- python pipeline.py fetch      # scrapes boards, saves jobs (some 404s are normal)
infisical run --path=/job-pipeline -- python pipeline.py score      # Claude-scores in-lane jobs; queues >=70
infisical run --path=/job-pipeline -- python pipeline.py dashboard  # http://localhost:8766
```
If scoring errors with an auth message → key missing/wrong at Infisical `/job-pipeline`.
If PDFs fail → TinyTeX isn't installed.

## 5. The CLI commands
| Command | What it does |
|---|---|
| `fetch` | Scrape all company boards, save new jobs, archive closed ones, refresh company lists |
| `score` | Claude-score unscored in-lane jobs (threshold 70 → queued); applies your rejection feedback |
| `generate` | Tailor a resume + cover letter and build PDFs for a specific job |
| `dashboard` | FastAPI review UI on port 8766 |
| `run` | The daily pipeline (fetch + score) |
| `review` | Review helper (see `pipeline.py`) |

## 6. Before you push
A pre-push hook runs **ruff → gitleaks → advisory review**. Keep it green:
```bash
ruff check .        # lint
```
Branch off `main`, keep commits scoped, and never commit anything under the
gitignored personal-data paths. Secrets stay in Infisical.

## Where things live
- `pipeline.py` — CLI entrypoint (Click), title pre-filters, orchestration
- `src/scraper.py` — 7 ATS scrapers (Greenhouse, Lever, Ashby, Recruitee, Workable, Rippling, Breezy)
- `src/matcher.py` — Claude scoring + rejection-feedback injection
- `src/generator.py` / `src/pdf_writer.py` — resume/cover-letter tailoring + LaTeX PDFs
- `src/database.py` — SQLite schema, upserts, archiving/closed-detection
- `dashboard/app.py` + `dashboard/templates/index.html` — review UI
- `config/companies.json` — the company watch list
