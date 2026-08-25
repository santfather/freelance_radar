"""Fiverr.com scraper.

Fiverr is heavily JS-rendered. We scrape search result pages and any
static HTML/schema.org structured data available.
"""

import json

from bs4 import BeautifulSoup

from models import Job, MAX_DESC_LENGTH
from scrapers.base import BaseScraper, parse_budget

URLS = [
    "https://www.fiverr.com/search/gigs?query=web+development&source=top-bar",
    "https://www.fiverr.com/search/gigs?query=mobile+app&source=top-bar",
    "https://www.fiverr.com/search/gigs?query=wordpress&source=top-bar",
    "https://www.fiverr.com/search/gigs?query=python+programming&source=top-bar",
]
BASE = "https://www.fiverr.com"


class FiverrScraper(BaseScraper):
    source_name = "fiverr"

    def __init__(self, timeout: int = 25, delay: tuple = (2, 4)):
        super().__init__(timeout=timeout, delay=delay)

    async def scrape(self) -> list[Job]:
        jobs: list[Job] = []

        for url in URLS:
            resp = await self._get(url)
            if not resp:
                continue
            soup = BeautifulSoup(resp.text, "lxml")

            # Method 1: JSON-LD structured data
            for script in soup.find_all("script", type="application/ld+json"):
                try:
                    data = json.loads(script.string)
                    items = data if isinstance(data, list) else [data]
                    for item in items:
                        if not isinstance(item, dict):
                            continue
                        if item.get("@type") in ("Product", "Service", "ItemList",):
                            entries = item.get("itemListElement", []) if item.get("@type") == "ItemList" else [item]
                            for entry in entries:
                                e = entry if isinstance(entry, dict) else {}
                                if e.get("@type") in ("Product", "Service", "ListItem",):
                                    name = e.get("name", "")
                                    url_val = e.get("url", "")
                                    desc = e.get("description", "")
                                    if not name or not url_val:
                                        continue
                                    if url_val in self.seen:
                                        continue
                                    self.seen.add(url_val)
                                    bmin, bmax = parse_budget(desc)
                                    jobs.append(self._make_job(
                                        title=name, url=url_val,
                                        description=desc[:MAX_DESC_LENGTH],
                                        budget_raw="", budget_min=bmin, budget_max=bmax,
                                    ))
                except (json.JSONDecodeError, TypeError, AttributeError):
                    continue

            # Method 2: search result cards
            cards = (
                soup.select("div.gig-card")
                or soup.select("div[class*='gig']")
                or soup.select("article[class*='gig']")
            )

            for card in cards:
                title_el = (
                    card.select_one("a.gig-card-link")
                    or card.select_one("a[href*='https://www.fiverr.com/']")
                    or card.select_one("h3 a, h4 a")
                )
                if not title_el:
                    continue
                title = title_el.get_text(strip=True)
                href = title_el.get("href", "")
                job_url = href if href.startswith("http") else BASE + href
                if not title or job_url in self.seen:
                    continue
                self.seen.add(job_url)

                desc_el = card.select_one("p[class*='description'], .description, p")
                description = desc_el.get_text(" ", strip=True)[:MAX_DESC_LENGTH] if desc_el else ""

                price_el = card.select_one("[class*='price'], [class*='budget'], strong")
                budget_raw = price_el.get_text(strip=True) if price_el else ""

                bmin, bmax = parse_budget(budget_raw)
                jobs.append(self._make_job(
                    title=title, url=job_url, description=description,
                    budget_raw=budget_raw, budget_min=bmin, budget_max=bmax,
                ))

        return jobs
