"""Коллектор Europeana.eu — официальный REST API.

Использует Record API v2: `https://api.europeana.eu/record/v2/search.json`
с параметрами `query`, `wskey` (ключ из `EUROPEANA_API_KEY`), `profile=rich`
и `reusability=open` (только свободно доступные материалы).

Из каждого элемента извлекаются `edmIsShownBy` (прямая ссылка на файл),
`edmPreview` (миниатюра), `title`, `dcDescription`, `year`. Пагинация —
курсорная (`cursor` из ответа), с фолбэком на числовой `start`.

Ключ можно получить бесплатно: https://pro.europeana.eu/page/get-api-key
Квота: 1 000 запросов/сутки (уведомляем в логе при приближении к лимиту —
контролируется не API, а собственным счётчиком).
"""

import asyncio
import logging
import os

from collectors.base_collector import BaseCollector
from collectors.utils import extract_year, extract_year_iso, limit_text

logger = logging.getLogger("freelance-radar.collector.europeana")

API = "https://api.europeana.eu/record/v2/search.json"
BASE = "https://www.europeana.eu"
DEFAULT_ROWS = 50

# Предел запросов к API, после которого начинаем предупреждать (квота ~1000/день)
QUOTA_WARN_THRESHOLD = 900


class EuropeanaCollector(BaseCollector):
    source_name = "europeana"
    base_url = BASE

    def __init__(self, query: str, limit: int = 20, language: str = "pl",
                 timeout: int = 30, delay: tuple = (1, 3),
                 year_from: int | None = None, year_to: int | None = None):
        super().__init__(query=query, limit=limit, timeout=timeout, delay=delay,
                         year_from=year_from, year_to=year_to)
        self.language = language or ""
        self.api_key = os.getenv("EUROPEANA_API_KEY", "").strip()
        self._api_calls = 0

    async def scrape(self) -> list[dict]:
        if not self.api_key:
            logger.warning(
                "[europeana] EUROPEANA_API_KEY не задан в .env — пропуск источника. "
                "Получите бесплатный ключ: https://pro.europeana.eu/page/get-api-key"
            )
            return []

        assets: list[dict] = []
        cursor = "*"
        qf_clauses = self._qf_clauses()
        params_base = {
            "query": self.query,
            "wskey": self.api_key,
            "profile": "rich",
            "rows": min(DEFAULT_ROWS, self.limit),
            "reusability": "open",
        }
        if qf_clauses:
            # Серверная фильтрация по языку и году (повторяющийся параметр qf)
            params_base["qf"] = qf_clauses

        while len(assets) < self.limit:
            if self._api_calls >= QUOTA_WARN_THRESHOLD:
                logger.warning(
                    "[europeana] приближение к дневной квоте запросов "
                    "(%d/%d) — следующие сбои могут быть из-за лимита",
                    self._api_calls, QUOTA_WARN_THRESHOLD + 100,
                )

            params = dict(params_base)
            if cursor and cursor != "*":
                params["cursor"] = cursor
            else:
                params["cursor"] = cursor  # первый запрос тоже курсором

            data = await self._fetch_json(API, params=params)
            if not data:
                break

            # Обработка ошибок API (квоты, лимиты, неверный ключ)
            if data.get("success") is False:
                logger.warning(
                    "[europeana] ошибка API: %s (код %s)",
                    data.get("error"), data.get("apikey", ""),
                )
                break
            if data.get("apikey") == "anonymous":
                logger.warning(
                    "[europeana] ключ не распознан API — проверьте EUROPEANA_API_KEY"
                )
                break

            items = data.get("items") or []
            self._api_calls += 1
            logger.info(
                "[europeana] страница: %d элементов по запросу %r "
                "(всего результатов: %s)",
                len(items), self.query, data.get("totalResults", 0),
            )
            for item in items:
                asset = self._parse_item(item)
                if asset:
                    assets.append(asset)
                    if len(assets) >= self.limit:
                        break

            total = int(data.get("totalResults", 0) or 0)
            next_cursor = data.get("nextCursor", "")
            if not next_cursor or not items:
                break
            if total and len(assets) >= min(total, self.limit):
                break
            cursor = next_cursor
            # вежливая пауза между запросами к API
            await asyncio.sleep(1)

        return self._filter_by_period(assets)

    def _qf_clauses(self) -> list[str]:
        """Фильтры по языку и году для параметра qf (YEAR-индекс Europeana).

        Поддерживаемые формы: `qf=YEAR:1900*` (префикс) и
        `qf=YEAR:[1500 TO 1800]` (диапазон). Метadata YEAR может содержать
        приблизительные значения, поэтому после сбора применяется ещё и
        постфильтрация по извлечённому году.
        """
        clauses: list[str] = []
        if self.language:
            clauses.append(f"LANGUAGE:{self.language}")
        if self._period_active:
            year_from = self.year_from or 1000
            year_to = self.year_to or 2100
            clauses.append(f"YEAR:[{year_from} TO {year_to}]")
        return clauses

    def _parse_item(self, item: dict) -> dict | None:
        file_url = self._first(item, "edmIsShownBy") or self._first(item, "edmObject")
        if not file_url:
            logger.debug("[europeana] элемент без прямой ссылки на файл — пропуск")
            return None

        title = self._first(item, "title") or ""
        if isinstance(title, str) and title.startswith("http"):
            title = self._first(item, "dcTitle") or ""

        description = limit_text(
            " ".join(s for s in (item.get("dcDescription") or []) if isinstance(s, str))
        )
        if not description:
            provider = " ".join(
                s for s in (item.get("dataProvider") or []) if isinstance(s, str)
            )
            description = f"Источник: {provider}" if provider else ""

        year = extract_year(
            self._first(item, "year"),
            extract_year_iso(self._first(item, "edmTimespanLabel", "")),
        )
        if not year:
            # из названий/описания как последний резерв
            year = extract_year(title, description)

        source_url = self._first(item, "edmLandingPage")
        if not source_url:
            item_id = self._first(item, "id")
            source_url = f"{BASE}/en/item/{item_id}" if item_id else ""

        return {
            "title": title,
            "source_url": source_url,
            "file_url": file_url,
            "thumbnail_url": self._first(item, "edmPreview") or "",
            "description": description,
            "year": year,
            "source": self.source_name,
            "file_type": self._file_type(file_url),
            "tags": self._tags(item),
        }

    @staticmethod
    def _tags(item: dict) -> list[str]:
        """Теги из ключевых слов/тем — для группировки по ракурсам."""
        tags = []
        for key in ("dcSubject", "dcType"):
            for value in item.get(key) or []:
                if isinstance(value, str) and value:
                    tags.append(value)
        return tags[:8]

    @staticmethod
    def _first(item: dict, key: str, default: str = "") -> str:
        value = item.get(key)
        if isinstance(value, list):
            value = value[0] if value else default
        return value if isinstance(value, str) else default

    @staticmethod
    def _file_type(url: str) -> str:
        from collectors.optimizer import ext_from_url

        ext = ext_from_url(url)
        return ext if ext else "jpg"
