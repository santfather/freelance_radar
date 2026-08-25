"""Freelancer.com scraper."""

from bs4 import BeautifulSoup

from models import Job, MAX_DESC_LENGTH
from scrapers.base import BaseScraper, parse_budget

URLS = [
    "https://www.freelancer.com/jobs/web-development",
    "https://www.freelancer.com/jobs/mobile-app-development",
    "https://www.freelancer.com/jobs/wordpress",
    "https://www.freelancer.com/jobs/python",
]
BASE = "https://www.freelancer.com"


class FreelancerScraper(BaseScraper):
    source_name = "freelancer"

    def __init__(self, timeout: int = 25, delay: tuple = (2, 4)):
        super().__init__(timeout=timeout, delay=delay)

    async def scrape(self) -> list[Job]:
        jobs: list[Job] = []

        for url in URLS:
            resp = await self._get(url)
            if not resp:
                continue
            soup = BeautifulSoup(resp.text, "lxml")

            cards = (
                soup.select("div.JobSearchCard-item")
                or soup.select("div.project-item")
                or soup.select("div[class*='project']")
                or soup.select("div[class*='job']")
            )

            for card in cards:
                title_el = (
                    card.select_one("a.JobSearchCard-primary-heading-link")
                    or card.select_one("a[href*='/projects/']")
                    or card.select_one("a[href*='/project/']")
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

                desc_el = card.select_one(
                    ".JobSearchCard-primary-description, "
                    ".project-description, p.description"
                )
                description = desc_el.get_text(" ", strip=True)[:MAX_DESC_LENGTH] if desc_el else ""

                budget_el = card.select_one(
                    ".JobSearchCard-secondary-price, "
                    "[class*='budget'], [class*='price']"
                )
                budget_raw = budget_el.get_text(strip=True) if budget_el else ""

                date_el = card.find("time") or card.select_one(
                    ".JobSearchCard-primary-subtitle-date, .date, .posted-date"
                )
                posted_at = date_el.get_text(strip=True) if date_el else ""

                bmin, bmax = parse_budget(budget_raw)
                jobs.append(self._make_job(
                    title=title, url=job_url, description=description,
                    budget_raw=budget_raw, budget_min=bmin, budget_max=bmax,
                    posted_at=posted_at,
                ))

        return jobs
