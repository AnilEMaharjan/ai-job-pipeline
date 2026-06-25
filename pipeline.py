#!/usr/bin/env python3
"""Main orchestration CLI for the AI-powered job application pipeline."""

import asyncio
import json
import os
import re
import sys
from pathlib import Path

import click
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel

# Load .env from project root before importing modules
load_dotenv(Path(__file__).parent / ".env", override=True)

# Add TinyTeX to PATH for pdflatex
_tinytex = Path.home() / "Library/TinyTeX/bin/universal-darwin"
if _tinytex.exists():
    os.environ["PATH"] = str(_tinytex) + os.pathsep + os.environ.get("PATH", "")

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

from src import (  # noqa: E402  (import after sys.path/.env setup)
    database,
    generator,
    matcher,
    pdf_writer,
    scraper,
)

console = Console()

CONFIG_DIR = Path(__file__).parent / "config"
APPLICATIONS_DIR = Path(__file__).parent / "applications"

SCORE_THRESHOLD = int(os.environ.get("SCORE_THRESHOLD", "70"))


TITLE_KEYWORDS = {
    "analytics", "analytical", "analyst", "business intelligence",
    "revenue operations", "revenue strategy", "revops", "rev ops",
    "marketing operations", "marketing analytics",
    "insights", "reporting", "gtm",
    "warehouse", "etl", "elt", "dbt", "snowflake", "bigquery", "orchestrat",
    "metrics", "attribution", "instrumentation",
    "finance manager", "finance director", "finance lead",
    # Broadened: finance/FP&A roles (CPA-relevant) and analytics-adjacent titles
    "strategic finance", "financial planning", "fp&a", "financial analyst",
    "business operations", "biz ops", "bizops", "growth analyst", "data science",
    # "data" and "scientist" checked separately below to avoid substring false positives
}

TITLE_EXCLUDES = {
    "frontend", "front-end", "front end", "mobile", "ios", "android",
    "backend", "back-end", "back end",
    "full stack engineer", "full stack developer", "full stack software",
    "fullstack engineer", "fullstack developer", "full-stack engineer", "full-stack developer",
    "security engineer", "infrastructure engineer", "devops", "sre",
    "recruiter", "recruiting", "talent acquisition", "legal", "counsel",
    "designer", "design", "brand", "content writer", "copywriter",
    "account executive", "account manager", "sales development",
    "intern", "internship",
    "program manager",
    "research scientist",
    "compliance", "regulatory",
    "fraud",
    "underwr",
    "credit risk",
    "compensation",
    "supportability",
    "enforcement",
    "bilingual",
    "emea",
    "decision scientist",
    "sales enablement", "revenue enablement",  # narrowed: don't exclude finance/data "enablement" roles
    "staff scientist",
    "site reliability",
    "temporary", "(temp)", "contractor", "contract role", "freelance",
    "fixed term", "fixed-term", "hourly",
    "analyst i,", "analyst ii,", "analyst 1", "analyst 2",
    " associate,", " associate -",
    "product marketing",
    "software architect",
    "machine learning engineer",
    "database reliability",
    "qa engineer",
    "billing ar",
    "data center",
    "product manager",
    "people analytics",
}

INTERNATIONAL_INDICATORS = {
    "canada", "uk", "united kingdom", "germany", "france", "australia",
    "india", "europe", "emea", "apac", "singapore", "ireland", "netherlands",
    "brazil", "mexico", "japan", "poland", "spain", "italy", "sweden",
}


HYBRID_INDICATORS = {
    "days per week in", "days a week in", "days/week in",
    "days in office", "days in the office", "in-office",
    "onsite", "on-site", "on site",
    "hybrid work", "hybrid role", "hybrid position",
    "must be located in", "must reside in",
    "required to be in",
}


def is_remote_description(description: str) -> bool:
    """Return False if description contains hybrid/in-office indicators."""
    d = description.lower()
    return not any(indicator in d for indicator in HYBRID_INDICATORS)


def is_relevant_title(title: str) -> bool:
    import re
    t = title.lower()
    if any(ex in t for ex in TITLE_EXCLUDES):
        return False
    if any(kw in t for kw in TITLE_KEYWORDS):
        return True
    # Whole-word check for short/ambiguous keywords
    if re.search(r'\bdata\b', t) or re.search(r'\bscientist\b', t):
        return True
    return False


def is_us_location(location: str) -> bool:
    if not location:
        return True  # no location = assume US remote
    loc = location.lower()
    if any(intl in loc for intl in INTERNATIONAL_INDICATORS):
        return False
    return True


def load_resume() -> dict:
    resume_path = CONFIG_DIR / "resume.json"
    with open(resume_path) as f:
        return json.load(f)


def load_companies() -> list[dict]:
    companies_path = CONFIG_DIR / "companies.json"
    with open(companies_path) as f:
        return json.load(f)


def regenerate_company_lists() -> None:
    """Rewrite the shareable company-list exports (names + careers URLs) from
    companies.json so they never drift. Called after each fetch."""
    import urllib.parse
    root = Path(__file__).parent
    companies = load_companies()

    def board_url(c: dict) -> str:
        s = urllib.parse.quote(c["slug"])
        return {
            "greenhouse": f"https://job-boards.greenhouse.io/{s}",
            "lever":      f"https://jobs.lever.co/{s}",
            "ashby":      f"https://jobs.ashbyhq.com/{s}",
            "recruitee":  f"https://{s}.recruitee.com",
            "workable":   f"https://apply.workable.com/{s}",
            "rippling":   f"https://ats.rippling.com/{s}/jobs",
        }.get(c["platform"], "")

    rows = sorted(companies, key=lambda c: c["name"].lower())
    (root / "companies_list.txt").write_text(
        "\n".join(sorted({c["name"] for c in companies}, key=str.lower))
    )
    md = [f"# Job Pipeline — Tracked Companies ({len(rows)})", ""]
    md.append("Careers-board URLs are approximate (built from platform + slug); "
              "most resolve, a few may 404 if a company uses a custom domain.")
    md.append("")
    md.append("| Company | Careers board |")
    md.append("|---|---|")
    md += [f"| {c['name']} | {board_url(c)} |" for c in rows]
    (root / "companies_list.md").write_text("\n".join(md) + "\n")


def slugify(text: str) -> str:
    """Convert text to a filesystem-safe slug."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_-]+", "-", text)
    return text[:60]


# ── CLI group ────────────────────────────────────────────────────────────────

@click.group()
def cli():
    """AI-powered job application pipeline."""
    pass


# ── fetch ─────────────────────────────────────────────────────────────────────

@cli.command()
def fetch():
    """Scrape all companies and save new jobs to the database."""
    console.print(Panel("[bold blue]Fetching jobs from all company boards...[/bold blue]"))

    database.init_db()
    companies = load_companies()

    console.print(f"Fetching from [cyan]{len(companies)}[/cyan] companies...")

    jobs = asyncio.run(scraper.fetch_all_companies(companies))

    console.print(f"\nFound [green]{len(jobs)}[/green] total jobs. Saving new ones...")

    new_count = 0
    dup_count = 0
    for job in jobs:
        job_id = database.save_job(
            company=job["company"],
            title=job["title"],
            url=job["url"],
            platform=job["platform"],
            description=job.get("description", ""),
            location=job.get("location", ""),
            salary_min=job.get("salary_min"),
            salary_max=job.get("salary_max"),
            salary_raw=job.get("salary_raw"),
            posted_at=job.get("posted_at"),
        )
        if job_id:
            new_count += 1
        else:
            dup_count += 1

    stale = database.archive_stale_jobs()
    closed_q = database.archive_closed_queued_jobs()
    regenerate_company_lists()  # keep the shareable lists in sync with companies.json
    console.print(
        f"\n[bold green]Done![/bold green] "
        f"Saved [green]{new_count}[/green] new jobs, "
        f"skipped [yellow]{dup_count}[/yellow] duplicates"
        + (f", archived [dim]{stale}[/dim] stale listings" if stale else "")
        + (f", removed [dim]{closed_q}[/dim] closed queued roles" if closed_q else "") + "."
    )


# ── score ─────────────────────────────────────────────────────────────────────

@cli.command()
@click.option("--limit", default=0, help="Only score this many jobs (0 = all).")
def score(limit):
    """Score unscored jobs with Claude and filter below threshold."""
    console.print(Panel(f"[bold blue]Scoring jobs (threshold: {SCORE_THRESHOLD})[/bold blue]"))

    database.init_db()
    unscored = database.get_unscored_jobs()
    if not unscored:
        console.print("[yellow]No unscored jobs found. Run 'fetch' first.[/yellow]")
        return

    # Pre-filter: skip irrelevant titles and international jobs without calling Claude
    to_score = []
    pre_rejected = 0
    for job in unscored:
        if (not is_relevant_title(job["title"])
                or not is_us_location(job.get("location", ""))
                or not is_remote_description(job.get("description", ""))):
            database.mark_job_status(job["id"], "filtered")
            pre_rejected += 1
        else:
            to_score.append(job)

    console.print(
        f"Pre-filter: [green]{len(to_score)}[/green] relevant, "
        f"[dim]{pre_rejected}[/dim] skipped (wrong title/location)"
    )

    if not to_score:
        console.print("[yellow]No jobs left to score after pre-filtering.[/yellow]")
        return

    if limit:
        to_score = to_score[:limit]
        console.print(f"[dim]Limiting to {limit} jobs.[/dim]")

    resume = load_resume()
    results = matcher.score_jobs_batch(resume, to_score, threshold=SCORE_THRESHOLD)

    queued = 0
    rejected = 0
    failed = 0
    for result in results:
        job_id = result["job_id"]
        if job_id is None:
            continue
        # Scoring failed (Claude down / unparseable). Leave the job UNSCORED
        # (score stays NULL, status 'new') so the next score run retries it,
        # rather than burying it as a score-0 reject.
        if result.get("failed"):
            failed += 1
            continue
        database.update_job_score(
            job_id=job_id,
            score=result["score"],
            missing_skills=result["missing"],
            strengths=result["strengths"],
            summary=result["summary"],
            threshold=SCORE_THRESHOLD,
        )
        if result["score"] >= SCORE_THRESHOLD:
            queued += 1
        else:
            rejected += 1

    msg = (
        f"\n[bold green]Done![/bold green] "
        f"[green]{queued}[/green] jobs queued, "
        f"[red]{rejected}[/red] below threshold."
    )
    if failed:
        msg += f" [yellow]{failed} failed to score (left unscored, will retry next run).[/yellow]"
    console.print(msg)


# ── generate ──────────────────────────────────────────────────────────────────

@cli.command()
def generate():
    """Generate tailored resume + cover letter PDFs for queued jobs."""
    console.print(Panel("[bold blue]Generating application materials...[/bold blue]"))

    database.init_db()
    queued_jobs = database.get_queued_jobs()

    if not queued_jobs:
        console.print("[yellow]No queued jobs. Run 'score' first.[/yellow]")
        return

    console.print(f"Generating materials for [cyan]{len(queued_jobs)}[/cyan] jobs...")

    resume = load_resume()

    for i, job in enumerate(queued_jobs, 1):
        company_slug = slugify(job["company"])
        role_slug = slugify(job["title"])
        output_dir = APPLICATIONS_DIR / company_slug / role_slug
        output_dir.mkdir(parents=True, exist_ok=True)

        console.print(
            f"\n[{i}/{len(queued_jobs)}] [bold]{job['company']}[/bold] – {job['title']} "
            f"(score: [green]{job['score']}[/green])"
        )

        strengths = json.loads(job.get("strengths") or "[]")
        description = job.get("description", "")

        # Tailor resume
        console.print("  Tailoring resume...")
        try:
            tailored_resume = generator.tailor_resume(
                resume_json=resume,
                job_description=description,
                strengths=strengths,
            )
        except Exception as exc:
            console.print(f"  [red]Resume tailoring failed: {exc}[/red] — using original")
            tailored_resume = resume

        # Generate cover letter
        console.print("  Generating cover letter...")
        try:
            cover_letter_text = generator.generate_cover_letter(
                resume_json=resume,
                job_description=description,
                company_name=job["company"],
                role_title=job["title"],
            )
        except Exception as exc:
            console.print(f"  [red]Cover letter generation failed: {exc}[/red]")
            cover_letter_text = f"Cover letter for {job['title']} at {job['company']}."

        # Write PDFs (filenames derived from the applicant's name in resume.json)
        resume_pdf_path = output_dir / pdf_writer.resume_pdf_name(resume)
        cover_letter_pdf_path = output_dir / pdf_writer.cover_pdf_name(resume)

        console.print("  Writing PDFs...")
        pdf_writer.write_resume_pdf(tailored_resume, resume_pdf_path)
        pdf_writer.write_cover_letter_pdf(
            text=cover_letter_text,
            applicant_name=resume["name"],
            output_path=cover_letter_pdf_path,
            resume_json=resume,
        )

        # Save text versions too
        (output_dir / "cover_letter.txt").write_text(cover_letter_text)

        # Mark as applied in DB
        database.mark_applied(
            job_id=job["id"],
            resume_path=str(resume_pdf_path),
            cover_letter_path=str(cover_letter_pdf_path),
        )

        console.print(f"  [green]Saved to[/green] {output_dir}")

    console.print(f"\n[bold green]Done![/bold green] Generated materials for {len(queued_jobs)} jobs.")


# ── review ────────────────────────────────────────────────────────────────────

@cli.command()
def review():
    """Interactive review of queued jobs — approve or skip each one."""
    console.print(Panel("[bold blue]Interactive Job Review[/bold blue]"))

    database.init_db()
    queued_jobs = database.get_queued_jobs()

    if not queued_jobs:
        console.print("[yellow]No queued jobs to review.[/yellow]")
        return

    console.print(f"[cyan]{len(queued_jobs)}[/cyan] jobs queued for review.\n")

    approved = []
    skipped = []

    for job in queued_jobs:
        strengths = json.loads(job.get("strengths") or "[]")
        missing = json.loads(job.get("missing_skills") or "[]")

        # Build display panel
        content_lines = []
        content_lines.append(f"[bold]{job['company']}[/bold] — {job['title']}")
        content_lines.append(f"Score: [bold green]{job['score']}/100[/bold green]")
        content_lines.append(f"URL: [link={job['url']}]{job['url']}[/link]\n")

        if strengths:
            content_lines.append("[green]Strengths:[/green]")
            for s in strengths[:5]:
                content_lines.append(f"  • {s}")

        if missing:
            content_lines.append("\n[yellow]Missing skills:[/yellow]")
            for m in missing[:5]:
                content_lines.append(f"  • {m}")

        if job.get("summary"):
            content_lines.append(f"\n[dim]{job['summary']}[/dim]")

        console.print(Panel("\n".join(content_lines), expand=False))

        while True:
            answer = console.input(
                "[bold]Approve this job? ([green]y[/green]/[red]n[/red]/[yellow]q[/yellow]uit)[/bold]: "
            ).strip().lower()

            if answer in ("y", "yes"):
                approved.append(job)
                console.print("[green]Approved.[/green]\n")
                break
            elif answer in ("n", "no", "s", "skip"):
                skipped.append(job)
                database.remove_job(job["id"])
                console.print("[dim]Skipped.[/dim]\n")
                break
            elif answer in ("q", "quit"):
                console.print("[yellow]Quitting review.[/yellow]")
                console.print(
                    f"\nReview complete. [green]{len(approved)}[/green] approved, "
                    f"[red]{len(skipped)}[/red] skipped."
                )
                return
            else:
                console.print("[red]Please enter y, n, or q.[/red]")

    console.print(
        f"\n[bold]Review complete.[/bold] "
        f"[green]{len(approved)}[/green] approved, "
        f"[red]{len(skipped)}[/red] skipped."
    )

    if approved:
        console.print(
            "\n[cyan]Hint:[/cyan] Run [bold]python pipeline.py generate[/bold] to create materials for approved jobs."
        )


# ── sync-sheets ───────────────────────────────────────────────────────────────

@cli.command("sync-sheets")
def sync_sheets():
    """Push all application records to Google Sheets."""
    console.print(Panel("[bold blue]Syncing to Google Sheets...[/bold blue]"))

    try:
        from src import sheets
    except ImportError as exc:
        console.print(f"[red]Import error: {exc}[/red]")
        return

    database.init_db()
    jobs = database.get_all_applied_jobs()

    if not jobs:
        console.print("[yellow]No applications to sync.[/yellow]")
        return

    spreadsheet_id = os.environ.get("GOOGLE_SHEET_ID") or None

    console.print(f"Syncing [cyan]{len(jobs)}[/cyan] records...")

    try:
        sheets.sync_all_applications(jobs, spreadsheet_id=spreadsheet_id)
        console.print(
            f"[bold green]Done![/bold green] Synced {len(jobs)} records."
        )
        if not spreadsheet_id:
            console.print(
                "[yellow]Tip:[/yellow] Save your new GOOGLE_SHEET_ID to .env to reuse the same sheet."
            )
    except FileNotFoundError as exc:
        console.print(f"[red]Error:[/red] {exc}")
    except Exception as exc:
        console.print(f"[red]Sync failed:[/red] {exc}")


# ── reset-filters ─────────────────────────────────────────────────────────────

@cli.command("reset-filters")
def reset_filters():
    """Reset pre-filtered jobs to 'new' so they get re-scored with updated rules."""
    database.init_db()
    count = database.reset_filtered_jobs()
    console.print(f"Reset [green]{count}[/green] filtered jobs back to 'new'. Run [bold]score[/bold] to re-evaluate.")


# ── run (full pipeline) ────────────────────────────────────────────────────────

@cli.command()
@click.pass_context
def run(ctx):
    """Run the full pipeline: fetch → score → generate → sync-sheets."""
    console.print(Panel("[bold blue]Running full pipeline...[/bold blue]", expand=False))

    ctx.invoke(fetch)
    console.print()
    ctx.invoke(score)
    console.print()
    ctx.invoke(generate)
    console.print()
    ctx.invoke(sync_sheets)

    console.print(Panel("[bold green]Pipeline complete![/bold green]", expand=False))


@cli.command()
@click.option("--port", default=8766, help="Port to run on (8765 is the daily-briefing assistant).")
def dashboard(port):
    """Launch the web dashboard."""
    import webbrowser

    import uvicorn
    console.print(Panel(f"[bold blue]Opening dashboard at http://localhost:{port}[/bold blue]", expand=False))
    try:
        webbrowser.open(f"http://localhost:{port}")
    except Exception:
        pass  # headless / no browser — the printed URL is enough
    # localhost only: keeps resumes / cover letters / salary data off the LAN
    uvicorn.run("dashboard.app:app", host="127.0.0.1", port=port, reload=False)


if __name__ == "__main__":
    cli()
