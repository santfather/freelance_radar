"""Коллектор Gallica — Национальная библиотека Франции (SRU-API).

6+ млн документов: гравюры, карты, рукописи, планы зданий и городов.
Протокол SRU 1.2 (`https://gallica.bnf.fr/SRU`), запросы в CQL:

- `gallica all "query"` — поиск по всем полям;
- `dc.type any image / carte / manuscrit` — только изображения, карты, рукописи;
- `dc.date >= "1701" and dc.date <= "1800"` или `century adj "18"` —
  серверная фильтрация по периоду.

Файлы отдаются через IIIF:
- полный размер `https://gallica.bnf.fr/iiif/<ark>/f0/full/2000,/0/native.jpg`
  (вариант `full/max` нестабилен — обрывается, поэтому используем 2000px);
- миниатюра `.../f0/full/!512,512/0/native.jpg`.

Открытый API без ключа; требует браузерный User-Agent и `suggest=0`.
"""

import asyncio
import logging
import re

from bs4 import BeautifulSoup

from collectors.base_collector import BaseCollector
from collectors.utils import extract_year, extract_year_iso, limit_text

logger = logging.getLogger("freelance-radar.collector.gallica")

SRU = "https://gallica.bnf.fr/SRU"
BASE = "https://gallica.bnf.fr"
IIIF = "https://gallica.bnf.fr/iiif/ark:/12148"
MAX_RECORDS = 50  # максимальный размер страницы SRU

# Типы Gallica, релевантные историческим материалам (изображения/карты/рукописи)
_TYPE_CLAUSE = (
    '(dc.type any "image" or dc.type any "carte" '
    'or dc.type any "manuscrit" or dc.type any "objet")'
)


def _local(tag) -> str:
    """Локальное имя тега без namespace-префикса ('dc:title' → 'title')."""
    name = getattr(tag, "name", "") or ""
    return name.split(":")[-1]


class GallicaCollector(BaseCollector):
    source_name = "gallica"
    base_url = BASE

    # ── Поиск ───────────────────────────────────────────────────────────────

    def _build_query(self, query: str) -> str:
        """CQL-запрос: запрос + тип + период (если задан)."""
        parts = [f'gallica all "{query}"', _TYPE_CLAUSE]
        if self._period_active:
            if self.year_from is not None and self.year_to is not None:
                parts.append(
                    f'(dc.date >= "{self.year_from}" and dc.date <= "{self.year_to}")'
                )
            elif self.year_from is not None:
                parts.append(f'(dc.date >= "{self.year_from}")')
            elif self.year_to is not None:
                parts.append(f'(dc.date <= "{self.year_to}")')
        return " and ".join(parts)

    async def scrape(self) -> list[dict]:
        assets = await self._scrape_query(self.query)
        if not assets and self.fallback_query:
            logger.info("[gallica] пусто по запросу %r — пробую фолбэк %r",
                        self.query, self.fallback_query)
            assets = await self._scrape_query(self.fallback_query)
        return assets

    async def _scrape_query(self, query: str) -> list[dict]:
        assets: list[dict] = []
        start = 1
        query_cql = self._build_query(query)
        logger.info("[gallica] SRU-запрос: %s", query_cql)

        while len(assets) < self.limit:
            params = {
                "operation": "searchRetrieve",
                "version": "1.2",
                # Gallica отвечает 500 на «сырой» запрос без CQL-обёртки
                # (например, query=Stare Miasto Warszawa), поэтому отправляем
                # полный CQL: gallica all "..." and (dc.type any ...) and ...
                "query": query_cql,
                "startRecord": start,
                "maximumRecords": min(MAX_RECORDS, max(self.limit, 20)),
                "suggest": 0,
                "collapsing": "false",
            }
            soup = await self._fetch_xml(SRU, params=params)
            if soup is None:
                logger.warning("[gallica] нет ответа SRU — источник пропускается")
                break

            records = [el for el in soup.find_all() if _local(el) == "record"]
            if not records:
                # пустой ответ / страница проверки безопасности
                text = soup.get_text(" ", strip=True)[:200]
                if "vérification" in text.lower() or "access interdit" in text.lower():
                    logger.warning("[gallica] WAF/антибот-заглушка вместо SRU")
                else:
                    logger.info("[gallica] записей не найдено")
                break

            logger.info("[gallica] страница %d: %d записей", start, len(records))
            for record in records:
                asset = self._parse_record(record)
                if asset and self._accepts(asset):
                    assets.append(asset)
                    if len(assets) >= self.limit:
                        break

            if len(records) < min(MAX_RECORDS, max(self.limit, 20)):
                break
            start += len(records)
            await asyncio.sleep(1)  # вежливая пауза между страницами

        return assets

    # ── Разбор записи ───────────────────────────────────────────────────────

    def _parse_record(self, record) -> dict | None:
        """Запись SRU (Dublin Core) → ассет."""
        def field(name: str) -> str:
            for el in record.find_all():
                if _local(el) == name:
                    text = el.get_text(" ", strip=True)
                    if text:
                        return text
            return ""

        identifier = field("identifier")
        # Ссылки-сироты (не на gallica.bnf.fr/ark:) не дают IIIF-файла
        ark_match = re.search(r"/ark:/12148/([^/?#\s]+)", identifier)
        if not ark_match:
            logger.debug("[gallica] запись без ark — пропуск")
            return None

        title = limit_text(field("title") or self.query, 300)
        description = limit_text(field("description"), 400)
        if not description:
            description = limit_text(field("source"), 200)
        creator = field("creator")
        if creator:
            description = f"{description} — {creator}" if description else creator
        subject = field("subject")
        if subject and subject not in description:
            description = f"{description} — {subject}" if description else subject

        # Год: метаданные (dc:date) → описание → заголовок
        year = extract_year(extract_year_iso(field("date")), field("coverage"))
        if not year:
            year = extract_year(description, title)

        ark_id = ark_match.group(1)
        return {
            "title": title,
            "source_url": f"https://gallica.bnf.fr/ark:/12148/{ark_id}",
            "file_url": f"{IIIF}/{ark_id}/f0/full/2000,/0/native.jpg",
            "thumbnail_url": f"{IIIF}/{ark_id}/f0/full/!512,512/0/native.jpg",
            "description": description,
            "year": year,
            "source": self.source_name,
            "file_type": "jpg",
        }
