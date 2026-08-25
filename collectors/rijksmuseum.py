"""Коллектор Rijksmuseum — государственный музей Нидерландов.

700 000+ изображений: гравюры, картины, рисунки, планы XVII–XIX вв.
Официальный REST API (`https://www.rijksmuseum.nl/api/...`), требуется
бесплатный ключ `RIJKSMUSEUM_API_KEY` (регистрация:
https://www.rijksmuseum.nl/en/rijksstudio/start).

- поиск: `.../api/en/collection?key=...&q=...&ps=100&p=1`;
- поля: `title`/`longTitle`, `principalOrFirstMaker`, `webImage.url`
  (полный размер ~1300px), `dating.yearEarly`/`yearLate`/`presentingDate`,
  `classification.iconClassDescription`, `links.web`.

Год берётся из `dating` (числовой диапазон → год), фильтр по периоду —
серверный через `f.dating.period` не гарантирован, поэтому используется
постфильтрация по извлечённому году.
"""

import asyncio
import logging
import os

from collectors.base_collector import BaseCollector
from collectors.utils import coerce_year, extract_year, limit_text

logger = logging.getLogger("freelance-radar.collector.rijksmuseum")

API = "https://www.rijksmuseum.nl/api"
PAGE_SIZE = 100  # максимум на страницу


class RijksmuseumCollector(BaseCollector):
    source_name = "rijksmuseum"
    base_url = "https://www.rijksmuseum.nl"

    def __init__(self, query: str, limit: int = 20, language: str = "pl",
                 timeout: int = 30, delay: tuple = (1, 3),
                 year_from: int | None = None, year_to: int | None = None):
        super().__init__(query=query, limit=limit, timeout=timeout, delay=delay,
                         year_from=year_from, year_to=year_to)
        self.api_key = os.getenv("RIJKSMUSEUM_API_KEY", "").strip()
        # API поддерживает только nl/en
        self.api_lang = language if language in ("nl", "en") else "en"

    async def scrape(self) -> list[dict]:
        if not self.api_key:
            logger.warning(
                "[rijksmuseum] RIJKSMUSEUM_API_KEY не задан в .env — пропуск источника. "
                "Получите бесплатный ключ: "
                "https://www.rijksmuseum.nl/en/rijksstudio/start"
            )
            return []

        assets: list[dict] = []
        page = 0
        while len(assets) < self.limit:
            data = await self._fetch_json(
                f"{API}/{self.api_lang}/collection",
                params={
                    "key": self.api_key,
                    "q": self.query,
                    "format": "json",
                    "ps": min(PAGE_SIZE, max(self.limit, 20)),
                    "p": page + 1,
                },
            )
            if not data:
                logger.warning("[rijksmuseum] ошибка/пустой ответ API — пропуск")
                break

            items = data.get("artObjects") or []
            if not items:
                break
            logger.info(
                "[rijksmuseum] страница %d: %d объектов (всего: %s)",
                page + 1, len(items), data.get("count", 0),
            )
            for item in items:
                asset = self._parse_item(item)
                if asset and self._accepts(asset):
                    assets.append(asset)
                    if len(assets) >= self.limit:
                        break

            page += 1
            if page * PAGE_SIZE >= int(data.get("count", 0) or 0):
                break
            await asyncio.sleep(1)  # вежливая пауза между страницами

        return assets

    def _parse_item(self, item: dict) -> dict | None:
        web_image = item.get("webImage") or {}
        file_url = web_image.get("url") or ""
        if not file_url or not item.get("hasImage"):
            return None

        title = limit_text(item.get("longTitle") or item.get("title") or "", 300)
        if not title:
            return None

        # Год: числовой диапазон dating → описательная дата → заголовок
        dating = item.get("dating") or {}
        year = extract_year(
            coerce_year(dating.get("yearEarly")) or "",
            dating.get("presentingDate") or "",
            title,
        )

        description_parts = []
        maker = item.get("principalOrFirstMaker") or ""
        if maker:
            description_parts.append(f"Автор: {maker}")
        classification = (item.get("classification") or {}).get("iconClassDescription") or ""
        if classification:
            description_parts.append(classification)
        description = limit_text(" · ".join(p for p in description_parts if p), 400)

        return {
            "title": title,
            "source_url": (item.get("links") or {}).get("web")
                          or f"https://www.rijksmuseum.nl/en/collection/{item.get('objectNumber', '')}",
            "file_url": file_url,
            "thumbnail_url": file_url,
            "description": description,
            "year": year,
            "source": self.source_name,
            "file_type": "jpg",
            "width": web_image.get("width"),
            "height": web_image.get("height"),
        }
