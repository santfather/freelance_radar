"""Коллектор Muzeum Warszawy — цифровые коллекции (kolekcje.muzeumwarszawy.pl).

Источник работает: JSON-поиск `https://kolekcje.muzeumwarszawy.pl/search/?q=...&page=N`
возвращает списки экспонатов (40 на страницу, пагинация через `page`).
Полноразмерные изображения — атрибуты `data-original` на странице объекта
(`/pl/obiekty/{id}/`); один экспонат может иметь несколько ракурсов —
это важно для фотограмметрии, поэтому каждый `data-original` отдаётся
отдельным ассетом. Год — из `creation_dates` в выдаче и блока
`object-creation-date` на странице объекта.
"""

import asyncio
import logging

from collectors.base_collector import BaseCollector
from collectors.utils import extract_year, is_bot_block, limit_text

logger = logging.getLogger("freelance-radar.collector.muzeum_warszawy")

SEARCH = "https://kolekcje.muzeumwarszawy.pl/search/"
ITEM_BASE = "https://kolekcje.muzeumwarszawy.pl/pl/obiekty"
PAGE_SIZE = 40
MAX_DETAIL_PAGES = 10  # предохранитель от бесконечной пагинации


class MuzeumWarszawyCollector(BaseCollector):
    source_name = "muzeum_warszawy"
    base_url = "https://kolekcje.muzeumwarszawy.pl"

    async def scrape(self) -> list[dict]:
        assets: list[dict] = []
        page = 1

        while len(assets) < self.limit and page <= MAX_DETAIL_PAGES:
            data = await self._fetch_json_list(SEARCH, params={
                "q": self.query,
                "page": page,
            })
            if not data:
                break
            if is_bot_block(str(data)[:1000]):
                logger.warning("[muzeum_warszawy] антибот-заглушка в выдаче")
                break

            logger.info(
                "[muzeum_warszawy] страница %d: %d экспонатов по запросу %r",
                page, len(data), self.query,
            )
            for item in data:
                if len(assets) >= self.limit:
                    break
                for asset in await self._parse_item(item):
                    if self._accepts(asset):
                        assets.append(asset)

            if len(data) < PAGE_SIZE:
                break
            page += 1
            await asyncio.sleep(1)

        return assets[: self.limit]

    async def _parse_item(self, item: dict) -> list[dict]:
        """Экспонат → список ассетов (по одному на каждый ракурс)."""
        title = limit_text(item.get("title") or "", 300)
        item_id = item.get("id")
        if not item_id:
            return []
        preview_url = item.get("preview_url") or f"/pl/obiekty/{item_id}/"
        detail_url = self._abs_url(preview_url)

        year = extract_year(str(item.get("creation_dates") or ""))

        # Полноразмерные изображения — со страницы объекта (data-original).
        image_urls = await self._fetch_full_images(detail_url, item_id)
        if not image_urls:
            return []

        thumbnail = item.get("thumbnail") or ""
        description = limit_text(item.get("description") or "", 400)
        if not description:
            creators = item.get("creators") or ""
            description = f"Muzeum Warszawy. Автор: {creators}" if creators else ""

        source_url = self._abs_url(preview_url)
        assets = []
        for num, url in enumerate(image_urls):
            assets.append({
                "title": title if len(image_urls) == 1
                else f"{title} — ракурс {num + 1}",
                "source_url": source_url,
                "file_url": url,
                "thumbnail_url": thumbnail,
                "description": description,
                "year": year,
                "source": self.source_name,
                "file_type": "jpg",
                # тег ракурса для группировки в photogrammetry
                "tags": [f"rakurs_{num + 1}"] if len(image_urls) > 1 else [],
            })
        return assets

    async def _fetch_full_images(self, detail_url: str, item_id: int) -> list[str]:
        """Все `data-original` изображения со страницы объекта (S3, полный размер)."""
        soup = await self._fetch_soup(detail_url)
        if soup is None:
            return []
        urls = []
        for img in soup.select("[data-original]"):
            url = img.get("data-original", "").strip()
            if url.startswith("http") and url not in urls:
                urls.append(url)
        if urls:
            return urls
        # фолбэк: og:image со страницы
        og = soup.find("meta", attrs={"property": "og:image"})
        if og and og.get("content"):
            return [og["content"]]
        return []
