"""SQLite database operations for the job pipeline."""

import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

DB_PATH = Path(__file__).parent.parent / "data" / "jobs.db"

STALE_DAYS = 21  # jobs not seen in 21 days are considered closed


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _migrate(conn: sqlite3.Connection) -> None:
    """Add new columns if they don't exist yet."""
    existing = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='jobs'").fetchone()
    if not existing:
        return
    cols = {row[1] for row in conn.execute("PRAGMA table_info(jobs)").fetchall()}
    migrations = {
        "location":     "ALTER TABLE jobs ADD COLUMN location TEXT",
        "last_seen_at": "ALTER TABLE jobs ADD COLUMN last_seen_at TEXT",
        "removed":      "ALTER TABLE jobs ADD COLUMN removed INTEGER NOT NULL DEFAULT 0",
        "category":     "ALTER TABLE jobs ADD COLUMN category TEXT",
        "salary_min":   "ALTER TABLE jobs ADD COLUMN salary_min INTEGER",
        "salary_max":   "ALTER TABLE jobs ADD COLUMN salary_max INTEGER",
        "salary_raw":   "ALTER TABLE jobs ADD COLUMN salary_raw TEXT",
        "rejected":     "ALTER TABLE jobs ADD COLUMN rejected INTEGER NOT NULL DEFAULT 0",
    }
    for col, sql in migrations.items():
        if col not in cols:
            conn.execute(sql)


def init_db() -> None:
    """Initialize the database schema."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with get_connection() as conn:
        _migrate(conn)
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS jobs (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                company         TEXT NOT NULL,
                title           TEXT NOT NULL,
                url             TEXT UNIQUE NOT NULL,
                platform        TEXT NOT NULL,
                location        TEXT,
                description     TEXT,
                score           INTEGER,
                missing_skills  TEXT,
                strengths       TEXT,
                summary         TEXT,
                status          TEXT NOT NULL DEFAULT 'new',
                removed         INTEGER NOT NULL DEFAULT 0,
                category        TEXT,
                fetched_at      TEXT NOT NULL,
                last_seen_at    TEXT,
                scored_at       TEXT
            );

            CREATE TABLE IF NOT EXISTS applications (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id            INTEGER NOT NULL REFERENCES jobs(id),
                resume_path       TEXT,
                cover_letter_path TEXT,
                created_at        TEXT NOT NULL,
                submitted_at      TEXT,
                notes             TEXT
            );
            """
        )


# ── Company category map ──────────────────────────────────────────────────────

COMPANY_CATEGORIES = {
    # Data tooling
    "dbt Labs": "Data tooling", "Fivetran": "Data tooling", "Hightouch": "Data tooling",
    "Dagster": "Data tooling", "Airbyte": "Data tooling", "Prefect": "Data tooling",
    "Monte Carlo": "Data tooling", "Anomalo": "Data tooling", "Soda Data": "Data tooling",
    "Coalesce": "Data tooling", "Astronomer": "Data tooling", "Matillion": "Data tooling",
    "Meltano": "Data tooling", "Databricks": "Data tooling", "Snowflake": "Data tooling",
    "Starburst": "Data tooling", "Clickhouse": "Data tooling", "Imply": "Data tooling",
    "Atlan": "Data tooling", "Collibra": "Data tooling", "Immuta": "Data tooling",
    # AI companies
    "Anthropic": "AI", "OpenAI": "AI", "Cohere": "AI", "Mistral": "AI",
    "Character AI": "AI", "Adept": "AI", "Perplexity": "AI", "Writer": "AI",
    "ElevenLabs": "AI", "Runway": "AI", "Cursor": "AI", "Glean": "AI",
    "Weights & Biases": "AI", "Anyscale": "AI", "Modal": "AI",
    # Fintech
    "Stripe": "Fintech", "Plaid": "Fintech", "Brex": "Fintech", "Ramp": "Fintech",
    "Mercury": "Fintech", "Carta": "Fintech", "Affirm": "Fintech", "Chime": "Fintech",
    "Robinhood": "Fintech", "Coinbase": "Fintech", "Klarna": "Fintech",
    "Airwallex": "Fintech", "Wise": "Fintech", "Tipalti": "Fintech",
    "Bill.com": "Fintech", "Adyen": "Fintech", "Marqeta": "Fintech",
    # GTM / Sales
    "Apollo.io": "GTM/Sales", "6sense": "GTM/Sales", "Outreach": "GTM/Sales",
    "Salesloft": "GTM/Sales", "Gong": "GTM/Sales", "Clari": "GTM/Sales",
    "DemandBase": "GTM/Sales", "ZoomInfo": "GTM/Sales", "Clearbit": "GTM/Sales",
    "Chili Piper": "GTM/Sales",
    # Analytics tools
    "Amplitude": "Analytics", "Mixpanel": "Analytics", "Heap": "Analytics",
    "FullStory": "Analytics", "Pendo": "Analytics", "Hotjar": "Analytics",
    "Metabase": "Analytics", "Looker": "Analytics", "Tableau": "Analytics",
    "Optimizely": "Analytics",
    # Marketing
    "Klaviyo": "Marketing tech", "Braze": "Marketing tech", "Iterable": "Marketing tech",
    "Attentive": "Marketing tech", "Postscript": "Marketing tech",
    "Customer.io": "Marketing tech", "Sprout Social": "Marketing tech",
    "Hootsuite": "Marketing tech", "The Trade Desk": "Marketing tech",
    # Healthcare
    "Oscar Health": "Healthtech", "Modern Health": "Healthtech", "Doximity": "Healthtech",
    "Inovalon": "Healthtech", "Innovaccer": "Healthtech", "Datavant": "Healthtech",
    "Komodo Health": "Healthtech", "Spring Health": "Healthtech",
    "Flatiron Health": "Healthtech", "Tempus": "Healthtech", "Medidata": "Healthtech",
    # Security
    "CrowdStrike": "Security", "SentinelOne": "Security", "Palo Alto Networks": "Security",
    "Snyk": "Security", "Wiz": "Security", "Drata": "Security", "Vanta": "Security",
    "Huntress": "Security", "Zscaler": "Security", "Netskope": "Security",
    # Enterprise SaaS
    "Salesforce": "Enterprise SaaS", "ServiceNow": "Enterprise SaaS",
    "Atlassian": "Enterprise SaaS", "HubSpot": "Enterprise SaaS",
    "Intercom": "Enterprise SaaS", "Zendesk": "Enterprise SaaS",
    "Freshworks": "Enterprise SaaS",
    # HR tech
    "Rippling": "HR tech", "Deel": "HR tech", "Remote": "HR tech",
    "Gusto": "HR tech", "Lattice": "HR tech", "Culture Amp": "HR tech",
    "Leapsome": "HR tech", "Workday": "HR tech",
    # Logistics
    "Samsara": "Logistics", "Motive": "Logistics", "Flexport": "Logistics",
    "FourKites": "Logistics", "Convoy": "Logistics",
}


def get_category(company: str) -> str:
    return COMPANY_CATEGORIES.get(company, "B2B SaaS")


# ── Core CRUD ────────────────────────────────────────────────────────────────

def save_job(
    company: str,
    title: str,
    url: str,
    platform: str,
    description: str,
    location: str = "",
    salary_min: int | None = None,
    salary_max: int | None = None,
    salary_raw: str | None = None,
) -> int | None:
    """Upsert a job. New jobs are inserted; existing jobs get last_seen_at updated.
    Returns new row id for new jobs, None for updates."""
    now = datetime.utcnow().isoformat()
    category = get_category(company)
    with get_connection() as conn:
        existing = conn.execute(
            "SELECT id FROM jobs WHERE company = ? AND title = ?", (company, title)
        ).fetchone()
        if existing:
            # Update last_seen_at and description in case it changed
            conn.execute(
                "UPDATE jobs SET last_seen_at = ?, description = ? WHERE id = ?",
                (now, description, existing["id"]),
            )
            return None
        try:
            cursor = conn.execute(
                """
                INSERT INTO jobs (company, title, url, platform, location, description,
                                  category, salary_min, salary_max, salary_raw,
                                  fetched_at, last_seen_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (company, title, url, platform, location, description, category,
                 salary_min, salary_max, salary_raw, now, now),
            )
            return cursor.lastrowid
        except sqlite3.IntegrityError:
            return None


def archive_stale_jobs(days: int = STALE_DAYS) -> int:
    """Mark jobs as removed if they haven't been seen in `days` days and aren't applied."""
    cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
    with get_connection() as conn:
        cursor = conn.execute(
            """
            UPDATE jobs SET removed = 1
            WHERE last_seen_at < ?
            AND last_seen_at IS NOT NULL
            AND status NOT IN ('applied')
            AND removed = 0
            """,
            (cutoff,),
        )
        return cursor.rowcount


def get_unscored_jobs() -> list[dict[str, Any]]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM jobs WHERE score IS NULL AND status IN ('new', 'filtered') AND removed = 0"
        ).fetchall()
    return [dict(row) for row in rows]


def reset_filtered_jobs() -> int:
    with get_connection() as conn:
        cursor = conn.execute(
            "UPDATE jobs SET status = 'new' WHERE status = 'filtered' AND removed = 0"
        )
        return cursor.rowcount


def get_queued_jobs() -> list[dict[str, Any]]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM jobs WHERE status = 'queued' AND removed = 0 ORDER BY score DESC"
        ).fetchall()
    return [dict(row) for row in rows]


def get_all_applied_jobs() -> list[dict[str, Any]]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT j.*, a.resume_path, a.cover_letter_path,
                   a.created_at AS app_created_at, a.submitted_at, a.notes
            FROM jobs j
            LEFT JOIN applications a ON a.job_id = j.id
            WHERE j.status IN ('applied', 'queued', 'rejected')
            ORDER BY j.score DESC
            """
        ).fetchall()
    return [dict(row) for row in rows]


def update_job_score(
    job_id: int,
    score: int,
    missing_skills: list[str],
    strengths: list[str],
    summary: str,
    threshold: int = 70,
) -> None:
    status = "queued" if score >= threshold else "rejected"
    now = datetime.utcnow().isoformat()
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE jobs
            SET score = ?, missing_skills = ?, strengths = ?, summary = ?,
                status = ?, scored_at = ?
            WHERE id = ?
            """,
            (score, json.dumps(missing_skills), json.dumps(strengths),
             summary, status, now, job_id),
        )


def mark_job_status(job_id: int, status: str) -> None:
    with get_connection() as conn:
        conn.execute("UPDATE jobs SET status = ? WHERE id = ?", (status, job_id))


def remove_job(job_id: int) -> None:
    """Soft-delete a job (user dismissed it manually)."""
    with get_connection() as conn:
        conn.execute("UPDATE jobs SET removed = 1 WHERE id = ?", (job_id,))


def mark_applied(
    job_id: int,
    resume_path: str,
    cover_letter_path: str,
    notes: str = "",
) -> None:
    now = datetime.utcnow().isoformat()
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO applications (job_id, resume_path, cover_letter_path, created_at, notes)
            VALUES (?, ?, ?, ?, ?)
            """,
            (job_id, resume_path, cover_letter_path, now, notes),
        )
        conn.execute("UPDATE jobs SET status = 'applied' WHERE id = ?", (job_id,))


def get_job_by_id(job_id: int) -> dict[str, Any] | None:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    return dict(row) if row else None
