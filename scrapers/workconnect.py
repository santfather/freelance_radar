from bs4 import BeautifulSoup

from models import Job
from scrapers.base import BaseScraper, detect_category, make_id, parse_budget

URLS = [
    "https://www.workconnect.app/zlecenia/programowanie-i-it/aplikacje-mobilne-i-webowe",
    "https://www.workconnect.app/zlecenia/programowanie-i-it/strony-internetowe",
    "https://www.workconnect.app/zlecenia/programowanie-i-it/cms-i-sklepy",
]
BASE = "https://www.workconnect.app"


class WorkConnectScraper(BaseScraper):
    source_name = "workconnect"

    async def scrape(self) -> list[Job]:
        jobs: list[Job] = []
        seen: set[str] = set()

        for url in URLS:
            resp = await self._get(url)
            if not resp:
                continue
            soup = BeautifulSoup(resp.text, "lxml")

            # Confirmed: job links are a[href*='/zlecenie'], inside li.break-words card
            job_links = soup.select("a[href*='/zlecenie']")
            for link in job_links:
                title = link.get_text(strip=True)
                href = link.get("href", "")
                job_url = href if href.startswith("http") else BASE + href
                if not title or len(title) < 8 or job_url in seen:
                    continue
                seen.add(job_url)

                # Walk up to li card
                card = link.find_parent("li")

                description = ""
                budget_raw = ""
                posted_at = ""

                if card:
                    # Description: p with t-14-default class
                    desc_el = card.select_one("p.t-14-default, p[class*='t-14']")
                    if desc_el:
                        description = desc_el.get_text(" ", strip=True)[:600]

                    # Budget: div.t-14-medium.leading-4
                    budget_el = card.select_one("div.t-14-medium")
                    if budget_el:
                        budget_raw = budget_el.get_text(strip=True)
                        if "ofert" in budget_raw.lower() or budget_raw.isdigit():
                            budget_raw = ""  # skip offer counts, not budget

                    # Category label (workconnect shows it in card)
                    cat_el = card.select_one("div.t-12-medium")
                    posted_at_el = card.select_one("time, [class*='date']")
                    if posted_at_el:
                        posted_at = posted_at_el.get("datetime") or posted_at_el.get_text(strip=True)

                    # Skip closed/ended jobs
                    status_els = card.select("div.t-12-medium")
                    is_closed = any(
                        "zakończon" in el.get_text().lower() or "zamknięt" in el.get_text().lower()
                        for el in status_els
                    )
                    if is_closed:
                        continue

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

        print(f"[workconnect] scraped {len(jobs)} jobs")
        return jobs
