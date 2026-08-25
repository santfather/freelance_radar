"""Gigster.com scraper.

Gigster is primarily JS-rendered. We scrape whatever static HTML and
JSON-LD structured data is available on their jobs/careers pages.
"""

import json
import re

from bs4 import BeautifulSoup

from models import Job, MAX_DESC_LENGTH
from scrapers.base import BaseScraper, parse_budget

URL = "https://gigster.com/jobs"
BASE = "https://gigster.com"


class GigsterScraper(BaseScraper):
    source_name = "gigster"

    def __init__(self, timeout: int = 25, delay: tuple = (2, 4)):
        super().__init__(timeout=timeout, delay=delay)

    async def scrape(self) -> list[Job]:
        jobs: list[Job] = []

        resp = await self._get(URL)
        if not resp:
            return jobs

        soup = BeautifulSoup(resp.text, "lxml")

        # Method 1: JSON-LD
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string)
                items = data if isinstance(data, list) else [data]
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    if item.get("@type") != "JobPosting":
                        continue
                    title = item.get("title", "")
                    url_val = item.get("url", "")
                    desc = item.get("description", "") or item.get("summary", "")
                    if not title or not url_val or url_val in self.seen:
                        continue
                    self.seen.add(url_val)
                    bmin, bmax = parse_budget(desc)
                    jobs.append(self._make_job(
                        title=title.strip(), url=url_val,
                        description=desc[:MAX_DESC_LENGTH],
                        budget_raw="", budget_min=bmin, budget_max=bmax,
                    ))
            except (json.JSONDecodeError, TypeError, AttributeError):
                continue

        # Method 2: job links in static HTML
        for link in soup.find_all("a", href=True):
            href = link.get("href", "")
            if not re.search(r"/jobs/[a-z]", href) and "/job/" not in href:
                continue
            title = link.get_text(strip=True)
            if not title or len(title) < 8 or href in self.seen:
                continue
            job_url = href if href.startswith("http") else BASE + href
            if job_url in self.seen:
                continue
            self.seen.add(job_url)

            card = link.find_parent(["div", "li", "article", "section"])
            description = ""
            if card:
                for tag in card.find_all(["p", "div", "span"]):
                    txt = tag.get_text(strip=True)
                    if len(txt) > 30:
                        description = txt[:MAX_DESC_LENGTH]
                        break

            bmin, bmax = parse_budget(description)
            jobs.append(self._make_job(
                title=title, url=job_url, description=description,
                budget_raw="", budget_min=bmin, budget_max=bmax,
            ))

        return jobs
