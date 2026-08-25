"""Freelancermap.com scraper — German freelance platform."""

from bs4 import BeautifulSoup

from models import Job, MAX_DESC_LENGTH
from scrapers.base import BaseScraper, parse_budget

URLS = [
    "https://www.freelancermap.com/projects/it-development",
    "https://www.freelancermap.com/projects/it-programming",
    "https://www.freelancermap.com/projects/web-mobile",
]
BASE = "https://www.freelancermap.com"


class FreelancermapScraper(BaseScraper):
    source_name = "freelancermap"

    async def scrape(self) -> list[Job]:
        jobs: list[Job] = []

        for url in URLS:
            resp = await self._get(url)
            if not resp:
                continue
            soup = BeautifulSoup(resp.text, "lxml")

            cards = (
                soup.select("article.project-item")
                or soup.select("div.project-card")
                or soup.select("div[class*='project']")
                or soup.select("li[class*='project']")
            )

            for card in cards:
                title_el = (
                    card.select_one("a[href*='/project/']")
                    or card.select_one("a[href*='/projekt/']")
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

                desc_el = card.select_one(".description, .project-description, p")
                description = desc_el.get_text(" ", strip=True)[:MAX_DESC_LENGTH] if desc_el else ""

                budget_el = card.select_one(".budget, .price, [class*='rate'], [class*='budget']")
                budget_raw = budget_el.get_text(strip=True) if budget_el else ""

                date_el = card.find("time") or card.select_one(".date, .posted-date, .created")
                posted_at = date_el.get_text(strip=True) if date_el else ""

                bmin, bmax = parse_budget(budget_raw)
                jobs.append(self._make_job(
                    title=title, url=job_url, description=description,
                    budget_raw=budget_raw, budget_min=bmin, budget_max=bmax,
                    posted_at=posted_at,
                ))

        return jobs
