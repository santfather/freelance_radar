"""Коллектор Исторического портала Варшавы (um.warszawa.pl).

«Portal Historyczny Warszawy»: https://mapa.um.warszawa.pl/portal-historyczny/ —
раздел карт, планов и исторической иконографии столицы.

Внимание: портал — JavaScript-приложение, прямого API нет. Коллектор
извлекает изображения из HTML стартовой страницы портала и, как запасной
вариант, с новостных страниц um.warszawa.pl по запросу. Работа ограничена —
в README источник помечен как экспериментальный.
"""

import asyncio
import logging
import os
from urllib.parse import quote

from bs4 import BeautifulSoup

from collectors.base_collector import BaseCollector

logger = logging.getLogger("freelance-radar.collector.um_warszawa")

PORTAL_URL = "https://mapa.um.warszawa.pl/portal-historyczny/"
SEARCH_URL = "https://um.warszawa.pl/-/search?q={query}"
IMAGE_EXT_MARK = (".jpg", ".jpeg", ".png", ".gif", ".tif", ".tiff", ".webp")


class UmWarszawaCollector(BaseCollector):
    source_name = "um_warszawa"
    base_url = "https://um.warszawa.pl"

    async def scrape(self) -> list[dict]:
        assets: list[dict] = []

        # 1. Стартовая страница портала исторических карт
        soup = await self._fetch_soup(PORTAL_URL)
        if soup is None:
            logger.warning("[um_warszawa] портал исторических карт недоступен")
        else:
            items = self._parse_images(soup, PORTAL_URL)
            logger.info("[um_warszawa] портал: найдено %d изображений", len(items))
            assets.extend(await self._collect(items))

        # 2. Запасной вариант — поиск по порталу мэрии
        if len(assets) < self.limit:
            search_url = SEARCH_URL.format(query=quote(self.query))
            soup = await self._fetch_soup(search_url)
            if soup is not None:
                items = self._parse_images(soup, search_url)
                logger.info("[um_warszawa] поиск: найдено %d изображений", len(items))
                assets.extend(await self._collect(items))

        return assets[: self.limit]

    def _parse_images(self, soup: BeautifulSoup, page_url: str) -> list[dict]:
        """Все изображения на странице с подписями из alt."""
        items: list[dict] = []
        seen: set[str] = set()
        for img in soup.select("img[src]"):
            src = img.get("src") or ""
            if not src or "data:image" in src or "pixel" in src.lower():
                continue
            url = self._abs_url(src)
            if not url or url in seen:
                continue
            if not any(mark in url.lower() for mark in IMAGE_EXT_MARK) and "map" not in url.lower():
                continue
            seen.add(url)
            items.append({
                "href": page_url,
                "title": img.get("alt") or "Warszawa historyczna",
                "thumbnail_url": url,
                "file_url": url,
            })
        return items

    async def _collect(self, items: list[dict]) -> list[dict]:
        assets: list[dict] = []
        for item in items:
            asset = {
                "title": item.get("title", "Warszawa historyczna"),
                "source_url": item.get("href", PORTAL_URL),
                "file_url": item["file_url"],
                "thumbnail_url": item.get("thumbnail_url", ""),
                "description": "Исторический портал Варшавы (mapa.um.warszawa.pl)",
                "year": "",
                "source": self.source_name,
                "file_type": self._file_type(item["file_url"]),
            }
            if self._accepts(asset):
                assets.append(asset)
            if len(assets) >= self.limit:
                break
            await asyncio.sleep(1)
        return assets

    @staticmethod
    def _file_type(url: str) -> str:
        ext = os.path.splitext(url.split("?")[0])[1].lower().lstrip(".")
        return ext if ext else "jpg"
