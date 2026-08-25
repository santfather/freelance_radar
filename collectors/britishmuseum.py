"""Коллектор British Museum — 1,9 млн объектов (гравюры, рисунки, карты).

⚠️ Статус источника (проверено 2026-08-04): публичного REST API «по ключу»
у British Museum **не существует** — документация описывает только SPARQL-
эндпоинт linked-data `http://collection.britishmuseum.org/sparql`
(бесплатный, без ключа). Эндпоинт на момент проверки недоступен (таймаут).

Поэтому коллектор реализован по этому реальному контракту (SPARQL → JSON):
- поиск объектов с `rdfs:label`, содержащим запрос;
- год извлекается из label/description и фильтруется постфильтрацией;
- ссылка на изображение — через `crm:P138i_has_representation`.

При недоступности эндпоинта коллектор корректно завершается с пустым
результатом и пояснением в `errors` (не маскируем недоступность), как и
коллекторы nac/szukajwarchiwach. Если BM откроет REST API — обновится только
`scrape()`.

Псевдоним `BRITISH_MUSEUM_API_KEY` в `.env` зарезервирован на случай
появления ключевого доступа, но сейчас не используется.
"""

import logging
from urllib.parse import quote

from collectors.base_collector import BaseCollector
from collectors.utils import extract_year, limit_text

logger = logging.getLogger("freelance-radar.collector.britishmuseum")

SPARQL_ENDPOINT = "http://collection.britishmuseum.org/sparql"
BASE = "https://www.britishmuseum.org"

# Граф объекта: CIDOC-CRM. Объекты — E22, представления (изображения) — E38.
_PREFIXES = """
PREFIX crm: <http://www.cidoc-crm.org/cidoc-crm/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
"""


class BritishMuseumCollector(BaseCollector):
    source_name = "britishmuseum"
    base_url = "https://collection.britishmuseum.org"

    def _build_query(self) -> str:
        """SPARQL: объекты, у которых label содержит запрос (case-insensitive)."""
        limit = max(self.limit, 50)
        return f"""{_PREFIXES}
SELECT DISTINCT ?object ?label ?image WHERE {{
  ?object a crm:E22_Human-Made_Object .
  ?object rdfs:label ?label .
  OPTIONAL {{ ?object crm:P138i_has_representation ?image . }}
  FILTER(CONTAINS(LCASE(STR(?label)), {quote(self.query.lower(), safe="")}))
}}
LIMIT {limit}"""

    async def scrape(self) -> list[dict]:
        data = await self._fetch_json(
            SPARQL_ENDPOINT,
            params={
                "query": self._build_query(),
                "format": "application/sparql-results+json",
            },
            headers={"Accept": "application/json"},
        )
        if not data:
            logger.warning(
                "[britishmuseum] SPARQL-эндпоинт недоступен/пустой ответ — "
                "источник пропускается. Публичного REST API у BM нет, "
                "см. комментарий в britishmuseum.py."
            )
            return []

        bindings = ((data.get("results") or {}).get("bindings") or [])
        logger.info("[britishmuseum] SPARQL: найдено %d объектов", len(bindings))

        assets: list[dict] = []
        for binding in bindings:
            if len(assets) >= self.limit:
                break
            asset = self._parse_binding(binding)
            if asset and self._accepts(asset):
                assets.append(asset)
        return assets

    def _parse_binding(self, binding: dict) -> dict | None:
        """Одна SPARQL-строка (объект, label, изображение) → ассет."""
        def literal(var: str) -> str:
            value = (binding.get(var) or {}).get("value", "")
            return str(value)

        uri = literal("object")
        title = limit_text(literal("label"), 300)
        if not title:
            return None

        image_url = literal("image")
        file_url = image_url
        thumbnail_url = image_url
        if image_url and not image_url.startswith("http"):
            # может прийти относительный путь к изображению
            file_url = self._abs_url(image_url)
            thumbnail_url = file_url

        year = extract_year(title)
        description = f"British Museum. Источник: {uri}" if uri else ""

        return {
            "title": title,
            "source_url": uri or f"{BASE}/collection",
            "file_url": file_url or "",
            "thumbnail_url": thumbnail_url or "",
            "description": description,
            "year": year,
            "source": self.source_name,
            "file_type": "jpg",
        }
