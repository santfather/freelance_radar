import asyncio
import hashlib
import random
import re
from abc import ABC, abstractmethod
from typing import Optional

import httpx

from models import Category, Job

USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3 Safari/605.1.15",
]

CATEGORY_KEYWORDS = {
    Category.MOBILE_APP: [
        "android", "ios", "mobile", "flutter", "react native", "swift", "kotlin",
        "aplikacja mobilna", "aplikacje mobilne", "app store", "google play",
    ],
    Category.CMS: [
        "wordpress", "woocommerce", "joomla", "drupal", "cms", "magento",
        "prestashop", "shopify", "wix", "elementor", "wtyczka", "plugin",
        "motyw", "theme",
    ],
    Category.WEB_APP: [
        "web app", "webapp", "react", "vue", "angular", "next.js", "node",
        "django", "fastapi", "flask", "laravel", "api", "saas", "portal",
        "platforma", "aplikacja webowa", "strona www", "website", "landing",
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
    nums = [int(n.replace(" ", "")) for n in nums if int(n.replace(" ", "")) > 10]
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

    async def _get(self, url: str, cookies: dict = None, **kwargs) -> Optional[httpx.Response]:
        headers = {
            "User-Agent": random.choice(USER_AGENTS),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "pl-PL,pl;q=0.9,en;q=0.8",
            # No 'br' — httpx doesn't support brotli without extra package
            "Accept-Encoding": "gzip, deflate",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
        }
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
            print(f"[{self.source_name}] fetch error {url}: {e}")
            return None

    async def _get_with_session(self, warmup_url: str, target_url: str) -> Optional[httpx.Response]:
        """Visit warmup_url first to get cookies, then fetch target_url."""
        headers = {
            "User-Agent": random.choice(USER_AGENTS),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "pl-PL,pl;q=0.9,en;q=0.8",
            "Accept-Encoding": "gzip, deflate",
            "Connection": "keep-alive",
        }
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
            print(f"[{self.source_name}] session fetch error: {e}")
            return None

    @abstractmethod
    async def scrape(self) -> list[Job]:
        """Scrape jobs and return list of Job objects."""
        ...
