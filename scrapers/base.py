import asyncio
import hashlib
import logging
import random
import re
from abc import ABC, abstractmethod
from typing import Callable, Optional

import httpx
from bs4 import BeautifulSoup

from models import Category, Job, MAX_DESC_LENGTH

logger = logging.getLogger("freelance-radar.scraper")

USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3 Safari/605.1.15",
]

BASE_HEADERS = {
    "User-Agent": "",
    "Accept-Language": "en-US,en;q=0.9,pl-PL,pl;q=0.8",
    "Accept-Encoding": "gzip, deflate",
    "Connection": "keep-alive",
}

CATEGORY_KEYWORDS = {
    Category.MOBILE_APP: [
        "android", "ios", "mobile", "flutter", "react native", "swift", "kotlin",
        "aplikacja mobilna", "aplikacje mobilne", "app store", "google play",
        "ipad", "iphone", "xamarin", "ionic", "mobile app", "mobile application",
    ],
    Category.CMS: [
        "wordpress", "woocommerce", "joomla", "drupal", "cms", "magento",
        "prestashop", "shopify", "wix", "elementor", "wtyczka", "plugin",
        "motyw", "theme", "ecommerce", "bigcommerce", "webflow", "content management",
        "headless cms", "strapi", "modx", "bitrix", "1c-bitrix",
    ],
    Category.WEB_APP: [
        "web app", "webapp", "react", "vue", "angular", "next.js", "node",
        "django", "fastapi", "flask", "laravel", "api", "saas", "portal",
        "platforma", "aplikacja webowa", "strona www", "website", "landing",
        "frontend", "backend", "full stack", "fullstack", "rest", "graphql",
        "typescript", "javascript", "html", "css", "tailwind", "bootstrap",
        "web development", "web application", "microservice",
    ],
}


def make_id(title: str, source: str) -> str:
    return hashlib.md5(f"{source}:{title}".encode()).hexdigest()[:12]


def detect_category(title: str, description: str) -> Category:
    text = (title + " " + description).lower()
    scores = {cat: 0 for cat in Category}
    for cat, keywords in CATEGORY_KEYWORDS.items():
        for kw in keywords:
            if kw in text:
                scores[cat] += 1
    best = max(scores, key=lambda c: scores[c])
    return best if scores[best] > 0 else Category.OTHER_IT


def parse_budget(text: str) -> tuple[Optional[int], Optional[int]]:
    """Extract min/max PLN values from budget strings like '500-1500 zł' or 'od 1000 PLN'."""
    nums = re.findall(r"\d[\d\s]*\d|\d+", text.replace(" ", ""))
    nums = [int(n.replace(" ", "")) for n in nums if int(n.replace(" ", "")) > 5]
    if not nums:
        return None, None
    if len(nums) == 1:
        return nums[0], nums[0]
    return min(nums[:2]), max(nums[:2])


class BaseScraper(ABC):
    source_name: str = ""

    def __init__(self, timeout: int = 20, delay: tuple = (1, 3)):
        self.timeout = timeout
        self.delay = delay
        self.seen: set[str] = set()

    def _make_job(self, title: str, url: str, description: str = "",
                  budget_raw: str = "", budget_min: Optional[int] = None,
                  budget_max: Optional[int] = None,
                  posted_at: str = "") -> Job:
        return Job(
            id=make_id(title, self.source_name),
            title=title,
            description=description,
            url=url,
            source=self.source_name,
            category=detect_category(title, description),
            budget_raw=budget_raw,
            budget_min=budget_min,
            budget_max=budget_max,
            posted_at=posted_at,
        )

    async def _get(self, url: str, cookies: dict = None, **kwargs) -> Optional[httpx.Response]:
        headers = dict(BASE_HEADERS)
        headers["User-Agent"] = random.choice(USER_AGENTS)
        headers["Accept"] = "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8"
        headers["Upgrade-Insecure-Requests"] = "1"
        await asyncio.sleep(random.uniform(*self.delay))
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout,
                follow_redirects=True,
                cookies=cookies or {},
            ) as client:
                resp = await client.get(url, headers=headers, **kwargs)
                resp.raise_for_status()
                return resp
        except Exception as e:
            logger.warning(f"[{self.source_name}] fetch error {url}: {e}")
            return None

    async def _get_with_session(self, warmup_url: str, target_url: str) -> Optional[httpx.Response]:
        """Visit warmup_url first to get cookies, then fetch target_url."""
        headers = dict(BASE_HEADERS)
        headers["User-Agent"] = random.choice(USER_AGENTS)
        headers["Accept"] = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout,
                follow_redirects=True,
            ) as client:
                await client.get(warmup_url, headers=headers)
                await asyncio.sleep(random.uniform(1.5, 3))
                resp = await client.get(target_url, headers={
                    **headers, "Referer": warmup_url
                })
                resp.raise_for_status()
                return resp
        except Exception as e:
            logger.warning(f"[{self.source_name}] session fetch error: {e}")
            return None

    async def _scrape_urls(
        self,
        urls: list[str],
        parse_item,
        use_session: bool = False,
        warmup_urls: list[str] | None = None,
    ) -> list[Job]:
        """Шаблонный метод для обхода URL и парсинга страниц.

        parse_item(soup, url) -> list[Job] — вызывается для каждой страницы.
        """
        all_jobs: list[Job] = []
        for i, url in enumerate(urls):
            if use_session:
                warmup = (warmup_urls or urls)[i]
                resp = await self._get_with_session(warmup, url)
            else:
                resp = await self._get(url)
            if not resp:
                continue
            soup = BeautifulSoup(resp.text, "lxml")
            jobs = parse_item(soup, url)
            all_jobs.extend(jobs)
        return all_jobs

    @abstractmethod
    async def scrape(self) -> list[Job]:
        """Scrape jobs and return list of Job objects."""
        ...
