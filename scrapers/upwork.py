"""Upwork scraper — парсит категорийную страницу freelance-jobs.

Основной источник:
  https://www.upwork.com/freelance-jobs/website-development/

RSS — запасной вариант, если категорийная страница не отдала данные.
"""

from urllib.parse import urljoin

from bs4 import BeautifulSoup

from models import Job, MAX_DESC_LENGTH
from scrapers.base import BaseScraper, parse_budget

# Основная страница — веб-разработка
LISTING_URL = "https://www.upwork.com/freelance-jobs/website-development/"

# RSS как fallback
RSS_FEEDS = [
    "https://www.upwork.com/ab/feed/jobs/rss?q=website+development+web+react+vue+node+typescript&sort=recency",
    "https://www.upwork.com/ab/feed/jobs/rss?q=mobile+app+flutter+react+native+swift&sort=recency",
    "https://www.upwork.com/ab/feed/jobs/rss?q=wordpress+cms+shopify+ecommerce&sort=recency",
    "https://www.upwork.com/ab/feed/jobs/rss?q=python+api+backend+fastapi+django+go&sort=recency",
]


class UpworkScraper(BaseScraper):
    source_name = "upwork"

    def __init__(self, timeout: int = 25, delay: tuple = (2, 4)):
        super().__init__(timeout=timeout, delay=delay)

    async def scrape(self) -> list[Job]:
        jobs: list[Job] = []

        # ── Stage 1: категорийная страница website-development ──────────
        found = await self._scrape_listing(LISTING_URL)
        jobs.extend(found)

        # ── Stage 2: RSS fallback ──
        if not jobs:
            for url in RSS_FEEDS:
                found = await self._scrape_rss(url)
                jobs.extend(found)

        return jobs

    async def _scrape_listing(self, url: str) -> list[Job]:
        """Парсит статический HTML страницы freelance-jobs."""
        resp = await self._get(url)
        if not resp:
            return []

        soup = BeautifulSoup(resp.text, "lxml")

        results = self._scrape_by_selectors(soup)
        if not results:
            results = self._scrape_by_links(soup)
        return results

    def _scrape_by_selectors(self, soup) -> list[Job]:
        """Парсинг через data-test атрибуты."""
        results: list[Job] = []
        job_cards = (
            soup.select('[data-test="job-tile"]')
            or soup.select('[data-test="JobTile"]')
            or soup.select("article.job-tile")
            or soup.select("section[class*='job']")
            or soup.select("div[class*='job-tile']")
        )

        for card in job_cards:
            job = self._extract_from_card(card)
            if job:
                results.append(job)
        return results

    def _scrape_by_links(self, soup) -> list[Job]:
        """Fallback: если селекторы не сработали — ищем любые ссылки /jobs/ или /freelance-jobs/."""
        results: list[Job] = []
        for link in soup.find_all("a", href=True):
            href = link.get("href", "")
            if not href.startswith("/jobs/") and "freelance-jobs/" not in href:
                continue
            title = link.get_text(strip=True)
            if not title or len(title) < 8:
                continue
            job_url = urljoin("https://www.upwork.com", href)
            if job_url in self.seen:
                continue
            self.seen.add(job_url)

            card = link.find_parent(["div", "article", "section"])
            description = ""
            if card:
                for tag in card.find_all(["p", "div", "span"]):
                    txt = tag.get_text(strip=True)
                    if len(txt) > 40:
                        description = txt[:MAX_DESC_LENGTH]
                        break

            # На этой площадке бюджет отсутствует в отдельном поле,
            # поэтому ищем его числами в тексте описания и заголовка.
            bmin, bmax = parse_budget(description + " " + title)
            results.append(self._make_job(
                title=title, url=job_url, description=description,
                budget_raw="", budget_min=bmin, budget_max=bmax,
            ))

        return results

    def _extract_from_card(self, card) -> Job | None:
        """Извлекает Job из одной карточки вакансии."""
        title_el = (
            card.select_one("a[data-test*='title'], a[class*='title']")
            or card.select_one("a[href*='/jobs/']")
            or card.find("a", href=True)
        )
        if not title_el:
            return None
        title = title_el.get_text(strip=True)
        href = title_el.get("href", "")
        if not title or len(title) < 8:
            return None

        job_url = urljoin("https://www.upwork.com", href)
        if job_url in self.seen:
            return None
        self.seen.add(job_url)

        desc_el = card.select_one('[data-test*="description"], p[class*="description"]')
        description = desc_el.get_text(" ", strip=True)[:MAX_DESC_LENGTH] if desc_el else ""

        budget_el = card.select_one('[data-test*="budget"], [class*="budget"], [class*="price"]')
        budget_raw = budget_el.get_text(strip=True) if budget_el else ""

        date_el = card.find("time") or card.select_one('[data-test*="date"]')
        posted_at = date_el.get_text(strip=True) if date_el else ""

        # На этой площадке бюджет отсутствует в отдельном поле,
        # поэтому ищем его числами в тексте описания и заголовка.
        bmin, bmax = parse_budget(budget_raw + " " + description)

        return self._make_job(
            title=title, url=job_url, description=description,
            budget_raw=budget_raw, budget_min=bmin, budget_max=bmax,
            posted_at=posted_at,
        )

    async def _scrape_rss(self, url: str) -> list[Job]:
        """Парсит RSS-ленту Upwork."""
        results: list[Job] = []

        resp = await self._get(url)
        if not resp:
            return results

        ct = resp.headers.get("content-type", "").lower()
        if "xml" not in ct:
            return results

        soup = BeautifulSoup(resp.text, "xml")
        items = soup.find_all("item")
        if not items:
            return results

        for item in items:
            title_el = item.find("title")
            if not title_el:
                continue
            title = title_el.get_text(strip=True)

            link_el = item.find("link")
            href = link_el.get_text(strip=True) if link_el else ""

            if not title or len(title) < 8 or href in self.seen:
                continue
            self.seen.add(href)

            desc_el = item.find("description")
            description = desc_el.get_text(" ", strip=True)[:MAX_DESC_LENGTH] if desc_el else ""

            date_el = item.find("pubDate")
            posted_at = date_el.get_text(strip=True) if date_el else ""

            # На этой площадке бюджет отсутствует в отдельном поле,
            # поэтому ищем его числами в тексте описания и заголовка.
            bmin, bmax = parse_budget(description + " " + title)

            results.append(self._make_job(
                title=title, url=href, description=description,
                budget_raw="", budget_min=bmin, budget_max=bmax,
                posted_at=posted_at,
            ))

        return results
