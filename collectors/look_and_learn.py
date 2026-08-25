"""Коллектор Look and Learn — парсинг поисковой выдачи.

Поиск: `https://www.lookandlearn.com/search/<query>/`. Из результатов
берутся ссылки на страницы изображений (URL с `/history-images/`), со
страницы изображения — ссылка на полную версию (`og:image` или основной
`img`).

Внимание: сайт защищён Cloudflare. При получении страницы проверки бота
коллектор логирует предупреждение и возвращает пустой список, не ломая
остальные источники.
"""

import asyncio
import logging
import os
from urllib.parse import quote

from bs4 import BeautifulSoup

from collectors.base_collector import BaseCollector

logger = logging.getLogger("freelance-radar.collector.lookandlearn")

BASE = "https://www.lookandlearn.com"
SEARCH_PATH = "/search/"
IMAGE_PATH_MARK = "/history-images/"


class LookAndLearnCollector(BaseCollector):
    source_name = "lookandlearn"
    base_url = BASE

    def _search_url(self) -> str:
        return f"{BASE}{SEARCH_PATH}{quote(self.query)}/"

    async def scrape(self) -> list[dict]:
        url = self._search_url()
        soup = await self._fetch_soup(url)
        if soup is None:
            return []

        if self._is_blocked(soup):
            logger.warning(
                "[lookandlearn] страница поиска защищена (Cloudflare/бота-проверка), "
                "запрос %r — пропуск источника", self.query
            )
            return []

        items = self._parse_results(soup)
        logger.info(
            "[lookandlearn] найдено %d элементов по запросу %r", len(items), self.query
        )

        assets: list[dict] = []
        for item in items[: self._search_window(len(items))]:
            if len(assets) >= self.limit:
                break
            asset = await self._scrape_image_page(item)
            if asset and self._accepts(asset):
                assets.append(asset)
            await asyncio.sleep(1)
        return assets

    def _is_blocked(self, soup: BeautifulSoup) -> bool:
        title = (soup.title.get_text(" ", strip=True) if soup.title else "").lower()
        body_text = soup.get_text(" ", strip=True)[:300].lower()
        return "security verification" in body_text or "verification successful" in body_text \
            or "cloudflare" in title or "just a moment" in body_text

    def _parse_results(self, soup: BeautifulSoup) -> list[dict]:
        """Результаты поиска: ссылки на страницы изображений."""
        items: list[dict] = []
        seen: set[str] = set()

        for a in soup.select(f"a[href*='{IMAGE_PATH_MARK}']"):
            href = a.get("href") or ""
            url = self._abs_url(href)
            if not url or url in seen:
                continue
            seen.add(url)

            thumb = ""
            img = a.select_one("img[src]")
            if img:
                thumb = self._abs_url(img.get("src") or "")
            elif a.parent:
                img = a.parent.select_one("img[src]")
                if img:
                    thumb = self._abs_url(img.get("src") or "")

            title = a.get("title") or a.get_text(" ", strip=True) or ""
            if not title:
                title = url.rsplit("/", 1)[-1].replace("-", " ").replace(".html", "")

            items.append({
                "href": url,
                "title": title,
                "thumbnail_url": thumb,
            })
        return items

    async def _scrape_image_page(self, item: dict) -> dict | None:
        soup = await self._fetch_soup(item["href"])
        if soup is None:
            return None

        file_url = self._full_image_url(soup)
        if not file_url:
            logger.warning("[lookandlearn] нет ссылки на полное изображение: %s", item["href"])
            return None

        description = ""
        meta = soup.select_one("meta[name='description']")
        if meta and meta.get("content"):
            description = meta["content"][:400]
        if not description:
            el = soup.select_one(".description, .caption, #description")
            if el:
                description = el.get_text(" ", strip=True)[:400]

        year = self._extract_year(soup, item.get("title", ""))

        return {
            "title": item.get("title", ""),
            "source_url": item["href"],
            "file_url": file_url,
            "thumbnail_url": item.get("thumbnail_url", ""),
            "description": description,
            "year": year,
            "source": self.source_name,
            "file_type": self._file_type(file_url),
        }

    def _full_image_url(self, soup: BeautifulSoup) -> str:
        """Полное изображение: og:image, основной img или ссылка download."""
        meta = soup.select_one("meta[property='og:image']")
        if meta and meta.get("content"):
            return self._abs_url(meta["content"])

        for sel in ("img#history-image", "img.main-image", ".image-large img",
                    ".history-image img", "img[data-full-image]"):
            img = soup.select_one(sel)
            if img:
                src = img.get("data-full-image") or img.get("src") or img.get("data-src")
                if src:
                    return self._abs_url(src)

        for a in soup.select("a[download], a[href*='/download/']"):
            href = a.get("href") or ""
            if href and "javascript" not in href:
                return self._abs_url(href)

        img = soup.select_one("img[src]")
        if img:
            src = img.get("src") or ""
            if "thumb" not in src and "icon" not in src:
                return self._abs_url(src)
        return ""

    @staticmethod
    def _extract_year(soup: BeautifulSoup, fallback_title: str) -> str:
        import re

        year_re = re.compile(r"\b(1[5-9]\d{2}|20[0-2]\d)\b")
        text = soup.get_text(" ", strip=True)
        for haystack in (text, fallback_title):
            m = year_re.search(haystack)
            if m:
                return m.group(1)
        return ""

    @staticmethod
    def _file_type(url: str) -> str:
        ext = os.path.splitext(url.split("?")[0])[1].lower().lstrip(".")
        return ext if ext else "jpg"
