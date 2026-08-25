"""Коллектор Polona.pl — Национальная библиотека Польши (JSON API).

Использует официальный JSON API: поиск `https://polona2.pl/api/entities`
с параметрами `query`, `from` (пагинация), `limit`, `filters` (категории).
Полноразмерный JPG каждого объекта отдаётся через
`https://polona2.pl/archive?uid={academica_id}&cid={main_scan_id}&name=download_fullJPG`
(проверено: скан 9700×7209 px).

Приоритет категорий: фотографии → карты → планы → открытки — для
фотограмметрии и исторического AR важны фотографии и картография.
"""

import asyncio
import logging

from collectors.base_collector import BaseCollector
from collectors.utils import extract_year, extract_year_iso, is_bot_block, limit_text

logger = logging.getLogger("freelance-radar.collector.polona")

API = "https://polona2.pl/api/entities"
ARCHIVE = "https://polona2.pl/archive"
ITEM_BASE = "https://polona.pl/item/"
ROWS = 40

# Категории Polona по убыванию приоритета для исторического AR.
CATEGORY_ORDER = ("photographs", "maps", "plans", "postcards")


class PolonaCollector(BaseCollector):
    source_name = "polona"
    base_url = "https://polona.pl"

    async def scrape(self) -> list[dict]:
        assets: list[dict] = []
        for category in CATEGORY_ORDER:
            if len(assets) >= self.limit:
                break
            page_assets = await self._search_category(category)
            assets.extend(page_assets)
            if page_assets:
                logger.info(
                    "[polona] категория %r: +%d ассетов (всего %d/%d)",
                    category, len(page_assets), len(assets), self.limit,
                )
        return assets[: self.limit]

    async def _search_category(self, category: str) -> list[dict]:
        """Обход одной категории Polona с пагинацией через `from`."""
        assets: list[dict] = []
        offset = 0

        while len(assets) < self.limit:
            params = {
                "query": self.query,
                "from": offset,
                "limit": ROWS,
                "filters": f"category:{category}",
            }
            data = await self._fetch_json(API, params=params)
            if not data:
                break
            text = str(data)[:2000]
            if is_bot_block(text):
                logger.warning("[polona] API заблокировало запрос (антибот)")
                break

            hits = data.get("hits") or []
            hits_count = data.get("hits_count") or 0
            logger.info(
                "[polona] %r: страница %d (%d хитов, всего: %d)",
                category, offset // ROWS + 1, len(hits), hits_count,
            )
            for hit in hits:
                asset = self._parse_hit(hit, category)
                if asset and self._accepts(asset):
                    assets.append(asset)
                    if len(assets) >= self.limit:
                        break

            if not hits:
                break
            offset += len(hits)
            if offset >= hits_count:
                break
            await asyncio.sleep(1)  # вежливая пауза между страницами API

        return assets

    def _parse_hit(self, hit: dict, category: str) -> dict | None:
        main_scan = hit.get("main_scan") or {}
        scan_id = main_scan.get("id")
        uid = hit.get("academica_id")
        if not scan_id or not uid:
            logger.debug("[polona] хит %s без main_scan/academica_id — пропуск",
                         hit.get("id"))
            return None

        title = limit_text(hit.get("title") or "", 300)
        if not title:
            title = hit.get("slug") or f"Polona {hit.get('id')}"

        # Год: метаданные → описательное поле → тематический период → regex
        year = extract_year(
            extract_year_iso(hit.get("date")),
            hit.get("date_descriptive"),
            str(hit.get("subject_time") or ""),
        )
        if not year:
            year = extract_year(
                title,
                hit.get("imprint"),
                hit.get("physical_description"),
            )

        description_parts = [
            str(p) for p in (
                hit.get("physical_description"),
                hit.get("imprint"),
            ) if p
        ]
        creator = hit.get("creator")
        if isinstance(creator, list):
            creator = ", ".join(str(c) for c in creator if c)
        if creator:
            description_parts.append(f"Автор: {creator}")
        description = limit_text(" · ".join(description_parts), 400)

        thumbnails = main_scan.get("thumbnails") or []
        thumbnail_url = ""
        for t in reversed(thumbnails):  # самый большой вариант
            url = t.get("url")
            if url:
                thumbnail_url = url
                break
        if not thumbnail_url:
            thumbnail_url = ARCHIVE + (
                f"?uid={uid}&cid={scan_id}&name=download_thumbnail"
            )

        item_url = (hit.get("links") or {}).get("item_url") or ""
        if not item_url:
            item_url = f"{ITEM_BASE}{hit.get('slug')},{hit.get('id')}/"

        return {
            "title": title,
            "source_url": item_url,
            "file_url": f"{ARCHIVE}?uid={uid}&cid={scan_id}&name=download_fullJPG",
            "thumbnail_url": thumbnail_url,
            "description": description,
            "year": year,
            "source": self.source_name,
            "file_type": "jpg",
            "tags": self._tags(hit, category),
            "width": self._scan_dimension(main_scan),
            "height": self._scan_dimension(main_scan, height=True),
        }

    @staticmethod
    def _scan_dimension(main_scan: dict, height: bool = False) -> int | None:
        """Ширина/высота главного скана из thumbnails (если указана)."""
        thumbnails = main_scan.get("thumbnails") or []
        for t in reversed(thumbnails):
            dims = (t.get("dimensions") or {})
            value = dims.get("height") if height else dims.get("width")
            if isinstance(value, (int, float)):
                return int(value)
        return None

    @staticmethod
    def _tags(hit: dict, category: str) -> list[str]:
        tags = []
        for key in ("metatypes", "categories", "form_and_type"):
            value = hit.get(key)
            values = value if isinstance(value, list) else [value]
            for v in values:
                if not isinstance(v, str) or not v:
                    continue
                for part in v.split(","):
                    part = part.strip()
                    if part and part not in tags:
                        tags.append(part)
        for value in (hit.get("subject") or [])[:6]:
            if isinstance(value, str) and value:
                tags.append(value)
        if category not in tags:
            tags.append(category)
        return tags[:12]
