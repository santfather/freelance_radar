"""Toptal scraper — job listings are mostly JS-rendered, so coverage is limited.

Toptal loads listings dynamically. We scrape what's available in the static HTML:
position cards, JSON-LD structured data, and any pre-rendered job links.
"""

import json
import re

from bs4 import BeautifulSoup

from models import Job
from scrapers.base import BaseScraper, detect_category, make_id, parse_budget

URL = "https://www.toptal.com/freelance-jobs"
BASE = "https://www.toptal.com"


class ToptalScraper(BaseScraper):
    source_name = "toptal"

    def __init__(self, timeout: int = 20, delay: tuple = (2, 4)):
        super().__init__(timeout=timeout, delay=delay)

    async def scrape(self) -> list[Job]:
        jobs: list[Job] = []
        seen: set[str] = set()

        resp = await self._get(URL)
        if not resp:
            print("[toptal] fetch failed")
            return jobs

        soup = BeautifulSoup(resp.text, "lxml")

        # ── Method 1: JSON-LD structured data (most reliable) ──────────────
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string)
                if isinstance(data, list):
                    for item in data:
                        self._add_from_ld(item, jobs, seen)
                else:
                    self._add_from_ld(data, jobs, seen)
            except (json.JSONDecodeError, TypeError, AttributeError):
                continue

        # ── Method 2: job cards / listing items ────────────────────────────
        # Look for links with a job-title-like pattern (not generic nav links)
        for link in soup.find_all("a", href=True):
            href = link.get("href", "")

            # Skip non-job links: nav, footer, social, auth, etc.
            if not self._is_job_link(href):
                continue

            title = link.get_text(strip=True)
            if not title or len(title) < 8 or href in seen:
                continue

            job_url = href if href.startswith("http") else BASE + href
            if job_url in seen:
                continue
            seen.add(job_url)

            card = link.find_parent(["div", "li", "article"])
            description = ""
            if card:
                desc_el = card.find("p") or card.find(
                    "div", class_=lambda c: c and "desc" in (c or "").lower()
                )
                if desc_el:
                    description = desc_el.get_text(" ", strip=True)[:600]

            bmin, bmax = parse_budget(description + " " + title)
            jobs.append(Job(
                id=make_id(title, self.source_name),
                title=title,
                description=description,
                url=job_url,
                source=self.source_name,
                category=detect_category(title, description),
                budget_raw="",
                budget_min=bmin,
                budget_max=bmax,
            ))

        # Deduplicate by id (JSON-LD may overlap with HTML links)
        seen_ids: set[str] = set()
        unique: list[Job] = []
        for j in jobs:
            if j.id not in seen_ids:
                seen_ids.add(j.id)
                unique.append(j)

        print(f"[toptal] scraped {len(unique)} jobs")
        return unique

    @staticmethod
    def _is_job_link(href: str) -> bool:
        """Return True if href looks like a specific job posting, not a nav link."""
        # Must look like a real job posting
        if re.search(r"/freelance-jobs/[a-z]|/jobs/[a-z]", href):
            # Exclude generic section links (3 or fewer path segments)
            segments = href.strip("/").split("/")
            if len(segments) >= 3:
                # Exclude known non-job patterns
                skip = [
                    "login", "signup", "register", "auth",
                    "about", "contact", "blog", "faq",
                    "how-it-works", "for-clients", "for-freelancers",
                    "careers", "press", "legal", "privacy",
                ]
                last_seg = segments[-1].lower()
                if not any(s in last_seg for s in skip):
                    return True
        return False

    @staticmethod
    def _add_from_ld(data: dict, jobs: list[Job], seen: set[str]):
        """Extract a job from JSON-LD item if it represents a job posting."""
        if not isinstance(data, dict):
            return
        if data.get("@type") not in ("JobPosting", "ItemList",):
            return
        title = data.get("title", "") or data.get("name", "")
        url = data.get("url", "")
        desc = data.get("description", "") or data.get("summary", "")
        if not title or not url or url in seen:
            return
        seen.add(url)

        bmin, bmax = parse_budget(desc + " " + title)
        jobs.append(Job(
            id=make_id(title, "toptal"),
            title=title.strip(),
            description=desc[:800],
            url=url,
            source="toptal",
            category=detect_category(title, desc),
            budget_raw="",
            budget_min=bmin,
            budget_max=bmax,
        ))
