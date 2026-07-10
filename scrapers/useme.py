from bs4 import BeautifulSoup

from models import Job
from scrapers.base import BaseScraper, detect_category, make_id, parse_budget

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
        seen: set[str] = set()

        for url in URLS:
            resp = await self._get(url)
            if not resp:
                continue
            soup = BeautifulSoup(resp.text, "lxml")

            # Confirmed structure: article.job > a.job__title-link, footer.job__details
            cards = soup.select("article.job")
            for card in cards:
                title_el = card.select_one("a.job__title-link, a.job__title")
                if not title_el:
                    continue
                title = title_el.get_text(strip=True)
                href = title_el.get("href", "")
                job_url = href if href.startswith("http") else BASE + href
                if not title or job_url in seen:
                    continue
                seen.add(job_url)

                # Description is in .job__content (title link is inside it, so strip)
                desc_el = card.select_one(".job__content")
                description = ""
                if desc_el:
                    # Remove the title text from content
                    for a in desc_el.find_all("a"):
                        a.decompose()
                    description = desc_el.get_text(" ", strip=True)[:600]

                # Budget: span.job__budget-value
                budget_el = card.select_one("span.job__budget-value")
                budget_raw = budget_el.get_text(strip=True) if budget_el else ""

                # Date: div.job__header-details--date
                date_el = card.select_one(".job__header-details--date")
                posted_at = date_el.get_text(strip=True) if date_el else ""

                bmin, bmax = parse_budget(budget_raw)
                jobs.append(Job(
                    id=make_id(title, self.source_name),
                    title=title,
                    description=description,
                    url=job_url,
                    source=self.source_name,
                    category=detect_category(title, description),
                    budget_raw=budget_raw,
                    budget_min=bmin,
                    budget_max=bmax,
                    posted_at=posted_at,
                ))

        print(f"[useme] scraped {len(jobs)} jobs")
        return jobs
