#!/usr/bin/env python3
"""
Cross-reference your LinkedIn connections against the target-company list to
build a warm-intro / referral map.

Usage:
    python connections_match.py /path/to/linkedin_archive_dir
    python connections_match.py ~/Downloads/Connections.csv
    python connections_match.py            # auto-searches ~/Downloads for LinkedIn exports

Handles:
  - LinkedIn's "Notes:" preamble rows before the real header
  - Both Connections.csv and Contacts.csv (deduped)
  - Fuzzy/normalized company-name matching ("dbt Labs Inc" -> "dbt Labs")
  - Email-domain matching when the Company field is blank
  - Referral-strength ranking by seniority + role relevance
  - Former-colleague "diaspora" flags (ex-Airbyte/Dagster/HMBradley/Knack/PwC)
  - Cross-reference against jobs you've already applied to
"""

import csv
import io
import json
import re
import sys
import zipfile
from collections import defaultdict
from difflib import SequenceMatcher
from pathlib import Path

ROOT = Path(__file__).parent
COMPANIES_JSON = ROOT / "config" / "companies.json"
DB_PATH = ROOT / "data" / "jobs.db"
PERSONAL_JSON = ROOT / "config" / "personal.json"  # optional, gitignored

# Past employers -> connections at these companies get an "ex-colleague" flag
# (the warmest intros). Loaded from config/personal.json: {"former_employers": [...]}
def _load_former_employers() -> set[str]:
    try:
        with open(PERSONAL_JSON) as f:
            return {e.lower() for e in json.load(f).get("former_employers", [])}
    except (FileNotFoundError, json.JSONDecodeError):
        return set()

FORMER_EMPLOYERS = _load_former_employers()

# Tokens stripped when normalizing a company name for matching.
_SUFFIXES = {
    "inc", "incorporated", "llc", "ltd", "limited", "corp", "corporation",
    "co", "company", "labs", "lab", "technologies", "technology", "tech",
    "software", "io", "ai", "hq", "the", "group", "holdings", "systems",
    "solutions", "global", "international", "com",
}

# Seniority weighting for ranking referral strength.
_SENIORITY = [
    (re.compile(r"\b(founder|co-?founder|ceo|cto|cfo|coo|chief)\b", re.I), 6),
    (re.compile(r"\b(vp|vice president|svp|evp|head of)\b", re.I), 5),
    (re.compile(r"\b(director|principal|staff)\b", re.I), 4),
    (re.compile(r"\b(senior manager|sr\.? manager|lead|manager)\b", re.I), 3),
    (re.compile(r"\b(senior|sr\.?|specialist)\b", re.I), 2),
]
# Role relevance to the candidate's target roles.
_RELEVANT_ROLE = re.compile(
    r"\b(data|analytics|analyst|engineer|engineering|bi|gtm|revops|revenue operations|"
    r"marketing operations|growth|recruit|talent|people|sourcer|hiring|finance|fp&a)\b",
    re.I,
)


def normalize(name: str) -> str:
    if not name:
        return ""
    n = name.lower().strip()
    n = re.sub(r"&", " and ", n)
    n = re.sub(r"[^\w\s]", " ", n)            # drop punctuation
    tokens = [t for t in n.split() if t and t not in _SUFFIXES]
    return " ".join(tokens)


def load_targets() -> dict:
    """Return {normalized_name: original_name}."""
    with open(COMPANIES_JSON) as f:
        companies = json.load(f)
    out = {}
    for c in companies:
        out[normalize(c["name"])] = c["name"]
    return out


def find_header_and_rows(text: str):
    """LinkedIn prepends 2-3 'Notes:' lines. Find the real header row."""
    reader = csv.reader(io.StringIO(text))
    rows = list(reader)
    for i, row in enumerate(rows):
        if row and row[0].strip().lower() in ("first name", "firstname"):
            header = [h.strip() for h in row]
            return header, rows[i + 1:]
    # Fallback: assume first row is header
    return [h.strip() for h in rows[0]], rows[1:]


def col(header, *names):
    low = [h.lower() for h in header]
    for nm in names:
        if nm in low:
            return low.index(nm)
    return None


def read_people(text: str):
    header, rows = find_header_and_rows(text)
    ci = {
        "first": col(header, "first name", "firstname"),
        "last": col(header, "last name", "lastname"),
        "url": col(header, "url"),
        "email": col(header, "email address", "email"),
        "company": col(header, "company"),
        "position": col(header, "position", "title"),
        "connected": col(header, "connected on"),
    }
    people = []
    for r in rows:
        if not r or all(not x.strip() for x in r):
            continue
        def g(key, r=r):  # bind r to this iteration's row
            idx = ci[key]
            return r[idx].strip() if idx is not None and idx < len(r) else ""
        people.append({
            "name": f"{g('first')} {g('last')}".strip(),
            "url": g("url"),
            "email": g("email"),
            "company": g("company"),
            "position": g("position"),
            "connected": g("connected"),
        })
    return people


def seniority_score(title: str) -> int:
    for rx, score in _SENIORITY:
        if rx.search(title or ""):
            return score
    return 1


def fuzzy_target(norm_company: str, targets: dict, cutoff=0.92):
    """Exact first, then high-confidence fuzzy match."""
    if not norm_company:
        return None
    if norm_company in targets:
        return targets[norm_company]
    # token-subset: connection company contains a target as a token-run
    for tnorm, tname in targets.items():
        if not tnorm:
            continue
        if tnorm == norm_company:
            return tname
        # one fully contains the other (token boundary)
        if f" {tnorm} " in f" {norm_company} " or f" {norm_company} " in f" {tnorm} ":
            return tname
    # difflib fallback
    best, best_name = 0.0, None
    for tnorm, tname in targets.items():
        if not tnorm:
            continue
        r = SequenceMatcher(None, norm_company, tnorm).ratio()
        if r > best:
            best, best_name = r, tname
    return best_name if best >= cutoff else None


def load_applied():
    """{normalized_company: [titles]} for jobs already applied to."""
    try:
        import sqlite3
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT company, title FROM jobs WHERE status='applied'"
        ).fetchall()
        out = defaultdict(list)
        for r in rows:
            out[normalize(r["company"])].append(r["title"])
        return out
    except Exception:
        return {}


def locate_csvs(arg: str | None):
    """Return list of (label, text) for Connections/Contacts CSVs."""
    candidates = []
    paths = []
    if arg:
        p = Path(arg).expanduser()
        if p.is_dir():
            paths += list(p.rglob("*.csv")) + list(p.rglob("*.zip"))
        elif p.suffix == ".zip":
            paths.append(p)
        elif p.suffix == ".csv":
            paths.append(p)
    else:
        dl = Path.home() / "Downloads"
        paths += list(dl.glob("*Connections*.csv"))
        paths += list(dl.glob("*Contacts*.csv"))
        paths += list(dl.glob("*[Ll]inked[Ii]n*.zip"))
        paths += list(dl.glob("Complete*LinkedInDataExport*.zip"))

    for p in paths:
        if p.suffix == ".zip":
            with zipfile.ZipFile(p) as z:
                for nm in z.namelist():
                    base = nm.split("/")[-1].lower()
                    if base in ("connections.csv", "contacts.csv"):
                        label = "Connections" if "connections" in base else "Contacts"
                        candidates.append((label, z.read(nm).decode("utf-8", "replace")))
        elif p.suffix == ".csv":
            label = "Connections" if "connection" in p.name.lower() else "Contacts"
            candidates.append((label, p.read_text("utf-8", "replace")))
    return candidates


def main():
    arg = sys.argv[1] if len(sys.argv) > 1 else None
    sources = locate_csvs(arg)
    if not sources:
        print("No Connections.csv / Contacts.csv / LinkedIn .zip found.")
        print("Pass a path, e.g.:  python connections_match.py ~/Downloads/Basic_LinkedInDataExport.zip")
        return

    targets = load_targets()
    applied = load_applied()

    # Merge + dedupe people across files (key on url, else name+company).
    seen = {}
    for label, text in sources:
        for person in read_people(text):
            key = person["url"] or f"{person['name']}|{person['company']}"
            if key not in seen:
                person["_source"] = label
                seen[key] = person
            elif not seen[key].get("email") and person.get("email"):
                seen[key]["email"] = person["email"]  # backfill email from Contacts
    people = list(seen.values())

    matches = []
    for p in people:
        target = fuzzy_target(normalize(p["company"]), targets)
        # email-domain fallback when company is blank/unmatched
        if not target and p["email"] and "@" in p["email"]:
            dom = p["email"].split("@")[1].split(".")[0]
            target = fuzzy_target(normalize(dom), targets)
        if not target:
            continue
        title = p["position"]
        score = seniority_score(title) + (3 if _RELEVANT_ROLE.search(title or "") else 0)
        is_former = normalize(p["company"]) in FORMER_EMPLOYERS or any(
            fe in normalize(p["company"]) for fe in FORMER_EMPLOYERS
        )
        matches.append({
            "target": target, "name": p["name"], "title": title,
            "company_raw": p["company"], "url": p["url"], "score": score,
            "former": is_former, "applied": normalize(target) in applied,
        })

    matches.sort(key=lambda m: (-m["score"], m["target"]))

    # ---- Report ----
    print(f"\n{'='*70}")
    print(f"  LinkedIn referral map  ·  {len(people)} connections scanned")
    print(f"  {len(matches)} sit at one of your {len(targets)} target companies")
    print(f"{'='*70}\n")

    if not matches:
        print("No connections matched a target company.")
        return

    applied_hits = [m for m in matches if m["applied"]]
    if applied_hits:
        print("🔥 ALREADY APPLIED — send a referral nudge to these people:\n")
        for m in applied_hits:
            print(f"  {m['target']:22} {m['name']:24} {m['title']}")
        print()

    print("⭐ TOP REFERRAL TARGETS (by seniority + role relevance):\n")
    for m in matches[:40]:
        flag = " [EX-COLLEAGUE]" if m["former"] else ""
        applied = " ✅applied" if m["applied"] else ""
        print(f"  [{m['score']:>2}] {m['target']:22} {m['name']:24} {m['title']}{flag}{applied}")

    # write full CSV
    out = ROOT / "referral_map.csv"
    with open(out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["target_company", "name", "title", "linkedin_url",
                    "referral_score", "ex_colleague", "already_applied"])
        for m in matches:
            w.writerow([m["target"], m["name"], m["title"], m["url"],
                        m["score"], m["former"], m["applied"]])
    print(f"\nFull map written to {out}  ({len(matches)} rows)")


if __name__ == "__main__":
    main()
