"""Fixly.pl scraper — Polish service marketplace."""

from bs4 import BeautifulSoup

from models import Job, MAX_DESC_LENGTH
from scrapers.base import BaseScraper, parse_budget

URLS = [
    "https://fixly.pl/zlecenia/it",
    "https://fixly.pl/zlecenia/programowanie",
    "https://fixly.pl/zlecenia/strony-internetowe",
]
BASE = "https://fixly.pl"


class FixlyScraper(BaseScraper):
    source_name = "fixly"

    async def scrape(self) -> list[Job]:
        jobs: list[Job] = []

        for url in URLS:
            resp = await self._get(url)
            if not resp:
                continue
            soup = BeautifulSoup(resp.text, "lxml")

            cards = (
                soup.select("article.order")
                or soup.select("div.order-card")
                or soup.select("[class*='order']")
                or soup.select("[class*='offer']")
            )

            for card in cards:
                title_el = (
                    card.select_one("a[href*='/zlecenie']")
                    or card.select_one("h3 a, h4 a")
                    or card.select_one("a.order-title")
                )
                if not title_el:
                    continue
                title = title_el.get_text(strip=True)
                href = title_el.get("href", "")
                job_url = href if href.startswith("http") else BASE + href
                if not title or job_url in self.seen:
                    continue
                self.seen.add(job_url)

                desc_el = card.select_one(".description, .order-description, p")
                description = desc_el.get_text(" ", strip=True)[:MAX_DESC_LENGTH] if desc_el else ""

                budget_el = card.select_one(".budget, .price, [class*='budget'], [class*='price']")
                budget_raw = budget_el.get_text(strip=True) if budget_el else ""

                date_el = card.find("time") or card.select_one(".date, .added-date")
                posted_at = date_el.get_text(strip=True) if date_el else ""

                bmin, bmax = parse_budget(budget_raw)
                jobs.append(self._make_job(
                    title=title, url=job_url, description=description,
                    budget_raw=budget_raw, budget_min=bmin, budget_max=bmax,
                    posted_at=posted_at,
                ))

        return jobs
