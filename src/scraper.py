"""Greenhouse, Lever, and Ashby job board scrapers."""

import asyncio
import html
import re
from typing import Any

import httpx

GREENHOUSE_URL = "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true"
LEVER_URL = "https://api.lever.co/v0/postings/{slug}?mode=json"
ASHBY_URL = "https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=true"

# A dollar figure is only treated as salary if there's pay context nearby, and
# never if there's funding/revenue context (so "$2B in revenue" / "$50M raised"
# don't get mistaken for a salary).
_SALARY_CTX = re.compile(
    r"salary|compensation|base pay|base salary|pay range|pay rate|/\s*yr|per year|"
    r"annually|annual|\bOTE\b|/\s*hour|/\s*hr|hourly|this (?:role|position)|"
    r"the (?:range|position)|expected pay|target (?:pay|compensation)",
    re.I,
)
_NON_SALARY_CTX = re.compile(
    r"revenue|raised|funding|valuation|\bARR\b|in funding|series [a-e]\b|"
    r"backed|invest|market cap|in sales|contract value|saved|savings|managed",
    re.I,
)


def _extract_salary(text: str) -> tuple[int | None, int | None, str | None]:
    """Extract a salary range from description text. Returns (min, max, raw_string).
    Only matches dollar figures that sit in pay context, not funding/revenue."""
    if not text:
        return None, None, None

    def parse_num(s: str) -> int:
        s = s.replace(",", "").strip().lower()
        if s.endswith("k"):
            return int(float(s[:-1]) * 1000)
        return int(float(s))

    # Range patterns. Note the second number's $ and K suffix are BOTH optional,
    # so "$105,000-115,000/yr" and "$120k-$160k" and "$120,000 to $160,000" all match.
    range_patterns = [
        r'\$\s*([\d,]+)\s*([Kk])?\s*(?:–|-|—|to)\s*\$?\s*([\d,]+)\s*([Kk])?',
    ]
    single_patterns = [
        r'up to \$\s*([\d,]+)\s*([Kk])?',
        r'\$\s*([\d,]+)\s*([Kk])?\s*(?:per year|/\s*yr|annually)',
    ]

    for pattern in range_patterns:
        for m in re.finditer(pattern, text, re.IGNORECASE):
            window = text[max(0, m.start() - 60): m.end() + 60]
            if _NON_SALARY_CTX.search(window) or not _SALARY_CTX.search(window):
                continue
            try:
                lo_raw, lo_k, hi_raw, hi_k = m.groups()
                lo = parse_num(lo_raw + ("k" if lo_k else ""))
                hi = parse_num(hi_raw + ("k" if hi_k else ""))
                # if first has K but second doesn't, second is same magnitude (120k-160 -> 160k)
                if lo_k and not hi_k and hi < 1000:
                    hi *= 1000
                if 20000 < lo < 1000000 and 20000 < hi < 1000000 and hi >= lo:
                    return lo, hi, m.group(0).strip()
            except (ValueError, TypeError):
                continue

    for pattern in single_patterns:
        for m in re.finditer(pattern, text, re.IGNORECASE):
            window = text[max(0, m.start() - 60): m.end() + 60]
            if _NON_SALARY_CTX.search(window) or not _SALARY_CTX.search(window):
                continue
            try:
                val = parse_num(m.group(1) + ("k" if m.group(2) else ""))
                if 20000 < val < 1000000:
                    return None, val, m.group(0).strip()
            except (ValueError, TypeError):
                continue

    return None, None, None


INTERNATIONAL_INDICATORS = {
    # countries / regions
    "canada", "uk", "united kingdom", "england", "scotland", "germany",
    "france", "australia", "india", "europe", "emea", "apac", "latam",
    "singapore", "ireland", "netherlands", "brazil", "mexico", "japan",
    "poland", "spain", "italy", "sweden", "israel", "switzerland", "austria",
    "belgium", "denmark", "norway", "finland", "portugal", "czechia",
    "czech republic", "romania", "hungary", "bulgaria", "serbia", "croatia",
    "estonia", "latvia", "lithuania", "ukraine", "turkey", "greece",
    "philippines", "vietnam", "indonesia", "malaysia", "thailand", "china",
    "hong kong", "taiwan", "korea", "pakistan", "nigeria", "kenya", "egypt",
    "south africa", "argentina", "colombia", "chile", "peru", "uruguay",
    "costa rica", "new zealand", "uae", "dubai", "saudi arabia", "qatar",
    # major non-US hub cities (unambiguous ones only)
    "london", "dublin", "berlin", "munich", "paris", "amsterdam", "stockholm",
    "copenhagen", "oslo", "helsinki", "zurich", "geneva", "madrid",
    "barcelona", "lisbon", "warsaw", "krakow", "prague", "vienna", "budapest",
    "tel aviv", "tokyo", "seoul", "beijing", "shanghai", "bangalore",
    "bengaluru", "mumbai", "delhi", "hyderabad", "chennai", "pune",
    "gurgaon", "gurugram", "noida", "manila", "jakarta", "hanoi", "sydney",
    "melbourne", "brisbane", "auckland", "toronto", "vancouver", "montreal",
    "ottawa", "calgary", "mexico city", "sao paulo", "são paulo",
    "buenos aires", "bogota", "santiago", "lima", "lagos", "nairobi",
    "cape town", "johannesburg", "istanbul", "athens", "kyiv", "belgrade",
    "tallinn", "edinburgh", "glasgow",
}

# Word-boundary matching: "uk" must not match Milwaukee, "india" must not
# match Indiana/Indianapolis.
_INTL_RE = re.compile(
    r"\b(" + "|".join(re.escape(i) for i in sorted(INTERNATIONAL_INDICATORS, key=len, reverse=True)) + r")\b"
)

_US_COUNTRY_NAMES = {"us", "usa", "u.s.", "u.s.a.", "united states", "united states of america"}


def _is_us_location(location: str) -> bool:
    if not location:
        return True
    return not _INTL_RE.search(location.lower())


def _country_is_us(country: str | None) -> bool | None:
    """Tri-state check on an explicit country field: True/False, or None if absent."""
    if not country:
        return None
    return country.strip().lower() in _US_COUNTRY_NAMES

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


def _salary_from_lever_range(rng: Any) -> tuple[int | None, int | None, str | None]:
    """Parse Lever's structured salaryRange dict into (min, max, raw).

    Lever shape: {"min": 160000, "max": 180000, "currency": "USD",
    "interval": "per-year-salary"}. Only trust annual USD ranges — hourly or
    non-USD values would otherwise look like absurd salaries.
    """
    if not isinstance(rng, dict):
        return None, None, None
    currency = (rng.get("currency") or "USD").upper()
    interval = (rng.get("interval") or "").lower()
    if currency != "USD" or ("year" not in interval and interval):
        return None, None, None
    try:
        lo = int(rng["min"]) if rng.get("min") is not None else None
        hi = int(rng["max"]) if rng.get("max") is not None else None
    except (ValueError, TypeError):
        return None, None, None
    if not lo and not hi:
        return None, None, None
    # Guard against hourly values mislabeled as annual (e.g. max of 80).
    if (hi or lo or 0) < 1000:
        return None, None, None
    if lo and hi:
        raw = f"${lo:,} – ${hi:,}"
    elif hi:
        raw = f"Up to ${hi:,}"
    else:
        raw = f"From ${lo:,}"
    return lo, hi, raw


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

        # Prefer Lever's structured salaryRange (many boards put pay ONLY here,
        # not in the description body); fall back to scraping the text.
        sal_min, sal_max, sal_raw = _salary_from_lever_range(posting.get("salaryRange"))
        if sal_min is None and sal_max is None:
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
        # Ashby provides a structured country; trust it over string matching when present.
        country_us = _country_is_us(
            ((job.get("address") or {}).get("postalAddress") or {}).get("addressCountry")
        )
        if country_us is False:
            continue
        if country_us is None and not _is_us_location(job.get("location", "")):
            continue

        description = re.sub(r"<[^>]+>", " ", job.get("descriptionHtml", "") or "")
        description = html.unescape(re.sub(r"\s{2,}", " ", description).strip())
        if not description:
            description = job.get("descriptionPlain", "") or ""

        # Structured compensation from Ashby: salary lives in summaryComponents
        # (or compensationTiers[].components), not at the top level.
        comp = job.get("compensation") or {}
        sal_min = sal_max = None
        sal_raw = comp.get("compensationTierSummary") or comp.get("scrapeableCompensationSalarySummary")
        components = list(comp.get("summaryComponents") or [])
        for tier in comp.get("compensationTiers") or []:
            components.extend(tier.get("components") or [])
        for c in components:
            if c.get("compensationType") == "Salary" and (c.get("minValue") or c.get("maxValue")):
                sal_min, sal_max = c.get("minValue"), c.get("maxValue")
                break
        # Fall back to description extraction
        if not sal_min and not sal_max:
            sal_min, sal_max, fallback_raw = _extract_salary(description)
            sal_raw = sal_raw or fallback_raw

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
