from bs4 import BeautifulSoup

from models import Job
from scrapers.base import BaseScraper, parse_budget

URLS = [
    "https://zleca.pl/zlecenia/programowanie-strony-internetowe",
    "https://zleca.pl/zlecenia/programowanie-aplikacje-i-programy",
    "https://zleca.pl/zlecenia/programowanie-cms",
]
BASE = "https://zleca.pl"


class ZlecaScraper(BaseScraper):
    source_name = "zleca"

    async def scrape(self) -> list[Job]:
        jobs: list[Job] = []

        for url in URLS:
            resp = await self._get(url)
            if not resp:
                continue
            soup = BeautifulSoup(resp.text, "lxml")

            items = soup.select("ol.list-panels li")
            if not items:
                items_raw = soup.select("a[href*='/zlecenie']")
                for link in items_raw:
                    title = link.get_text(strip=True)
                    href = link.get("href", "")
                    if not title or len(title) < 8:
                        continue
                    job_url = href if href.startswith("http") else BASE + href
                    if job_url in self.seen:
                        continue
                    self.seen.add(job_url)
                    jobs.append(self._make_job(
                        title=title, url=job_url,
                    ))
                continue

            for li in items:
                title_el = li.select_one("h3.title a")
                if not title_el:
                    continue
                title = title_el.get_text(strip=True)
                href = title_el.get("href", "")
                job_url = href if href.startswith("http") else BASE + href
                if not title or job_url in self.seen:
                    continue
                self.seen.add(job_url)

                desc_el = li.select_one("p.description")
                description = desc_el.get_text(" ", strip=True)[:800] if desc_el else ""

                date_el = li.select_one("span.from-to")
                posted_at = date_el.get_text(" ", strip=True)[:40] if date_el else ""

                jobs.append(self._make_job(
                    title=title, url=job_url, description=description,
                    posted_at=posted_at,
                ))

        return jobs
