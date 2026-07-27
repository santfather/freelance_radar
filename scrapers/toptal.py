"""Toptal scraper — job listings are mostly JS-rendered, so coverage is limited.

Toptal loads listings dynamically. We scrape what's available in the static HTML:
position cards, JSON-LD structured data, and any pre-rendered job links.
"""

import json
import re

from bs4 import BeautifulSoup

from models import Job
from scrapers.base import BaseScraper, parse_budget

URL = "https://www.toptal.com/freelance-jobs"
BASE = "https://www.toptal.com"


class ToptalScraper(BaseScraper):
    source_name = "toptal"

    def __init__(self, timeout: int = 20, delay: tuple = (2, 4)):
        super().__init__(timeout=timeout, delay=delay)

    async def scrape(self) -> list[Job]:
        jobs: list[Job] = []

        resp = await self._get(URL)
        if not resp:
            return jobs

        soup = BeautifulSoup(resp.text, "lxml")

        # ── Method 1: JSON-LD structured data ──────────────────────────────
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string)
                if isinstance(data, list):
                    for item in data:
                        self._add_from_ld(item, jobs)
                else:
                    self._add_from_ld(data, jobs)
            except (json.JSONDecodeError, TypeError, AttributeError):
                continue

        # ── Method 2: job cards / listing items ────────────────────────────
        for link in soup.find_all("a", href=True):
            href = link.get("href", "")
            if not self._is_job_link(href):
                continue
            title = link.get_text(strip=True)
            if not title or len(title) < 8 or href in self.seen:
                continue

            job_url = href if href.startswith("http") else BASE + href
            if job_url in self.seen:
                continue
            self.seen.add(job_url)

            card = link.find_parent(["div", "li", "article"])
            description = ""
            if card:
                desc_el = card.find("p") or card.find(
                    "div", class_=lambda c: c and "desc" in (c or "").lower()
                )
                if desc_el:
                    description = desc_el.get_text(" ", strip=True)[:600]

            bmin, bmax = parse_budget(description + " " + title)
            jobs.append(self._make_job(
                title=title, url=job_url, description=description,
                budget_raw="", budget_min=bmin, budget_max=bmax,
            ))

        # Deduplicate by id (JSON-LD may overlap with HTML links)
        seen_ids: set[str] = set()
        unique: list[Job] = []
        for j in jobs:
            if j.id not in seen_ids:
                seen_ids.add(j.id)
                unique.append(j)

        return unique

    @staticmethod
    def _is_job_link(href: str) -> bool:
        if re.search(r"/freelance-jobs/[a-z]|/jobs/[a-z]", href):
            segments = href.strip("/").split("/")
            if len(segments) >= 3:
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

    def _add_from_ld(self, data: dict, jobs: list[Job]):
        """Extract a job from JSON-LD item if it represents a job posting."""
        if not isinstance(data, dict):
            return
        if data.get("@type") not in ("JobPosting", "ItemList",):
            return
        title = data.get("title", "") or data.get("name", "")
        url = data.get("url", "")
        desc = data.get("description", "") or data.get("summary", "")
        if not title or not url or url in self.seen:
            return
        self.seen.add(url)

        bmin, bmax = parse_budget(desc + " " + title)
        jobs.append(self._make_job(
            title=title.strip(), url=url, description=desc[:800],
            budget_raw="", budget_min=bmin, budget_max=bmax,
        ))
