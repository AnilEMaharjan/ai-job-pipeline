"""Greenhouse, Lever, and Ashby job board scrapers."""

import asyncio
import html
import re
from typing import Any

import httpx

GREENHOUSE_URL = "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true"
LEVER_URL = "https://api.lever.co/v0/postings/{slug}?mode=json"
ASHBY_URL = "https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=true"

def _extract_salary(text: str) -> tuple[int | None, int | None, str | None]:
    """Extract salary range from job description text. Returns (min, max, raw_string)."""
    if not text:
        return None, None, None
    # Patterns: $120,000 - $160,000 | $120k-$160k | $120K to $160K | up to $200K
    patterns = [
        r'\$\s*([\d,]+)[Kk]?\s*(?:–|-|to)\s*\$\s*([\d,]+)[Kk]?(?:\s*(?:per year|/yr|annually|USD))?',
        r'([\d,]+)[Kk]\s*(?:–|-|to)\s*([\d,]+)[Kk]',
        r'up to \$\s*([\d,]+)[Kk]?',
        r'salary.*?\$\s*([\d,]+)[Kk]?.*?\$\s*([\d,]+)[Kk]?',
    ]
    text_lower = text.lower()
    for pattern in patterns:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            groups = m.groups()
            raw = m.group(0).strip()
            try:
                def parse_num(s: str) -> int:
                    s = s.replace(',', '').strip()
                    n = float(s)
                    # If looks like thousands (< 1000), multiply
                    if n < 1000:
                        n *= 1000
                    return int(n)
                if len(groups) >= 2 and groups[0] and groups[1]:
                    lo = parse_num(groups[0])
                    hi = parse_num(groups[1])
                    if 30000 < lo < 1000000 and 30000 < hi < 1000000:
                        return lo, hi, raw
                elif len(groups) >= 1 and groups[0]:
                    val = parse_num(groups[0])
                    if 30000 < val < 1000000:
                        return None, val, raw
            except (ValueError, TypeError):
                continue
    return None, None, None


INTERNATIONAL_INDICATORS = {
    "canada", "uk", "united kingdom", "germany", "france", "australia",
    "india", "europe", "emea", "apac", "singapore", "ireland", "netherlands",
    "brazil", "mexico", "japan", "poland", "spain", "italy", "sweden",
}


def _is_us_location(location: str) -> bool:
    if not location:
        return True
    loc = location.lower()
    return not any(intl in loc for intl in INTERNATIONAL_INDICATORS)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; job-pipeline/1.0)"
}


async def fetch_greenhouse_jobs(slug: str) -> list[dict[str, Any]]:
    """Fetch jobs from a Greenhouse job board. Returns list of {title, url, description}."""
    url = GREENHOUSE_URL.format(slug=slug)
    try:
        async with httpx.AsyncClient(timeout=20.0, headers=HEADERS) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPStatusError as exc:
        print(f"  [greenhouse/{slug}] HTTP {exc.response.status_code} – skipping")
        return []
    except httpx.RequestError as exc:
        print(f"  [greenhouse/{slug}] Request error: {exc} – skipping")
        return []

    jobs = []
    for job in data.get("jobs", []):
        location = (job.get("location") or {}).get("name", "") or ""
        if "remote" not in location.lower() or not _is_us_location(location):
            continue

        content = job.get("content", "") or ""
        description = re.sub(r"<[^>]+>", " ", content)
        description = html.unescape(re.sub(r"\s{2,}", " ", description).strip())

        sal_min, sal_max, sal_raw = _extract_salary(description)
        jobs.append(
            {
                "title": job.get("title", "").strip(),
                "url": job.get("absolute_url", "").strip(),
                "location": location,
                "description": description,
                "salary_min": sal_min,
                "salary_max": sal_max,
                "salary_raw": sal_raw,
            }
        )
    return jobs


async def fetch_lever_jobs(slug: str) -> list[dict[str, Any]]:
    """Fetch jobs from a Lever job board. Returns list of {title, url, description}."""
    url = LEVER_URL.format(slug=slug)
    try:
        async with httpx.AsyncClient(timeout=20.0, headers=HEADERS) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPStatusError as exc:
        print(f"  [lever/{slug}] HTTP {exc.response.status_code} – skipping")
        return []
    except httpx.RequestError as exc:
        print(f"  [lever/{slug}] Request error: {exc} – skipping")
        return []

    jobs = []
    for posting in data:
        location = (posting.get("categories") or {}).get("location", "") or ""
        workplace_type = posting.get("workplaceType", "") or ""
        if "remote" not in location.lower() and "remote" not in workplace_type.lower():
            continue
        if not _is_us_location(location):
            continue

        # Build description from lists block
        description_parts = []
        for section in posting.get("lists", []):
            description_parts.append(section.get("text", ""))
            for item in section.get("content", "").split("</li>"):
                cleaned = re.sub(r"<[^>]+>", "", item).strip()
                if cleaned:
                    description_parts.append(f"- {cleaned}")

        additional = posting.get("additional", "") or ""
        if additional:
            additional = re.sub(r"<[^>]+>", " ", additional)
            description_parts.append(additional.strip())

        description = "\n".join(description_parts).strip()
        sal_min, sal_max, sal_raw = _extract_salary(description)

        jobs.append(
            {
                "title": posting.get("text", "").strip(),
                "url": posting.get("hostedUrl", "").strip(),
                "location": location or workplace_type,
                "description": description,
                "salary_min": sal_min,
                "salary_max": sal_max,
                "salary_raw": sal_raw,
            }
        )
    return jobs


async def fetch_ashby_jobs(slug: str) -> list[dict[str, Any]]:
    """Fetch jobs from an Ashby job board. Returns list of {title, url, description}."""
    url = ASHBY_URL.format(slug=slug)
    try:
        async with httpx.AsyncClient(timeout=20.0, headers=HEADERS) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPStatusError as exc:
        print(f"  [ashby/{slug}] HTTP {exc.response.status_code} – skipping")
        return []
    except httpx.RequestError as exc:
        print(f"  [ashby/{slug}] Request error: {exc} – skipping")
        return []

    jobs = []
    for job in data.get("jobs", []):
        if not job.get("isRemote") and "remote" not in (job.get("location") or "").lower():
            continue
        if not _is_us_location(job.get("location", "")):
            continue

        description = re.sub(r"<[^>]+>", " ", job.get("descriptionHtml", "") or "")
        description = html.unescape(re.sub(r"\s{2,}", " ", description).strip())
        if not description:
            description = job.get("descriptionPlain", "") or ""

        # Structured compensation from Ashby
        comp = job.get("compensation") or {}
        sal_min = comp.get("minValue") or comp.get("min")
        sal_max = comp.get("maxValue") or comp.get("max")
        sal_raw = comp.get("summary") or comp.get("compensationTierSummary")
        # Fall back to description extraction
        if not sal_min and not sal_max:
            sal_min, sal_max, sal_raw = _extract_salary(description)

        jobs.append(
            {
                "title": job.get("title", "").strip(),
                "url": job.get("applyUrl", "").strip(),
                "location": job.get("location", "Remote"),
                "description": description,
                "salary_min": sal_min,
                "salary_max": sal_max,
                "salary_raw": sal_raw,
            }
        )
    return jobs


async def fetch_recruitee_jobs(slug: str) -> list[dict[str, Any]]:
    """Fetch jobs from a Recruitee job board. Returns list of {title, url, description, ...}."""
    url = f"https://{slug}.recruitee.com/api/offers/"
    try:
        async with httpx.AsyncClient(timeout=20.0, headers=HEADERS) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPStatusError as exc:
        print(f"  [recruitee/{slug}] HTTP {exc.response.status_code} – skipping")
        return []
    except httpx.RequestError as exc:
        print(f"  [recruitee/{slug}] Request error: {exc} – skipping")
        return []

    jobs = []
    for o in data.get("offers", []):
        location = o.get("location") or ", ".join(
            filter(None, [o.get("city"), o.get("country")])
        )
        # Recruitee exposes explicit remote/hybrid/on_site flags — use them.
        is_remote = bool(o.get("remote")) or "remote" in (location or "").lower()
        if not is_remote:
            continue
        if (o.get("hybrid") or o.get("on_site")) and not o.get("remote"):
            continue
        if not _is_us_location(location):
            continue

        description = re.sub(r"<[^>]+>", " ", o.get("description", "") or "")
        description = html.unescape(re.sub(r"\s{2,}", " ", description).strip())

        # Structured salary if present, else fall back to description regex.
        sal_min = sal_max = sal_raw = None
        sal = o.get("salary")
        if isinstance(sal, dict):
            sal_min = int(sal["min"]) if sal.get("min") else None
            sal_max = int(sal["max"]) if sal.get("max") else None
            sal_raw = sal.get("summary") or sal.get("currency")
        if not sal_min and not sal_max:
            sal_min, sal_max, sal_raw = _extract_salary(description)

        jobs.append(
            {
                "title": (o.get("title") or "").strip(),
                "url": (o.get("careers_url") or o.get("careers_apply_url") or "").strip(),
                "location": location or "Remote",
                "description": description,
                "salary_min": sal_min,
                "salary_max": sal_max,
                "salary_raw": sal_raw,
            }
        )
    return jobs


async def fetch_workable_jobs(slug: str) -> list[dict[str, Any]]:
    """Best-effort fetch from a Workable widget board. Workable's public API is
    locked down per-account, so this degrades gracefully (returns [] if not open)."""
    url = f"https://apply.workable.com/api/v1/widget/accounts/{slug}?details=true"
    try:
        async with httpx.AsyncClient(timeout=20.0, headers=HEADERS) as client:
            resp = await client.get(url)
            if resp.status_code != 200:
                return []
            data = resp.json()
    except Exception:
        return []

    jobs = []
    for j in data.get("jobs", []):
        # Workable's widget API returns flat location fields, not a nested dict.
        loc_str = ", ".join(
            filter(None, [j.get("city"), j.get("state"), j.get("country")])
        )
        title = (j.get("title") or "").strip()
        is_remote = (
            bool(j.get("telecommuting"))
            or "remote" in loc_str.lower()
            or "remote" in title.lower()
        )
        if not is_remote:
            continue
        if not _is_us_location(loc_str):
            continue

        description = re.sub(r"<[^>]+>", " ", j.get("description", "") or "")
        description = html.unescape(re.sub(r"\s{2,}", " ", description).strip())
        sal_min, sal_max, sal_raw = _extract_salary(description)

        jobs.append(
            {
                "title": title,
                "url": (j.get("shortlink") or j.get("application_url") or j.get("url") or "").strip(),
                "location": loc_str or "Remote",
                "description": description,
                "salary_min": sal_min,
                "salary_max": sal_max,
                "salary_raw": sal_raw,
            }
        )
    return jobs


async def fetch_all_companies(
    companies_config: list[dict[str, str]],
) -> list[dict[str, Any]]:
    """
    Fetch jobs from all companies in parallel.
    Returns deduplicated list of dicts with keys:
      company, title, url, platform, description
    """

    async def fetch_one(company: dict[str, str]) -> list[dict[str, Any]]:
        name = company["name"]
        platform = company["platform"]
        slug = company["slug"]

        if platform == "greenhouse":
            raw_jobs = await fetch_greenhouse_jobs(slug)
        elif platform == "lever":
            raw_jobs = await fetch_lever_jobs(slug)
        elif platform == "ashby":
            raw_jobs = await fetch_ashby_jobs(slug)
        elif platform == "recruitee":
            raw_jobs = await fetch_recruitee_jobs(slug)
        elif platform == "workable":
            raw_jobs = await fetch_workable_jobs(slug)
        else:
            print(f"  Unknown platform '{platform}' for {name} – skipping")
            return []

        enriched = []
        for job in raw_jobs:
            enriched.append(
                {
                    "company": name,
                    "platform": platform,
                    **job,
                }
            )
        return enriched

    # Limit concurrency to avoid overwhelming the corporate proxy
    semaphore = asyncio.Semaphore(20)

    async def fetch_one_limited(company):
        if company.get("active") is False:
            return []
        async with semaphore:
            return await fetch_one(company)

    tasks = [fetch_one_limited(c) for c in companies_config]
    results = await asyncio.gather(*tasks, return_exceptions=False)

    # Flatten and deduplicate by URL
    seen_urls: set[str] = set()
    all_jobs: list[dict[str, Any]] = []
    for batch in results:
        for job in batch:
            url = job.get("url", "")
            if url and url not in seen_urls:
                seen_urls.add(url)
                all_jobs.append(job)

    return all_jobs
