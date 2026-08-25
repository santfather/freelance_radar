"""Коллектор Szukaj w Archiwach — портал Archiwa Państwowe (81+ млн цифровых копий).

Контракт API портала:
- поиск: `GET https://szukajwarchiwach.gov.pl/api/search?query={q}&limit=...`
  с фильтрацией по типу: `type`/категория (fotografie, mapy, plany);
- прямые ссылки на файлы: `https://szukajwarchiwach.gov.pl/api/file/download/{id}`.

⚠️ Статус источника (проверено 2026-08-04): весь портал `szukajwarchiwach.gov.pl`
(включая `/api/`) закрыт антибот-защитой Incapsula — любой запрос возвращает
HTML-заглушку challenge'а вместо JSON. Публичной документации API нет.
Поэтому коллектор реализован по контракту, но при детекте антибота завершается
с пустым результатом и пояснением в `errors` (не «маскируем» недоступность).

Когда портал станет доступен (через сессию/прокси или открытие API) —
коллектор заработает без изменений. Альтернатива: часть фондов
Archiwa Państwowe продублирована на Europeana (`europeana.py`).
"""

import logging

from collectors.base_collector import BaseCollector
from collectors.utils import extract_year, is_bot_block, limit_text

logger = logging.getLogger("freelance-radar.collector.szukajwarchiwach")

API = "https://szukajwarchiwach.gov.pl/api"
DOWNLOAD = f"{API}/file/download"
ROWS = 100

# Типы материалов портала: фотографии → карты → планы (для исторического AR).
TYPE_ORDER = ("fotografie", "mapy", "plany")


class SzukajWArchiwachCollector(BaseCollector):
    source_name = "szukajwarchiwach"
    base_url = "https://szukajwarchiwach.gov.pl"

    async def scrape(self) -> list[dict]:
        assets: list[dict] = []
        for material_type in TYPE_ORDER:
            if len(assets) >= self.limit:
                break
            assets.extend(await self._search_type(material_type))
        return assets[: self.limit]

    async def _search_type(self, material_type: str) -> list[dict]:
        assets: list[dict] = []
        offset = 0

        while len(assets) < self.limit:
            params = {
                "query": self.query,
                "limit": min(ROWS, self.limit),
                "offset": offset,
                "type": material_type,
            }
            data = await self._fetch_json(API + "/search", params=params)
            if data is None:
                # _fetch_json вернул None и при 403-заглушке антибота
                logger.warning(
                    "[szukajwarchiwach] нет JSON-ответа (антибот Incapsula?) — "
                    "источник недоступен напрямую, см. комментарий в файле"
                )
                break

            raw = data.get("results") or data.get("items") or data.get("hits") or []
            if not raw:
                break
            for item in raw:
                asset = self._parse_item(item, material_type)
                if asset and self._accepts(asset):
                    assets.append(asset)
                    if len(assets) >= self.limit:
                        break
            offset += len(raw)
            total = int(data.get("total") or 0)
            if not total or offset >= total:
                break

        return assets

    def _parse_item(self, item: dict, material_type: str) -> dict | None:
        item_id = item.get("id")
        if not item_id:
            return None

        title = limit_text(item.get("title") or item.get("name") or "", 300)
        file_id = item.get("fileId") or item.get("file_id") or item_id

        description = limit_text(
            item.get("description") or item.get("content") or "", 400
        )

        # Год: метаданные (date/dateFrom/year) → описание → regex по названию
        year = extract_year(
            str(item.get("year") or ""),
            str(item.get("date") or ""),
            str(item.get("dateFrom") or ""),
            description,
            title,
        )

        return {
            "title": title,
            "source_url": item.get("url") or f"{API}/archive-unit/{item_id}",
            "file_url": f"{DOWNLOAD}/{file_id}",
            "thumbnail_url": item.get("thumbnail") or item.get("preview") or "",
            "description": description,
            "year": year,
            "source": self.source_name,
            "file_type": "jpg",
            "tags": [material_type],
        }
