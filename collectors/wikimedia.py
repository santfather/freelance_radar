"""Коллектор Wikimedia Commons.

Поиск по категории `Category:<query>` через MediaWiki API; если категории нет
или в ней мало файлов — фолбэк на полнотекстовый поиск файлов. Для каждого
файла страница файла парсится по HTML: из неё берётся ссылка на оригинальный
файл (`div.fullImageLink a` / `a.internal`), миниатюра, описание и год.
"""

import asyncio
import logging
import os
import re
from urllib.parse import quote

from bs4 import BeautifulSoup

from collectors.base_collector import BaseCollector

logger = logging.getLogger("freelance-radar.collector.wikimedia")

API = "https://commons.wikimedia.org/w/api.php"
BASE = "https://commons.wikimedia.org"

YEAR_RE = re.compile(r"\b(1[0-9]{3}|20[0-2]\d)\b")


class WikimediaCollector(BaseCollector):
    source_name = "wikimedia"
    base_url = BASE

    async def scrape(self) -> list[dict]:
        titles = await self._find_file_titles()
        if not titles:
            logger.warning("[wikimedia] ничего не найдено для запроса %r", self.query)
            return []

        assets: list[dict] = []
        for title in titles[: self._search_window(len(titles))]:
            if len(assets) >= self.limit:
                break
            asset = await self._scrape_file_page(title)
            if asset and self._accepts(asset):
                assets.append(asset)
            # вежливая пауза между запросами к страницам файлов
            await asyncio.sleep(1)
        return assets

    # ── Поиск файлов ─────────────────────────────────────────────────────────

    async def _find_file_titles(self) -> list[str]:
        titles = await self._category_members(self.query)
        if len(titles) < self.limit:
            for extra in await self._search_files(self.query):
                if extra not in titles:
                    titles.append(extra)
        return titles

    async def _category_members(self, category: str, limit: int = 500) -> list[str]:
        """Файлы из категории `Category:<name>` через MediaWiki API."""
        params = {
            "action": "query",
            "list": "categorymembers",
            "format": "json",
            "cmtitle": f"Category:{category}",
            "cmtype": "file",
            "cmlimit": min(limit, 500),
        }
        data = await self._fetch_json(API, params=params)
        if not data:
            return []
        return [m["title"] for m in data.get("query", {}).get("categorymembers", [])]

    async def _search_files(self, query: str, limit: int = 100) -> list[str]:
        """Полнотекстовый поиск файлов (namespace 6) как фолбэк к категории."""
        params = {
            "action": "query",
            "list": "search",
            "format": "json",
            "srsearch": query,
            "srnamespace": 6,
            "srlimit": min(limit, 100),
        }
        data = await self._fetch_json(API, params=params)
        if not data:
            return []
        return [h["title"] for h in data.get("query", {}).get("search", [])]

    # ── Страница файла ───────────────────────────────────────────────────────

    async def _scrape_file_page(self, title: str) -> dict | None:
        url = f"{BASE}/wiki/{quote(title.replace(' ', '_'))}"
        soup = await self._fetch_soup(url)
        if soup is None:
            return None

        file_url = self._original_file_url(soup)
        if not file_url:
            logger.warning("[wikimedia] нет ссылки на оригинал: %s", url)
            return None

        thumbnail = ""
        img = soup.select_one("div.fullImageLink img")
        if img:
            thumbnail = self._abs_url(img.get("src") or "")

        description = self._description(soup)
        year = self._extract_year(soup)

        return {
            "title": title.replace("File:", "").replace("_", " "),
            "source_url": url,
            "file_url": file_url,
            "thumbnail_url": thumbnail,
            "description": description,
            "year": year,
            "source": self.source_name,
            "file_type": self._file_type(file_url),
        }

    def _original_file_url(self, soup: BeautifulSoup) -> str:
        """Ссылка на оригинальный файл: `div.fullImageLink a` → `a.internal`."""
        el = soup.select_one("div.fullImageLink a")
        if el:
            url = self._abs_url(el.get("href") or "")
            if url:
                return url
        el = soup.select_one("a.internal[href*='upload.wikimedia.org']")
        if el:
            return self._abs_url(el.get("href") or "")
        el = soup.select_one("link[rel='image_src']")
        if el:
            return self._abs_url(el.get("href") or "")
        return ""

    def _description(self, soup: BeautifulSoup) -> str:
        el = soup.select_one("#fileinfotpl_desc") or soup.select_one(".description")
        if el:
            return el.get_text(" ", strip=True)[:400]
        return ""

    def _extract_year(self, soup: BeautifulSoup) -> str:
        """Год из таблицы метаданных файла (строка Date/Data) или со страницы."""
        for tr in soup.select("table.fileinfotpl tr"):
            th = tr.select_one("th")
            td = tr.select_one("td")
            if th and td and re.search(r"date|data|czas", th.get_text(" ", strip=True), re.I):
                m = YEAR_RE.search(td.get_text(" ", strip=True))
                if m:
                    return m.group(1)
        years = YEAR_RE.findall(soup.get_text(" ", strip=True))
        return years[0] if years else ""

    @staticmethod
    def _file_type(url: str) -> str:
        ext = os.path.splitext(url.split("?")[0])[1].lower().lstrip(".")
        return ext if ext else "jpg"


# Обратная совместимость со старым именем класса
WikimediaCommonsCollector = WikimediaCollector
