from bs4 import BeautifulSoup

from models import Job
from scrapers.base import BaseScraper, detect_category, make_id, parse_budget

CATEGORY_URLS = [
    ("https://oferia.pl/zlecenia/programowanie-it", "https://oferia.pl"),
    ("https://oferia.pl/zlecenia/programowanie-aplikacje-mobilne", "https://oferia.pl"),
    ("https://oferia.pl/zlecenia/programowanie-strony-internetowe", "https://oferia.pl"),
]
BASE = "https://oferia.pl"


class OferiaScraper(BaseScraper):
    source_name = "oferia"

    async def scrape(self) -> list[Job]:
        jobs: list[Job] = []
        seen: set[str] = set()

        for target_url, warmup_url in CATEGORY_URLS:
            # Use session to get cookies first (avoids 403)
            resp = await self._get_with_session(warmup_url, target_url)
            if not resp:
                print(f"[oferia] skipping {target_url} (blocked)")
                continue

            soup = BeautifulSoup(resp.text, "lxml")

            # Try known selectors
            items = (
                soup.select("article.offer") or
                soup.select(".offer-list-item") or
                soup.select("li.offer-item") or
                soup.select(".project-item")
            )

            job_links = []
            if items:
                for item in items:
                    link = item.select_one("a[href]")
                    if link:
                        job_links.append((link, item))
            else:
                # Fallback: any link with /zlecenie/ or /project/
                for a in soup.find_all("a", href=True):
                    href = a.get("href", "")
                    if "/zlecenie/" in href or "/project/" in href:
                        job_links.append((a, a))

            for link, container in job_links:
                title = link.get_text(strip=True)
                href = link.get("href", "")
                job_url = href if href.startswith("http") else BASE + href
                if not title or len(title) < 8 or job_url in seen:
                    continue
                seen.add(job_url)

                desc_el = container.select_one(".description, p")
                description = desc_el.get_text(" ", strip=True)[:800] if desc_el and container != link else ""
                budget_el = container.select_one(".budget, .price")
                budget_raw = budget_el.get_text(strip=True) if budget_el else ""
                date_el = container.select_one("time, .date")
                posted_at = (date_el.get("datetime") or date_el.get_text(strip=True)) if date_el else ""

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

        print(f"[oferia] scraped {len(jobs)} jobs")
        return jobs
