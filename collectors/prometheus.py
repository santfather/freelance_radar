"""Коллектор Prometheus — Deutsche Digitale Bibliothek (35 млн объектов).

Немецкие архивы, библиотеки и музеи: гравюры, карты, планы городов, рукописи.
REST API `https://api.deutsche-digitale-bibliothek.de/search`.

⚠️ Регистрация: для API требуется бесплатный `oauth_consumer_key`
(https://www.deutsche-digitale-bibliothek.de/content/entwicklung).
Ключ задаётся в `.env` как `DDB_API_KEY`. Без ключа источник пропускается
с инструкцией (как europeana/rijksmuseum).

Поля поисковой выдачи: `displayTitle`, `dateOfPublication`/`yearOfPublication`,
`type`, `placeOfPublication`, `thumbnail` (прямая ссылка на изображение),
`item` (ссылка на детали). Пагинация — `start`/`rows`.
"""

import asyncio
import logging
import os

from collectors.base_collector import BaseCollector
from collectors.utils import extract_year, limit_text

logger = logging.getLogger("freelance-radar.collector.prometheus")

API = "https://api.deutsche-digitale-bibliothek.de/search"
BASE = "https://www.deutsche-digitale-bibliothek.de"
ROWS = 100


class PrometheusCollector(BaseCollector):
    source_name = "prometheus"
    base_url = "https://api.deutsche-digitale-bibliothek.de"

    def __init__(self, query: str, limit: int = 20, language: str = "pl",
                 timeout: int = 30, delay: tuple = (1, 3),
                 year_from: int | None = None, year_to: int | None = None):
        super().__init__(query=query, limit=limit, timeout=timeout, delay=delay,
                         year_from=year_from, year_to=year_to)
        self.api_key = os.getenv("DDB_API_KEY", "").strip()

    async def scrape(self) -> list[dict]:
        if not self.api_key:
            logger.warning(
                "[prometheus] DDB_API_KEY не задан в .env — пропуск источника. "
                "Получите бесплатный oauth_consumer_key: "
                "https://www.deutsche-digitale-bibliothek.de/content/entwicklung"
            )
            return []

        assets: list[dict] = []
        start = 0
        while len(assets) < self.limit:
            data = await self._fetch_json(
                API,
                params={
                    "query": self.query,
                    "rows": min(ROWS, max(self.limit, 20)),
                    "start": start,
                    "oauth_consumer_key": self.api_key,
                },
            )
            if not data:
                logger.warning("[prometheus] ошибка/пустой ответ API — пропуск")
                break

            results = data.get("results") or []
            if not results:
                break
            logger.info(
                "[prometheus] страница %d: %d результатов (всего: %s)",
                start // ROWS + 1, len(results), data.get("numberOfResults", 0),
            )
            for item in results:
                asset = self._parse_item(item)
                if asset and self._accepts(asset):
                    assets.append(asset)
                    if len(assets) >= self.limit:
                        break

            start += len(results)
            if start >= int(data.get("numberOfResults", 0) or 0):
                break
            await asyncio.sleep(1)  # вежливая пауза между страницами

        return assets

    def _parse_item(self, item: dict) -> dict | None:
        file_url = item.get("thumbnail") or ""
        if not file_url:
            return None

        title = limit_text(
            item.get("displayTitle") or item.get("primaryTitle") or "", 300
        )
        if not title:
            return None

        # Год: метаданные публикации → тип → заголовок
        year = extract_year(
            str(item.get("yearOfPublication") or ""),
            str(item.get("dateOfPublication") or ""),
            title,
        )

        description = limit_text(
            item.get("placeOfPublication") or "", 200
        )
        item_types = item.get("type") or []
        if isinstance(item_types, list):
            item_types = ", ".join(str(t) for t in item_types if t)
        if item_types:
            description = f"{description} — {item_types}" if description else str(item_types)

        item_id = (item.get("item") or "").rstrip("/").rsplit("/", 1)[-1]
        source_url = f"{BASE}/item/{item_id}" if item_id else f"{BASE}/item"

        return {
            "title": title,
            "source_url": source_url,
            "file_url": file_url,
            "thumbnail_url": file_url,
            "description": description,
            "year": year,
            "source": self.source_name,
            "file_type": self._file_type(file_url),
        }

    @staticmethod
    def _file_type(url: str) -> str:
        path = url.split("?")[0]
        ext = path.rsplit(".", 1)[-1].lower() if "." in path.rsplit("/", 1)[-1] else ""
        return ext if ext in {"jpg", "jpeg", "png", "gif", "tif", "tiff", "webp"} else "jpg"
