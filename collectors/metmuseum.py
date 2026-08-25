"""Коллектор Metropolitan Museum of Art (MET) — открытый REST API.

400 000+ объектов (живопись, гравюры, рисунки, карты, планы).

- поиск: `https://collectionapi.metmuseum.org/public/collection/v1/search`
  (`q`, `hasImages=true`, серверный фильтр `dateBegin`/`dateEnd`);
- объект: `.../objects/{id}` — `title`, `objectDate`/`objectBeginDate`/
  `objectEndDate` (например, «ca. 1630» / 1625–1635), `primaryImage`
  (полный размер), `primaryImageSmall` (миниатюра), `artistDisplayName`,
  `medium`, `classification`.

Ключ не требуется (опциональная регистрация для больших объёмов —
`MET_API_KEY` зарезервирован, но не используется).
"""

import asyncio
import logging
import os

from collectors.base_collector import BaseCollector
from collectors.utils import coerce_year, extract_year, limit_text

logger = logging.getLogger("freelance-radar.collector.metmuseum")

SEARCH = "https://collectionapi.metmuseum.org/public/collection/v1/search"
OBJECT = "https://collectionapi.metmuseum.org/public/collection/v1/objects"
BASE = "https://www.metmuseum.org"
MAX_OBJECTS_PER_PAGE = 500  # ограничение API поиска
# При малом числе результатов по имени объекта пробуем фолбэк по городу
# (например, «Warsaw»): запросы по конкретным названиям часто дают 0–2 объекта.
MET_FALLBACK_MIN = 5

# Кэш деталей объектов в рамках процесса: запрос по городу («Warsaw») возвращает
# один и тот же набор для каждого объекта, и повторные API-вызовы не нужны.
_MET_CACHE: dict[int, dict | None] = {}


class MetMuseumCollector(BaseCollector):
    source_name = "metmuseum"
    base_url = "https://collectionapi.metmuseum.org"

    async def scrape(self) -> list[dict]:
        object_ids = await self._search()
        if not object_ids:
            logger.warning("[metmuseum] ничего не найдено для запроса %r", self.query)
            return []

        assets: list[dict] = []
        for obj_id in object_ids[: self._search_window(len(object_ids))]:
            if len(assets) >= self.limit:
                break
            asset = await self._fetch_object(obj_id)
            if asset and self._accepts(asset):
                assets.append(asset)
            if obj_id not in _MET_CACHE:
                await asyncio.sleep(0.5)  # вежливая пауза между запросами
        return assets

    async def _search(self) -> list[int]:
        """ID объектов с изображениями; при малом результате по запросу —
        фолбэк на запрос по городу (например, «Warsaw»)."""
        ids = await self._search_query(self.query)
        if len(ids) < MET_FALLBACK_MIN and self.fallback_query:
            logger.info("[metmuseum] мало результатов (%d) по %r — пробую фолбэк %r",
                        len(ids), self.query, self.fallback_query)
            fallback_ids = await self._search_query(self.fallback_query)
            if len(fallback_ids) > len(ids):
                ids = fallback_ids
        return ids

    async def _search_query(self, q: str) -> list[int]:
        """Поиск по одному запросу с серверным фильтром периода и hasImages."""
        params: dict = {"q": q, "hasImages": "true"}
        if self._period_active:
            params["dateBegin"] = self.year_from if self.year_from is not None else 1000
            params["dateEnd"] = self.year_to if self.year_to is not None else 2100

        data = await self._fetch_json(SEARCH, params=params)
        if not data or data.get("total", 0) == 0:
            return []
        ids = data.get("objectIDs") or []
        logger.info("[metmuseum] найдено объектов: %d", data.get("total", len(ids)))
        return [int(i) for i in ids if i]

    async def _fetch_object(self, obj_id: int) -> dict | None:
        if obj_id in _MET_CACHE:
            return _MET_CACHE[obj_id]
        data = await self._fetch_json(f"{OBJECT}/{obj_id}")
        if not data:
            _MET_CACHE[obj_id] = None
            return None

        title = limit_text(data.get("title") or "", 300)
        if not title:
            _MET_CACHE[obj_id] = None
            return None

        file_url = data.get("primaryImage") or ""
        if not file_url:
            _MET_CACHE[obj_id] = None
            return None

        # Год: числовые метаданные объекта → описательная дата → текст
        year = extract_year(
            coerce_year(data.get("objectBeginDate")) or "",
            data.get("objectDate") or "",
            data.get("title") or "",
        )

        description = limit_text(data.get("medium") or "", 300)
        artist = data.get("artistDisplayName") or ""
        if artist:
            description = f"{artist}. {description}" if description else artist

        asset = {
            "title": title,
            "source_url": data.get("objectURL")
                          or f"{BASE}/art/collection/search/{obj_id}",
            "file_url": file_url,
            "thumbnail_url": data.get("primaryImageSmall") or "",
            "description": description,
            "year": year,
            "source": self.source_name,
            "file_type": "jpg",
        }
        _MET_CACHE[obj_id] = asset
        return asset
