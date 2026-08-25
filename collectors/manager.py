"""Менеджер коллекторов: запуск сбора по объекту, сохранение в БД, оптимизация.

Оркестрирует коллекторы из `COLLECTOR_REGISTRY`, объединяет результаты
(с дедупликацией по `file_url`), сохраняет исторический объект и ассеты в
SQLite, а затем через `MediaOptimizer` скачивает и готовит версии файла:

- `assets/archive/<city>/<slug>/<year>_<id>_original.<ext>`
- `assets/production/<city>/<slug>/<year>_<id>_optimized.jpg`
- `assets/thumbnails/<city>/<slug>/<year>_<id>_thumb.jpg`

Режим `--mode photogrammetry` (`mode="photogrammetry"`):
- лимит поднимается до 50–100 файлов на объект;
- сохраняются оригиналы, оптимизированная 2048px-версия не создаётся;
- фильтр по разрешению ≥ 2000 px по большей стороне (где известно);
- приоритет высококачественным источникам (Europeana, Wikimedia, Muzeum Warszawy);
- файлы группируются по тегам (ракурсы).
"""

import asyncio
import logging
import os
import re

from collectors.optimizer import MediaOptimizer
from collectors.utils import (
    century_era,
    coerce_year,
    detect_material_type,
)
from database import (
    get_asset,
    mark_asset_error,
    update_object_era,
    upsert_asset,
    upsert_historical_object,
    update_asset_paths,
)

logger = logging.getLogger("freelance-radar.collector.manager")

ASSETS_ROOT = os.getenv("ASSETS_ROOT", "assets")

# Приоритет источников в режиме photogrammetry (меньше — лучше).
PHOTOGRAMMETRY_SOURCE_ORDER = [
    "europeana",
    "wikimedia",
    "muzeum_warszawy",
    "polona",
    "nac",
    "szukajwarchiwach",
    "lookandlearn",
]

# Порог по большей стороне для «фотограмметрически готовых» изображений.
PHOTOGRAMMETRY_MIN_SIDE = 2000

# Алиасы городов для структуры папок assets/<city>/<slug>/
CITY_ALIASES: dict[str, tuple[str, ...]] = {
    "warsaw": ("warsaw", "warszawa", "varsovie"),
    "krakow": ("krakow", "kraków", "cracow"),
    "gdansk": ("gdansk", "gdańsk", "danzig"),
    "wroclaw": ("wroclaw", "wrocław", "breslau"),
    "poznan": ("poznan", "poznań"),
    "lodz": ("lodz", "łódź"),
    "lublin": ("lublin",),
    "katowice": ("katowice",),
    "prague": ("prague", "praha", "praga"),
    "berlin": ("berlin",),
    "vienna": ("vienna", "wien", "wiedeń"),
    "paris": ("paris", "paryż"),
    "london": ("london",),
    "kyiv": ("kyiv", "kiev", "kijów"),
    "vilnius": ("vilnius", "wilno"),
    "riga": ("riga", "ryga"),
    "stockholm": ("stockholm", "sztokholm"),
    "moscow": ("moscow", "moskwa"),
    "stpetersburg": ("st petersburg", "sankt-petersburg", "saint-petersburg", "petersburg"),
    "budapest": ("budapest", "budapeszt"),
}

# Фолбэк-запросы для источников, которые ищут на своём языке: по названию
# объекта (на польском) они могут не найти ничего, поэтому при пустом
# результате коллектор повторяет поиск по запросу на языке источника.
# Ключ — город (slug), значение — source → query.
CITY_SEARCH_QUERIES: dict[str, dict[str, str]] = {
    "warsaw": {
        "metmuseum": "Warsaw",
        "gallica": "Varsovie",
    },
}

_TRANSLIT = str.maketrans({
    "ą": "a", "ć": "c", "ę": "e", "ł": "l", "ń": "n",
    "ó": "o", "ś": "s", "ź": "z", "ż": "z",
    "ü": "u", "ö": "o", "ä": "a", "ß": "ss", "é": "e",
})


def slugify(text: str) -> str:
    """Транслитерация и нормализация строки до безопасного слага."""
    text = text.lower().translate(_TRANSLIT)
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return text.strip("_") or "unknown"


def detect_city(query: str) -> str:
    """Определить город из названия объекта (для структуры папок)."""
    lowered = query.lower()
    for city, aliases in CITY_ALIASES.items():
        for alias in aliases:
            if alias in lowered:
                return city
    return "unknown"


def _to_int_year(value) -> int | None:
    """Привести строку/число к целому году (1000–2099) или None."""
    return coerce_year(value)


class CollectorManager:
    """Запускает коллекторы, сохраняет результаты и оптимизирует файлы."""

    def __init__(self, object_name: str, sources: list[str] | None = None,
                 limit: int = 20, era: str = "", latitude: float | None = None,
                 longitude: float | None = None, description: str = "",
                 city: str = "", mode: str = "general",
                 year_from: int | None = None, year_to: int | None = None,
                 century: int | None = None):
        self.object_name = object_name.strip()
        self.city = (city or "").strip() or detect_city(self.object_name)
        self.slug = slugify(self.object_name)
        self.sources = [s.lower() for s in (sources or [])]
        self.mode = (mode or "general").strip().lower()
        if self.mode == "photogrammetry":
            # 50–100 файлов на объект для построения 3D-модели
            self.limit = max(50, min(int(limit), 100))
        else:
            self.limit = max(1, min(int(limit), 200))
        self.era = era or ""
        self.latitude = latitude
        self.longitude = longitude
        self.description = description or ""
        self.log: list[str] = []
        self.errors: list[str] = []

        # Период сбора: century преобразуется в диапазон годов
        # (18 → 1701–1800); явные year_from/year_to имеют приоритет.
        if century:
            century = int(century)
            if year_from is None:
                year_from = (century - 1) * 100 + 1
            if year_to is None:
                year_to = century * 100
        self.year_from = coerce_year(year_from)
        self.year_to = coerce_year(year_to)
        self.century = century

    @property
    def output_dir(self) -> str:
        return os.path.join(ASSETS_ROOT, self.city, self.slug)

    @property
    def _photogrammetry(self) -> bool:
        return self.mode == "photogrammetry"

    # ── Основной запуск ──────────────────────────────────────────────────────

    async def run(self) -> dict:
        period = "весь период"
        if self.year_from or self.year_to:
            period = f"{self.year_from or '…'}–{self.year_to or '…'}"
        self.log.append(
            f"▶ Сбор для «{self.object_name}» (город: {self.city}, "
            f"источники: {', '.join(self.sources) or 'all'}, "
            f"лимит: {self.limit}, режим: {self.mode}, период: {period})"
        )

        object_id = await upsert_historical_object(
            self.object_name,
            latitude=self.latitude,
            longitude=self.longitude,
            description=self.description,
            era=self.era,
            city=self.city,
            slug=self.slug,
        )

        # Ленивый импорт: реестр собирается в collectors/__init__.py
        from collectors import COLLECTOR_REGISTRY

        raw: list[dict] = []
        for source in self.sources:
            cls = COLLECTOR_REGISTRY.get(source)
            if cls is None:
                self.errors.append(f"Неизвестный источник: {source}")
                continue
            fallback = CITY_SEARCH_QUERIES.get(self.city.lower(), {}).get(source, "")
            collector = cls(
                query=self.object_name,
                limit=self.limit,
                year_from=self.year_from,
                year_to=self.year_to,
                fallback_query=fallback,
            )
            try:
                assets = await collector.scrape()
            except Exception as e:
                self.errors.append(f"[{source}] ошибка сбора: {e}")
                logger.exception("[%s] сбор завершился с ошибкой", source)
                continue
            self.log.append(f"✓ {source}: найдено {len(assets)} файлов")
            raw.extend(assets)

        unique = self._dedupe(raw)
        if self._photogrammetry:
            unique = self._photogrammetry_filter(unique)
            unique.sort(key=self._source_priority)
        # Тип материала (photo/painting/print/map/drawing/unknown) — по ключевым
        # словам в title/description с дефолтом по источнику.
        for asset in unique:
            if not asset.get("material_type"):
                asset["material_type"] = detect_material_type(
                    asset.get("source"),
                    asset.get("title"),
                    asset.get("description"),
                )
        by_source: dict[str, int] = {}
        for asset in unique:
            src = asset.get("source") or "?"
            by_source[src] = by_source.get(src, 0) + 1
        self.log.append(f"💾 Уникальных материалов: {len(unique)}")

        downloaded, failed = await self._process_assets(object_id, unique)
        self.log.append(f"💾 Сохранено в БД (object_id={object_id})")
        self.log.append(f"⬇ Скачано и оптимизировано файлов: {downloaded}"
                        + (f", ошибок: {failed}" if failed else ""))

        era = self._auto_era(unique)
        if era:
            await update_object_era(object_id, era)
            self.log.append(f"📅 era (авто): {era}")

        return {
            "object_id": object_id,
            "object_name": self.object_name,
            "city": self.city,
            "slug": self.slug,
            "mode": self.mode,
            "era": era,
            "collected": len(unique),
            "downloaded": downloaded,
            "by_source": by_source,
            "errors": self.errors,
            "log": self.log,
        }

    # ── Сухой прогон (--dry-run) ─────────────────────────────────────────────

    async def preview(self) -> dict:
        """Сухой прогон: поиск (scrape) без сохранения в БД и скачивания.

        Возвращает число уникальных ассетов и их разбивку по источникам —
        для оценки объёма сбора перед реальным запуском.
        """
        from collectors import COLLECTOR_REGISTRY

        raw: list[dict] = []
        errors: list[str] = []
        for source in self.sources:
            cls = COLLECTOR_REGISTRY.get(source)
            if cls is None:
                errors.append(f"Неизвестный источник: {source}")
                continue
            fallback = CITY_SEARCH_QUERIES.get(self.city.lower(), {}).get(source, "")
            collector = cls(
                query=self.object_name,
                limit=self.limit,
                year_from=self.year_from,
                year_to=self.year_to,
                fallback_query=fallback,
            )
            try:
                assets = await collector.scrape()
            except Exception as e:
                errors.append(f"[{source}] ошибка сбора: {e}")
                logger.exception("[%s] сбор завершился с ошибкой (preview)", source)
                continue
            raw.extend(assets)

        unique = self._dedupe(raw)
        by_source: dict[str, int] = {}
        for asset in unique:
            src = asset.get("source") or "?"
            by_source[src] = by_source.get(src, 0) + 1
        return {"collected": len(unique), "by_source": by_source, "errors": errors}

    @staticmethod
    def _dedupe(assets: list[dict]) -> list[dict]:
        seen: set[str] = set()
        unique: list[dict] = []
        for asset in assets:
            key = asset.get("file_url") or asset.get("source_url")
            if not key or key in seen:
                continue
            seen.add(key)
            unique.append(asset)
        return unique

    # ── Логика режима photogrammetry ────────────────────────────────────────

    @staticmethod
    def _source_priority(asset: dict) -> int:
        """Ранг приоритета источника: меньше значение — выше приоритет."""
        source = (asset.get("source") or "").lower()
        if source in PHOTOGRAMMETRY_SOURCE_ORDER:
            return PHOTOGRAMMETRY_SOURCE_ORDER.index(source)
        return len(PHOTOGRAMMETRY_SOURCE_ORDER)

    @staticmethod
    def _photogrammetry_filter(assets: list[dict]) -> list[dict]:
        """Оставить изображения ≥ 2000 px по большей стороне.

        Если размеры в метаданных неизвестны — ассет не отбрасываем
        (разрешение будет проверено при скачивании через original_width).
        """
        kept: list[dict] = []
        for asset in assets:
            width = asset.get("width")
            height = asset.get("height")
            if isinstance(width, (int, float)) and isinstance(height, (int, float)):
                if max(width, height) >= PHOTOGRAMMETRY_MIN_SIDE:
                    kept.append(asset)
            else:
                kept.append(asset)
        return kept

    def _auto_era(self, assets: list[dict]) -> str:
        """Вычислить era как диапазон веков римскими цифрами.

        Например, ассеты 1450, 1550, 1600 → "XV–XVII вв.", один век — "XVI в.".
        Если ничего не найдено — вернуть пустую строку.
        """
        if not assets:
            return ""
        years = [
            y for a in assets if (y := _to_int_year(a.get("year"))) is not None
        ]
        return century_era(years)

    # ── Скачивание и оптимизация ────────────────────────────────────────────

    async def _process_assets(self, object_id: int, assets: list[dict]) -> tuple[int, int]:
        """Для каждого ассета: сохранить в БД → скачать/оптимизировать."""
        downloaded = 0
        failed = 0

        for num, asset in enumerate(assets, start=1):
            # Метаданные для MediaOptimizer и структуры папок
            asset_data = dict(asset)
            asset_data["city"] = self.city
            asset_data["slug"] = self.slug

            asset_id = await upsert_asset(object_id, asset_data)
            if not asset_id:
                self.errors.append(
                    f"[{asset.get('source')}] не удалось сохранить ассет в БД"
                )
                failed += 1
                continue

            # Файл уже обработан ранее — не качаем повторно
            existing = await get_asset(asset_id)
            if existing and existing.get("downloaded"):
                existing_path = (
                    existing.get("original_path")
                    or existing.get("local_path")
                    or ""
                )
                if existing_path and os.path.exists(existing_path):
                    downloaded += 1
                    continue

            file_url = asset.get("file_url", "")
            if not file_url:
                continue

            processed = await MediaOptimizer.process(
                file_url=file_url,
                asset_data=asset_data,
                output_dir=ASSETS_ROOT,
                asset_id=asset_id,
                skip_optimization=self._photogrammetry,
                prefer_original=self._photogrammetry,
            )

            if processed.get("error"):
                self.errors.append(
                    f"[{asset.get('source')}] {file_url}: {processed['error']}"
                )
                await mark_asset_error(asset_id, processed["error"])
                failed += 1
                await asyncio.sleep(0.5)
                continue

            await update_asset_paths(asset_id, processed)
            if processed.get("downloaded"):
                downloaded += 1
            self.log.append(
                f"  ⬇ {os.path.basename(processed['original_path'])} "
                f"({asset.get('source')})"
            )
            # вежливая пауза между скачиваниями (Wikimedia 429 при частых запросах)
            await asyncio.sleep(3)

        return downloaded, failed
