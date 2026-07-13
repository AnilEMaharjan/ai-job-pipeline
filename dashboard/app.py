"""Job Pipeline Dashboard — FastAPI web UI."""

import json
import os
import sqlite3
import subprocess
import threading
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import FastAPI, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse

DB_PATH = Path(__file__).parent.parent / "data" / "jobs.db"
APPLICATIONS_DIR = Path(__file__).parent.parent / "applications"
PIPELINE_DIR = Path(__file__).parent.parent
CONFIG_DIR = PIPELINE_DIR / "config"
INDEX_HTML = Path(__file__).parent / "templates" / "index.html"
VENV_PYTHON = Path(__file__).parent.parent / ".venv" / "bin" / "python"
REFERRAL_CSV = Path(__file__).parent.parent / "referral_map.csv"
RESUME_JSON = CONFIG_DIR / "resume.json"
PERSONAL_JSON = CONFIG_DIR / "personal.json"
CANDIDATE_NOTES = CONFIG_DIR / "candidate_notes.md"
RESUME_EXAMPLE = CONFIG_DIR / "resume.example.json"

# PDF filenames are derived from the applicant's name in config/resume.json.
# mtime-cached (like load_referrals below) so a Profile-page save is picked up
# immediately without re-reading the file on every request.
_pdf_names_cache: dict = {"mtime": None, "names": ("Applicant_Resume.pdf", "Applicant_CoverLetter.pdf")}


def _pdf_names() -> tuple[str, str]:
    try:
        mtime = RESUME_JSON.stat().st_mtime
    except FileNotFoundError:
        return _pdf_names_cache["names"]
    if _pdf_names_cache["mtime"] != mtime:
        try:
            with open(RESUME_JSON) as f:
                last = (json.load(f).get("name") or "Applicant").strip().split()[-1]
        except Exception:
            last = "Applicant"
        _pdf_names_cache.update(mtime=mtime, names=(f"{last}_Resume.pdf", f"{last}_CoverLetter.pdf"))
    return _pdf_names_cache["names"]

app = FastAPI(title="Job Pipeline Dashboard")


@app.middleware("http")
async def _csrf_guard(request: Request, call_next):
    """Block cross-site state-changing requests (CSRF). Safe methods pass. For
    mutating methods, require Sec-Fetch-Site to be same-origin/none (modern
    browsers), falling back to an Origin/Referer same-origin check (against the
    request's own Host header, not a hardcoded localhost list — so this holds
    whether the dashboard is bound to 127.0.0.1 or a Tailscale IP for a hosted
    friend) for older browsers that omit Sec-Fetch-Site."""
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        sfs = request.headers.get("sec-fetch-site")
        if sfs is not None:
            ok = sfs in ("same-origin", "none")
        else:
            from urllib.parse import urlparse
            origin = request.headers.get("origin") or request.headers.get("referer") or ""
            ok = (urlparse(origin).netloc == request.headers.get("host", "")) if origin else True
        if not ok:
            return JSONResponse({"detail": "cross-site request blocked"}, status_code=403)
    response = await call_next(request)
    # This is a single-user local tool whose data and UI change constantly; never
    # let the browser serve a stale page or API response from cache.
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    return response

# Referral map (LinkedIn connections at target companies), keyed by company name.
_referral_cache: dict = {"mtime": None, "data": {}}


def load_referrals() -> dict:
    """Return {company_name: [connection, ...]} from referral_map.csv, mtime-cached."""
    import csv as _csv
    try:
        mtime = REFERRAL_CSV.stat().st_mtime
    except FileNotFoundError:
        return {}
    if _referral_cache["mtime"] == mtime:
        return _referral_cache["data"]
    data: dict = {}
    with open(REFERRAL_CSV) as f:
        for row in _csv.DictReader(f):
            data.setdefault(row["target_company"], []).append({
                "name": row.get("name", ""),
                "title": row.get("title", ""),
                "url": row.get("linkedin_url", ""),
                "score": int(row.get("referral_score") or 0),
                "ex_colleague": str(row.get("ex_colleague")).lower() == "true",
            })
    for conns in data.values():
        conns.sort(key=lambda c: -c["score"])
    _referral_cache.update(mtime=mtime, data=data)
    return data

# Pipeline run state
_pipeline_state = {"status": "idle", "message": ""}


def _run_pipeline():
    _pipeline_state["status"] = "running"
    _pipeline_state["message"] = "Fetching jobs..."
    env = os.environ.copy()
    env["PATH"] = str(Path.home() / "Library/TinyTeX/bin/universal-darwin") + os.pathsep + env.get("PATH", "")
    try:
        for cmd, msg in [
            (["fetch"], "Fetching jobs..."),
            (["score"], "Scoring jobs..."),
        ]:
            _pipeline_state["message"] = msg
            result = subprocess.run(
                [str(VENV_PYTHON), "pipeline.py"] + cmd,
                cwd=str(PIPELINE_DIR),
                capture_output=True,
                text=True,
                env=env,
            )
            if result.returncode != 0:
                _pipeline_state["status"] = "error"
                _pipeline_state["message"] = result.stderr[-200:] or "Unknown error"
                return
        _pipeline_state["status"] = "done"
        _pipeline_state["message"] = "Fetch & score complete."
    except Exception as e:
        _pipeline_state["status"] = "error"
        _pipeline_state["message"] = str(e)


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# ── API routes ────────────────────────────────────────────────────────────────

_generate_states: dict[int, dict] = {}


def _run_generate(job_id: int):
    _generate_states[job_id] = {"status": "running", "message": "Generating..."}
    env = os.environ.copy()
    env["PATH"] = str(Path.home() / "Library/TinyTeX/bin/universal-darwin") + os.pathsep + env.get("PATH", "")
    try:
        result = subprocess.run(
            [str(VENV_PYTHON), "-c", f"""
import sys, os, json, re, html
from pathlib import Path
sys.path.insert(0, '{PIPELINE_DIR}')
os.environ['PATH'] = str(Path.home() / 'Library/TinyTeX/bin/universal-darwin') + os.pathsep + os.environ.get('PATH', '')
from dotenv import load_dotenv
load_dotenv('{PIPELINE_DIR}/.env', override=True)
from src import generator, pdf_writer
from src.database import get_connection

with open('{PIPELINE_DIR}/config/resume.json') as f:
    resume = json.load(f)

def slugify(t):
    return re.sub(r'[\\s_-]+', '-', re.sub(r'[^\\w\\s-]', '', t.lower().strip()))[:60]

conn = get_connection()
job = dict(conn.execute('SELECT * FROM jobs WHERE id=?', ({job_id},)).fetchone())
desc = html.unescape(re.sub(r'\\s{{2,}}', ' ', re.sub(r'<[^>]+>', ' ', job.get('description','')))).strip()
job['description'] = desc

out_dir = Path('{APPLICATIONS_DIR}') / slugify(job['company']) / slugify(job['title'])
out_dir.mkdir(parents=True, exist_ok=True)
strengths = json.loads(job.get('strengths') or '[]')
gaps = json.loads(job.get('missing_skills') or '[]')
try:
    tailored = generator.tailor_resume(resume, desc, strengths)
except:
    tailored = resume
cover = generator.generate_cover_letter(resume, desc, job['company'], job['title'], strengths=strengths, gaps=gaps)
(out_dir / 'cover_letter.txt').write_text(cover)
pdf_writer.write_resume_pdf(tailored, out_dir / pdf_writer.resume_pdf_name(resume))
pdf_writer.write_cover_letter_pdf(cover, resume['name'], out_dir / pdf_writer.cover_pdf_name(resume), resume_json=tailored)
print('done')
"""],
            cwd=str(PIPELINE_DIR),
            capture_output=True, text=True, env=env, timeout=300,
        )
        if result.returncode == 0:
            _generate_states[job_id] = {"status": "done", "message": "Materials ready"}
        else:
            _generate_states[job_id] = {"status": "error", "message": result.stderr[-150:]}
    except Exception as e:
        _generate_states[job_id] = {"status": "error", "message": str(e)[:150]}


@app.post("/api/jobs/{job_id}/generate")
def generate_job(job_id: int):
    if _generate_states.get(job_id, {}).get("status") == "running":
        return {"ok": False, "message": "Already generating"}
    _generate_states[job_id] = {"status": "starting", "message": "Starting..."}
    thread = threading.Thread(target=_run_generate, args=(job_id,), daemon=True)
    thread.start()
    return {"ok": True}


@app.get("/api/jobs/{job_id}/generate-status")
def generate_status(job_id: int):
    return _generate_states.get(job_id, {"status": "idle", "message": ""})


@app.post("/api/pipeline/run")
def run_pipeline():
    if _pipeline_state["status"] == "running":
        return {"ok": False, "message": "Already running"}
    _pipeline_state["status"] = "starting"
    _pipeline_state["message"] = "Starting..."
    thread = threading.Thread(target=_run_pipeline, daemon=True)
    thread.start()
    return {"ok": True}


@app.get("/api/pipeline/status")
def pipeline_status():
    return _pipeline_state


@app.get("/api/stats")
def stats():
    conn = get_db()
    # rejected=1 is a personal "I passed on this" flag; exclude from the
    # actionable counts so the headline numbers match the default (hide-rejected) view.
    def one(sql, *args):
        row = conn.execute(sql, args).fetchone()
        return row[0] if row and row[0] is not None else 0

    # Total companies tracked (from the source list, not just ones that returned jobs).
    companies_tracked = 0
    try:
        companies_tracked = len(json.loads(
            (PIPELINE_DIR / "config" / "companies.json").read_text()
        ))
    except Exception:
        pass

    # Companies you have at least one LinkedIn connection at (that also have a live job).
    referrals = load_referrals()
    conn_companies = 0
    if referrals:
        live = {r[0] for r in conn.execute(
            "SELECT DISTINCT company FROM jobs WHERE removed=0 AND rejected=0"
        ).fetchall()}
        conn_companies = sum(1 for c in referrals if c in live)

    # Pay stats over jobs you've actually applied to (what you're really pursuing).
    top_pay = one(
        "SELECT MAX(salary_max) FROM jobs WHERE status='applied' AND salary_max IS NOT NULL"
    )
    # Median of the TOP of each posted band (labeled as such in the UI).
    median_applied_pay = one(
        """SELECT salary_max FROM jobs
           WHERE status='applied' AND salary_max IS NOT NULL
           ORDER BY salary_max
           LIMIT 1 OFFSET (
             SELECT COUNT(*)/2 FROM jobs
             WHERE status='applied' AND salary_max IS NOT NULL
           )"""
    )
    # Median of the MIDPOINT of each posted band (or the single bound we have).
    _mid = "(COALESCE(salary_min, salary_max) + salary_max) / 2.0"
    median_applied_mid = one(
        f"""SELECT {_mid} AS mid FROM jobs
           WHERE status='applied' AND salary_max IS NOT NULL
           ORDER BY mid
           LIMIT 1 OFFSET (
             SELECT COUNT(*)/2 FROM jobs
             WHERE status='applied' AND salary_max IS NOT NULL
           )"""
    )

    return {
        "total":    one("SELECT COUNT(*) FROM jobs WHERE removed=0"),
        "queued":   one("SELECT COUNT(*) FROM jobs WHERE status='queued' AND removed=0 AND rejected=0"),
        "applied":  one("SELECT COUNT(*) FROM jobs WHERE status='applied'"),
        "rejected": one("SELECT COUNT(*) FROM jobs WHERE status='rejected' AND removed=0"),
        "new":      one("SELECT COUNT(*) FROM jobs WHERE status='new' AND removed=0 AND rejected=0"),
        "companies": companies_tracked,
        "connections": conn_companies,
        "top_pay": top_pay,
        "median_applied_pay": median_applied_pay,
        "median_applied_mid": median_applied_mid,
    }


@app.get("/api/jobs")
def get_jobs(
    status: str = "queued",
    category: str = "",
    platform: str = "",
    search: str = "",
    sort: str = "posted_desc",
    min_score: int = 0,
    max_score: int = 0,
    min_salary: int = 0,
    has_connection: bool = False,
    hide_applied_cos: bool = False,
    rejected: str = "hide",
    closed: str = "all",
):
    conn = get_db()
    referrals = load_referrals()
    query = "SELECT * FROM jobs WHERE removed = 0"
    params = []

    # Hide jobs at companies where you already applied to a different role
    # (keeps the applied ones themselves visible; just hides the duplicates).
    if hide_applied_cos:
        query += (
            " AND (status = 'applied' OR company NOT IN "
            "(SELECT DISTINCT company FROM jobs WHERE status = 'applied'))"
        )

    # Rejected-by-me is a flag orthogonal to status: hide (default) / only / all
    if rejected == "only":
        query += " AND rejected = 1"
    elif rejected != "all":
        query += " AND rejected = 0"

    if has_connection:
        companies = list(referrals.keys())
        if companies:
            query += f" AND company IN ({','.join('?' * len(companies))})"
            params.extend(companies)
        else:
            query += " AND 1=0"

    # status is a comma-separated list (multi-select); "all" or empty = no filter
    statuses = [s for s in status.split(",") if s and s != "all"]
    if statuses:
        query += f" AND status IN ({','.join('?' * len(statuses))})"
        params.extend(statuses)

    if category:
        query += " AND category = ?"
        params.append(category)

    if platform:
        query += " AND platform = ?"
        params.append(platform)

    if search:
        query += " AND (company LIKE ? OR title LIKE ?)"
        params.extend([f"%{search}%", f"%{search}%"])

    if min_score > 0:
        query += " AND score >= ?"
        params.append(min_score)

    if max_score > 0:
        query += " AND score <= ?"
        params.append(max_score)

    if min_salary > 0:
        query += " AND salary_max >= ?"
        params.append(min_salary)

    # Posting-date sorts fall back to fetched_at (first seen) when a board gave no
    # posting date, so jobs without one still order sensibly instead of vanishing.
    order = {
        "score": "ORDER BY COALESCE(score, 0) DESC",
        "date":  "ORDER BY last_seen_at DESC",
        "company": "ORDER BY company ASC",
        # Newest posting day first, then best score within the same day.
        "posted_desc": "ORDER BY DATE(COALESCE(posted_at, fetched_at)) DESC, COALESCE(score, 0) DESC",
        "posted_asc":  "ORDER BY COALESCE(posted_at, fetched_at) ASC",
    }.get(sort, "ORDER BY DATE(COALESCE(posted_at, fetched_at)) DESC, COALESCE(score, 0) DESC")

    query += f" {order} LIMIT 200"
    rows = conn.execute(query, params).fetchall()

    # A posting is "closed" once it drops out of the company's live feed: the daily
    # fetch refreshes last_seen_at for every currently-listed job, so a stale value
    # means the role is no longer open. (Reliable because it comes from the board
    # API, not the JS-rendered page.) Use 4 days to tolerate a missed daily run.
    CLOSED_CUTOFF = (datetime.utcnow() - timedelta(days=4)).isoformat()

    # Map of company -> roles already applied to (to flag duplicate-company applies
    # and let the UI compare seniority / score / pay / open-status against the role
    # being viewed). Each entry carries whether its own posting is still open.
    applied_by_company: dict[str, list[dict]] = {}
    for ar in conn.execute(
        "SELECT company, title, url, score, salary_min, salary_max, last_seen_at FROM jobs WHERE status='applied'"
    ).fetchall():
        applied_by_company.setdefault(ar["company"], []).append({
            "title": ar["title"], "url": ar["url"], "score": ar["score"],
            "salary_min": ar["salary_min"], "salary_max": ar["salary_max"],
            "closed": (not ar["last_seen_at"]) or (ar["last_seen_at"] < CLOSED_CUTOFF),
        })
    # Count of still-open (recently-seen, not-removed) roles per company, so a
    # closed applied role can point you to what's still open to reapply to.
    open_roles_by_company: dict[str, int] = {}
    for orow in conn.execute(
        "SELECT company, COUNT(*) c FROM jobs WHERE removed=0 AND last_seen_at >= ? GROUP BY company",
        (CLOSED_CUTOFF,),
    ).fetchall():
        open_roles_by_company[orow["company"]] = orow["c"]

    jobs = []
    resume_pdf_name, _ = _pdf_names()
    for r in rows:
        j = dict(r)
        j["strengths"] = json.loads(j.get("strengths") or "[]")[:3]
        j["missing_skills"] = json.loads(j.get("missing_skills") or "[]")[:3]
        # Other roles already applied to at this company (excludes this exact role)
        j["also_applied"] = [
            a for a in applied_by_company.get(j["company"], []) if a["title"] != j["title"]
        ]
        # Posting closed? (dropped out of the live feed) + how many roles the
        # company still has open (for reapply-elsewhere prompts).
        lsa = j.get("last_seen_at")
        j["posting_closed"] = (not lsa) or (lsa < CLOSED_CUTOFF)
        j["company_open_roles"] = open_roles_by_company.get(j["company"], 0)
        # Check if PDFs exist
        import re
        def slugify(t):
            return re.sub(r"[\s_-]+", "-", re.sub(r"[^\w\s-]", "", t.lower().strip()))[:60]
        app_dir = APPLICATIONS_DIR / slugify(j["company"]) / slugify(j["title"])
        j["has_materials"] = (app_dir / resume_pdf_name).exists()
        j["materials_path"] = str(app_dir) if j["has_materials"] else None
        j["connections"] = referrals.get(j["company"], [])
        jobs.append(j)

    if closed == "only":
        jobs = [j for j in jobs if j["posting_closed"]]
    elif closed == "hide":
        jobs = [j for j in jobs if not j["posting_closed"]]

    return jobs


@app.get("/api/categories")
def get_categories():
    conn = get_db()
    rows = conn.execute(
        "SELECT category, COUNT(*) as n FROM jobs WHERE removed=0 AND category IS NOT NULL GROUP BY category ORDER BY n DESC"
    ).fetchall()
    return [{"category": r["category"], "count": r["n"]} for r in rows]


@app.get("/api/platforms")
def get_platforms():
    conn = get_db()
    rows = conn.execute(
        "SELECT platform, COUNT(*) as n FROM jobs WHERE removed=0 AND platform IS NOT NULL GROUP BY platform ORDER BY n DESC"
    ).fetchall()
    return [{"platform": r["platform"], "count": r["n"]} for r in rows]


@app.post("/api/jobs/{job_id}/queue")
def queue_job(job_id: int):
    conn = get_db()
    conn.execute("UPDATE jobs SET status='queued', removed=0 WHERE id=?", (job_id,))
    conn.commit()
    return {"ok": True}


@app.post("/api/jobs/{job_id}/remove")
def remove_job(job_id: int):
    conn = get_db()
    conn.execute("UPDATE jobs SET removed=1 WHERE id=?", (job_id,))
    conn.commit()
    return {"ok": True}


@app.post("/api/jobs/{job_id}/dismiss")
def dismiss_job(job_id: int, reason: str = ""):
    """User rejection flag — orthogonal to status. Optional reason is stored and
    fed back into future scoring so similar jobs rank lower."""
    conn = get_db()
    conn.execute(
        "UPDATE jobs SET rejected=1, reject_reason=? WHERE id=?",
        (reason.strip() or None, job_id),
    )
    conn.commit()
    return {"ok": True}


@app.post("/api/jobs/{job_id}/unreject")
def unreject_job(job_id: int):
    conn = get_db()
    conn.execute("UPDATE jobs SET rejected=0 WHERE id=?", (job_id,))
    conn.commit()
    return {"ok": True}


@app.post("/api/jobs/{job_id}/apply")
def apply_job(job_id: int):
    conn = get_db()
    conn.execute("UPDATE jobs SET status='applied' WHERE id=?", (job_id,))
    conn.commit()
    return {"ok": True}


@app.post("/api/jobs/{job_id}/reject")
def reject_job(job_id: int):
    conn = get_db()
    conn.execute("UPDATE jobs SET status='rejected' WHERE id=?", (job_id,))
    conn.commit()
    return {"ok": True}


def _slugify(t: str) -> str:
    import re
    return re.sub(r"[\s_-]+", "-", re.sub(r"[^\w\s-]", "", t.lower().strip()))[:60]


def _materials_dir(job_id: int) -> Path | None:
    conn = get_db()
    row = conn.execute("SELECT company, title FROM jobs WHERE id=?", (job_id,)).fetchone()
    if not row:
        return None
    return APPLICATIONS_DIR / _slugify(row["company"]) / _slugify(row["title"])


@app.get("/api/jobs/{job_id}/materials")
def list_materials(job_id: int):
    """Which generated materials exist for this job, and the URL to view each.
    Served over HTTP (not opened locally with macOS `open`) so this works
    identically whether the dashboard is local or a hosted friend's instance."""
    app_dir = _materials_dir(job_id)
    if app_dir is None:
        return JSONResponse({"ok": False, "error": "not found"}, status_code=404)
    resume_pdf_name, cover_pdf_name = _pdf_names()
    out = {}
    for kind, name in (("resume", resume_pdf_name), ("cover", cover_pdf_name)):
        exists = (app_dir / name).exists()
        out[kind] = {
            "available": exists,
            "filename": name,
            "url": f"/api/jobs/{job_id}/materials/{kind}" if exists else None,
        }
    return {"ok": True, **out}


@app.get("/api/jobs/{job_id}/materials/{kind}")
def get_material(job_id: int, kind: str):
    if kind not in ("resume", "cover"):
        return JSONResponse({"ok": False, "error": "invalid material kind"}, status_code=400)
    app_dir = _materials_dir(job_id)
    if app_dir is None:
        return JSONResponse({"ok": False, "error": "not found"}, status_code=404)
    resume_pdf_name, cover_pdf_name = _pdf_names()
    name = resume_pdf_name if kind == "resume" else cover_pdf_name
    path = app_dir / name
    if not path.exists():
        return JSONResponse({"ok": False, "error": "material not generated yet"}, status_code=404)
    from fastapi.responses import Response
    return Response(
        content=path.read_bytes(),
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{name}"'},
    )


# ── Profile (self-service onboarding: resume / personal / notes) ──────────────
# Lets a friend on a hosted instance set up their own profile from the browser —
# no host touching the filesystem. Writes the same three files a human would
# hand-edit: config/resume.json, config/personal.json, config/candidate_notes.md.

@app.get("/api/profile")
def get_profile():
    def read_or(path: Path, default: str) -> str:
        try:
            return path.read_text()
        except FileNotFoundError:
            return default

    return {
        "resume": read_or(RESUME_JSON, ""),
        "personal": read_or(PERSONAL_JSON, "{}\n"),
        "notes": read_or(CANDIDATE_NOTES, ""),
        "has_resume": RESUME_JSON.exists(),
    }


@app.post("/api/profile/parse-resume")
def parse_resume_upload(file: UploadFile | None = None, text: str = ""):
    """Convert an uploaded resume (PDF) or pasted text into the resume.json schema
    via Claude. Returns the parsed JSON for review — does NOT save it; the user
    reviews/edits in the Profile editor and saves explicitly via /api/profile/save."""
    from src.resume_import import ResumeParseError, parse_resume

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return JSONResponse({"ok": False, "error": "No ANTHROPIC_API_KEY configured on this instance."}, status_code=400)

    pdf_bytes = None
    if file is not None and file.filename:
        raw = file.file.read()
        if file.filename.lower().endswith(".pdf"):
            pdf_bytes = raw
        else:
            text = raw.decode("utf-8", errors="ignore")
    if not pdf_bytes and not text.strip():
        return JSONResponse({"ok": False, "error": "Upload a PDF or paste resume text."}, status_code=400)

    try:
        example = RESUME_EXAMPLE.read_text()
        data, missing = parse_resume(example, pdf_bytes=pdf_bytes, text=text or None, api_key=api_key)
    except ResumeParseError as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=502)
    except Exception as e:
        return JSONResponse({"ok": False, "error": f"Unexpected error: {e}"}, status_code=500)

    return {"ok": True, "resume": json.dumps(data, indent=2), "missing_keys": missing}


@app.post("/api/profile/save")
async def save_profile(request: Request):
    """Save the profile editor's three fields. Each is optional — only provided
    (non-null) fields are written. resume/personal must be valid JSON text;
    notes is saved as-is (markdown)."""
    body = await request.json()
    errors = {}
    parsed_resume = parsed_personal = None

    if body.get("resume") is not None:
        try:
            parsed_resume = json.loads(body["resume"])
        except json.JSONDecodeError as e:
            errors["resume"] = f"Invalid JSON: {e}"
    if body.get("personal") is not None:
        try:
            parsed_personal = json.loads(body["personal"])
        except json.JSONDecodeError as e:
            errors["personal"] = f"Invalid JSON: {e}"
    if errors:
        return JSONResponse({"ok": False, "errors": errors}, status_code=400)

    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if parsed_resume is not None:
        RESUME_JSON.write_text(json.dumps(parsed_resume, indent=2) + "\n")
    if parsed_personal is not None:
        PERSONAL_JSON.write_text(json.dumps(parsed_personal, indent=2) + "\n")
    if body.get("notes") is not None:
        CANDIDATE_NOTES.write_text(body["notes"])

    return {"ok": True}


# ── Main UI ───────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
def index():
    return HTMLResponse(content=INDEX_HTML.read_text())
