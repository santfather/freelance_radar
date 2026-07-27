from bs4 import BeautifulSoup

from models import Job
from scrapers.base import BaseScraper, parse_budget

URLS = [
    "https://useme.com/pl/jobs/category/kodowanie-i-it,35/aplikacje-mobilne,101/",
    "https://useme.com/pl/jobs/category/kodowanie-i-it,35/aplikacje-internetowe,102/",
    "https://useme.com/pl/jobs/category/kodowanie-i-it,35/sklepy-i-strony-internetowe,99/",
]
BASE = "https://useme.com"


class UsemeScraper(BaseScraper):
    source_name = "useme"

    async def scrape(self) -> list[Job]:
        jobs: list[Job] = []

        for url in URLS:
            resp = await self._get(url)
            if not resp:
                continue
            soup = BeautifulSoup(resp.text, "lxml")

            cards = soup.select("article.job")
            for card in cards:
                title_el = card.select_one("a.job__title-link, a.job__title")
                if not title_el:
                    continue
                title = title_el.get_text(strip=True)
                href = title_el.get("href", "")
                job_url = href if href.startswith("http") else BASE + href
                if not title or job_url in self.seen:
                    continue
                self.seen.add(job_url)

                desc_el = card.select_one(".job__content")
                description = ""
                if desc_el:
                    for a in desc_el.find_all("a"):
                        a.decompose()
                    description = desc_el.get_text(" ", strip=True)[:600]

                budget_el = card.select_one("span.job__budget-value")
                budget_raw = budget_el.get_text(strip=True) if budget_el else ""

                date_el = card.select_one(".job__header-details--date")
                posted_at = date_el.get_text(strip=True) if date_el else ""

                bmin, bmax = parse_budget(budget_raw)
                jobs.append(self._make_job(
                    title=title, url=job_url, description=description,
                    budget_raw=budget_raw, budget_min=bmin, budget_max=bmax,
                    posted_at=posted_at,
                ))

        return jobs
