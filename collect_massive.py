#!/usr/bin/env python3
"""Массовый сбор исторических материалов по всем объектам Варшавы.

Проходит по объектам (по умолчанию — уже существующим в БД, fallback — списку
OBJECTS ниже) последовательно и для каждого вызывает CollectorManager
(источники только из числа проверенно работающих: wikimedia, metmuseum,
gallica, muzeum_warszawy; никаких API-ключей не требуется). После сбора —
пост-обработка:

  1. backfill_era()         — заполнить поле era (диапазон веков) по годам ассетов;
  2. update_coordinates.py  — проставить недостающие координаты;
  3. regenerate_thumbnails.py — перегенерировать миниатюры;
  4. export_to_json.py      — собрать итоговый JSON-дамп export/historical_data.json.

Повторный запуск безопасен: ассеты дедуплицируются по file_url, уже скачанные
файлы не качаются повторно. `--dry-run` позволяет оценить объём сбора без
записи в БД и без скачивания файлов.

Запуск:
    .venv/bin/python collect_massive.py                        # полный сбор
    .venv/bin/python collect_massive.py --dry-run              # оценка объёма
    .venv/bin/python collect_massive.py --limit 50             # лимит 50 на источник
    .venv/bin/python collect_massive.py --only "Zamek Królewski"
    .venv/bin/python collect_massive.py --skip-post            # только сбор, без пост-обработки
    .venv/bin/python collect_massive.py --resume               # пропустить объекты, уже скачанные >= limit
"""

import argparse
import asyncio
import logging
import os
import re
import sqlite3
import sys

from collectors.manager import CollectorManager
from database import (
    backfill_era,
    backfill_material_types,
    get_collect_stats,
    get_historical_object_by_name,
    list_historical_objects,
)
from export_to_json import export_to_json
from regenerate_thumbnails import regenerate_all_thumbnails
from update_coordinates import update_missing_coordinates

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("collect_massive")

# Не засорять лог прогресса внутренними HTTP-запросами httpx.
for noisy in ("httpx", "httpcore", "urllib3"):
    logging.getLogger(noisy).setLevel(logging.WARNING)

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.getenv("DB_PATH", os.path.join(PROJECT_ROOT, "radar.db"))
DEFAULT_LIMIT = 100
DEFAULT_YEAR_FROM = 1000
DEFAULT_YEAR_TO = 2024
DEFAULT_CITY = "Warsaw"

# Только проверенно работающие источники без API-ключей (2026-08-04).
# polona/nac/szukajwarchiwach/lookandlearn требуют переписывания на API,
# europeana/rijksmuseum/prometheus — ключи; britishmuseum закрыт SPARQL-таймаутами.
WORKING_SOURCES: list[str] = [
    "wikimedia",
    "metmuseum",
    "gallica",
    "muzeum_warszawy",
]

# Fallback-список объектов (используется, если в БД ещё нет ни одного объекта).
OBJECTS: list[dict] = [
    {"name": "Zamek Królewski", "city": "Warsaw", "lat": 52.2476, "lng": 21.0141},
    {"name": "Warszawa Stare Miasto", "city": "Warsaw", "lat": 52.2497, "lng": 21.0122},
    {"name": "Palac Kultury i Nauki", "city": "Warsaw", "lat": 52.2318, "lng": 21.0058},
    {"name": "Łazienki Królewskie", "city": "Warsaw", "lat": 52.2143, "lng": 21.0357},
    {"name": "Wilanów", "city": "Warsaw", "lat": 52.1656, "lng": 21.0893},
    {"name": "Uniwersytet Warszawski", "city": "Warsaw", "lat": 52.2406, "lng": 21.0192},
    {"name": "Krakowskie Przedmieście", "city": "Warsaw", "lat": 52.2424, "lng": 21.0159},
    {"name": "Plac Zamkowy", "city": "Warsaw", "lat": 52.2472, "lng": 21.0140},
    {"name": "Barbakan Warszawski", "city": "Warsaw", "lat": 52.2522, "lng": 21.0096},
    {"name": "Kościół św. Anny", "city": "Warsaw", "lat": 52.2441, "lng": 21.0147},
    {"name": "Ogród Saski", "city": "Warsaw", "lat": 52.2406, "lng": 21.0106},
    {"name": "Pałac Prezydencki", "city": "Warsaw", "lat": 52.2417, "lng": 21.0152},
    {"name": "Pomnik Chopina", "city": "Warsaw", "lat": 52.2149, "lng": 21.0252},
    {"name": "Cmentarz Powązkowski", "city": "Warsaw", "lat": 52.2526, "lng": 20.9726},
    {"name": "Warszawa Powiśle", "city": "Warsaw", "lat": 52.2322, "lng": 21.0294},
    {"name": "Warszawa Praga", "city": "Warsaw", "lat": 52.2583, "lng": 21.0463},
    {"name": "Most Poniatowskiego", "city": "Warsaw", "lat": 52.2372, "lng": 21.0399},
    {"name": "Dworzec Centralny", "city": "Warsaw", "lat": 52.2260, "lng": 21.0035},
    {"name": "Warszawa Ochota", "city": "Warsaw", "lat": 52.2158, "lng": 20.9773},
    {"name": "Warszawa Żoliborz", "city": "Warsaw", "lat": 52.2692, "lng": 20.9844},
    {"name": "Warszawa Mokotów", "city": "Warsaw", "lat": 52.1747, "lng": 21.0089},
    {"name": "Warszawa Wola", "city": "Warsaw", "lat": 52.2333, "lng": 20.9558},
    {"name": "Warszawa Bielany", "city": "Warsaw", "lat": 52.2922, "lng": 20.9376},
    {"name": "Warszawa Ursynów", "city": "Warsaw", "lat": 52.1392, "lng": 21.0594},
    {"name": "Warszawa Wesoła", "city": "Warsaw", "lat": 52.2531, "lng": 21.2222},
    {"name": "Muzeum Powstania Warszawskiego", "city": "Warsaw", "lat": 52.2325, "lng": 20.9824},
    {"name": "Stadion Narodowy", "city": "Warsaw", "lat": 52.2394, "lng": 21.0456},
    {"name": "Muzeum Narodowe w Warszawie", "city": "Warsaw", "lat": 52.2321, "lng": 21.0238},
    {"name": "Most Świętokrzyski", "city": "Warsaw", "lat": 52.2447, "lng": 21.0316},
    {"name": "Cytadela Warszawska", "city": "Warsaw", "lat": 52.2648, "lng": 20.9986},
]


def build_sources() -> list[str]:
    """Источники сбора — только работающие без API-ключей."""
    return list(WORKING_SOURCES)


async def load_target_objects() -> list[dict]:
    """Объекты для сбора: из БД (актуальные), иначе — статический список.

    Используем именно объекты из БД, чтобы гарантированно покрыть все 20
    существующих объектов Варшавы, включая добавленные вручную.
    """
    try:
        rows = await list_historical_objects(limit=500)
        if rows:
            return [
                {
                    "name": r["name"],
                    # city='unknown'/None — артефакт старых объектов: объекты
                    # списка находятся в Варшаве, поэтому нормализуем.
                    "city": _normalize_city(r.get("city")),
                    "lat": r.get("latitude"),
                    "lng": r.get("longitude"),
                }
                for r in rows
            ]
    except Exception as exc:
        logger.warning("Не удалось прочитать объекты из БД: %s", exc)
    return list(OBJECTS)


def _normalize_city(city: str | None) -> str:
    """Привести город из БД к нормализованному виду ('unknown'/None → Warsaw)."""
    city = (city or "").strip()
    if not city or city.lower() in {"unknown", "warszawa", "varsovie"}:
        return DEFAULT_CITY
    return city


async def _existing_coords(name: str) -> tuple[float | None, float | None]:
    """Координаты уже существующего объекта в БД (чтобы не затирать NULL-ом)."""
    try:
        row = await get_historical_object_by_name(name)
    except Exception:
        return None, None
    if not row:
        return None, None
    return row.get("latitude"), row.get("longitude")


async def _is_complete(name: str, limit: int) -> bool:
    """Проверить, что объект уже полностью собран (скачано >= limit)."""
    try:
        row = await get_historical_object_by_name(name)
        if not row:
            return False
        stats = await get_collect_stats(int(row["id"]))
        return stats.get("downloaded", 0) >= limit
    except Exception:
        return False


def _error_type(err: str) -> str:
    """Тип ошибки для группировки статистики: источник из '[source]', иначе 'other'."""
    m = re.search(r"\[([^\]]+)\]", err)
    return m.group(1) if m else "other"


async def collect_all(objects: list[dict], limit: int, sources: list[str],
                      mode: str = "general", year_from: int | None = None,
                      year_to: int | None = None, dry_run: bool = False,
                      resume: bool = False) -> dict:
    """Последовательный сбор всех объектов. Возвращает сводную статистику."""
    total_collected = 0
    total_downloaded = 0
    skipped = 0
    errors: list[str] = []
    empty: list[str] = []
    by_source: dict[str, int] = {}

    for i, obj in enumerate(objects, start=1):
        name = (obj.get("name") or "").strip()
        city = (obj.get("city") or DEFAULT_CITY).strip()

        # Докачка: в режиме --resume объекты, уже полностью скачанные, пропускаем.
        if resume and not dry_run and await _is_complete(name, limit):
            logger.info("[%d/%d] «%s» — уже скачано %d файлов, пропуск",
                        i, len(objects), name, limit)
            skipped += 1
            continue

        lat, lng = obj.get("lat"), obj.get("lng")
        if lat is None or lng is None:
            ex_lat, ex_lng = await _existing_coords(name)
            lat = lat if lat is not None else ex_lat
            lng = lng if lng is not None else ex_lng

        logger.info("[%d/%d] Сбор «%s» (city=%s, lat=%s, lng=%s)%s",
                    i, len(objects), name, city, lat, lng,
                    " [dry-run]" if dry_run else "")
        try:
            manager = CollectorManager(
                object_name=name,
                city=city,
                latitude=lat,
                longitude=lng,
                limit=limit,
                sources=list(sources),
                mode=mode,
                year_from=year_from,
                year_to=year_to,
            )
            if dry_run:
                result = await manager.preview()
                result["downloaded"] = 0
                result["by_source"] = result.get("by_source") or {}
            else:
                result = await manager.run()
        except Exception as exc:
            logger.error("  Ошибка при сборе для «%s»: %s", name, exc)
            errors.append(f"{name}: {exc}")
            continue

        collected = result.get("collected", 0)
        downloaded = result.get("downloaded", 0)
        total_collected += collected
        total_downloaded += downloaded
        for src, cnt in (result.get("by_source") or {}).items():
            by_source[src] = by_source.get(src, 0) + cnt
        logger.info(
            "  «%s»: собрано %d%s, ошибок %d | прогресс: %d/%d объектов, "
            "всего собрано %d",
            name, collected, f", скачано {downloaded}" if not dry_run else "",
            len(result.get("errors", [])), i - skipped, len(objects), total_collected,
        )
        for err in result.get("errors", []):
            logger.warning("    %s: %s", name, err)
            errors.append(f"{name}: {err}")
        if collected == 0:
            empty.append(name)

    return {
        "objects": len(objects),
        "collected": total_collected,
        "downloaded": total_downloaded,
        "skipped": skipped,
        "by_source": by_source,
        "errors": errors,
        "empty": empty,
    }


def print_stats(stats: dict, dry_run: bool) -> None:
    """Итоговая статистика сбора: объекты, ассеты (всего и по источникам),
    ошибки по типам."""
    print("\n=== Статистика сбора ===")
    print(f"Объектов в списке: {stats['objects']} (пропущено: {stats['skipped']})")
    print(f"Ассетов собрано: {stats['collected']}" + ("" if dry_run
          else f" (скачано файлов: {stats['downloaded']})"))
    if stats["by_source"]:
        print("По источникам:")
        for src, cnt in sorted(stats["by_source"].items(), key=lambda x: -x[1]):
            print(f"  {src}: {cnt}")
    if stats["errors"]:
        by_type: dict[str, int] = {}
        for err in stats["errors"]:
            t = _error_type(err)
            by_type[t] = by_type.get(t, 0) + 1
        print(f"Ошибок: {len(stats['errors'])} — по типам:")
        for t, cnt in sorted(by_type.items(), key=lambda x: -x[1]):
            print(f"  {t}: {cnt}")
        for err in stats["errors"][:10]:
            print(f"    - {err}")
    else:
        print("Ошибок: 0")
    if stats["empty"]:
        print("Не собрано ни одного ассета для:", ", ".join(stats["empty"]))


def _db_counts() -> tuple[int, int]:
    """Количество объектов и ассетов в БД (для итоговой статистики)."""
    conn = sqlite3.connect(DB_PATH)
    try:
        objects = conn.execute("SELECT COUNT(*) FROM historical_objects").fetchone()[0]
        assets = conn.execute("SELECT COUNT(*) FROM historical_assets").fetchone()[0]
    finally:
        conn.close()
    return objects, assets


async def run_pipeline(objects: list[dict], limit: int, run_post: bool,
                       mode: str = "general", year_from: int | None = None,
                       year_to: int | None = None, dry_run: bool = False,
                       resume: bool = False) -> int:
    """Сбор + пост-обработка (backfill era, координаты, миниатюры, экспорт)."""
    sources = build_sources()
    logger.info("Настройки: источники=%s, лимит=%d, режим=%s, объектов=%d, "
                "период=%s–%s, dry_run=%s, resume=%s",
                sources, limit, mode, len(objects),
                year_from or "…", year_to or "…", dry_run, resume)

    stats = await collect_all(objects, limit, sources, mode=mode,
                              year_from=year_from, year_to=year_to,
                              dry_run=dry_run, resume=resume)

    logger.info("Сбор завершён: собрано %d ассетов%s, пропущено объектов %d",
                stats["collected"],
                f", скачано {stats['downloaded']}" if not dry_run else "",
                stats["skipped"])
    for name in stats["empty"]:
        logger.warning("Не собрано ни одного ассета для: %s", name)
    if stats["errors"]:
        logger.warning("Ошибок во время сбора: %d", len(stats["errors"]))

    if dry_run:
        print_stats(stats, dry_run=True)
        logger.info("--dry-run: БД не изменялась, файлы не скачивались.")
        return 0

    if not run_post:
        print_stats(stats, dry_run=False)
        logger.info("--skip-post: пост-обработка пропущена.")
        return 0

    logger.info("Шаг 1/6: backfill material_type (тип материала ассетов)...")
    try:
        material_updated = await backfill_material_types()
        logger.info("  material_type обновлён у %d ассетов", material_updated)
    except Exception as exc:
        logger.error("  Ошибка при backfill material_type: %s", exc)

    logger.info("Шаг 2/6: backfill era (диапазон веков по годам ассетов)...")
    try:
        updated = await backfill_era()
        logger.info("  era заполнена у %d объектов", updated)
    except Exception as exc:
        logger.error("  Ошибка при backfill era: %s", exc)

    logger.info("Шаг 3/6: заполнение координат (update_coordinates.py)...")
    try:
        coords_stats = update_missing_coordinates(DB_PATH)
        logger.info("  координаты: обработано=%d, геокодер=%d, fallback=%d, не удалось=%d",
                    coords_stats["total"], coords_stats["via_geocode"],
                    coords_stats["via_fallback"], coords_stats["failed"])
    except Exception as exc:
        logger.error("  Ошибка при заполнении координат: %s", exc)

    logger.info("Шаг 4/6: перегенерация миниатюр (regenerate_thumbnails.py)...")
    try:
        await regenerate_all_thumbnails(DB_PATH)
    except Exception as exc:
        logger.error("  Ошибка при перегенерации миниатюр: %s", exc)

    logger.info("Шаг 5/6: экспорт JSON (export_to_json.py)...")
    try:
        export_to_json(
            output_path=os.path.join(PROJECT_ROOT, "export", "historical_data.json"),
            absolute=False,
            db_path=DB_PATH,
        )
    except Exception as exc:
        logger.error("  Ошибка при экспорте JSON: %s", exc)

    print_stats(stats, dry_run=False)

    n_objects, n_assets = _db_counts()
    logger.info("Итог: объектов в БД=%d, ассетов в БД=%d", n_objects, n_assets)
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--limit", type=int, default=DEFAULT_LIMIT,
        help=f"лимит ассетов на источник/объект (по умолчанию {DEFAULT_LIMIT})",
    )
    parser.add_argument(
        "--mode", default="general", choices=["general", "photogrammetry"],
        help="general — обычный сбор; photogrammetry — 50–100 файлов/объект, "
             "оригиналы без 2048px-версии, фильтр ≥2000px",
    )
    parser.add_argument(
        "--only", default="",
        help="собрать только указанные объекты (через запятую), а не весь список",
    )
    parser.add_argument(
        "--skip-post", action="store_true",
        help="только сбор, без пост-обработки (backfill/координаты/миниатюры/экспорт)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="оценка объёма: только поиск (scrape), без записи в БД и скачивания",
    )
    parser.add_argument(
        "--resume", action="store_true",
        help="пропускать объекты, у которых уже скачано >= limit файлов",
    )
    parser.add_argument(
        "--year-from", type=int, default=DEFAULT_YEAR_FROM,
        help=f"нижняя граница периода (по умолчанию {DEFAULT_YEAR_FROM})",
    )
    parser.add_argument(
        "--year-to", type=int, default=DEFAULT_YEAR_TO,
        help=f"верхняя граница периода (по умолчанию {DEFAULT_YEAR_TO})",
    )
    parser.add_argument(
        "--century", type=int, default=None,
        help="век: 18 → 1701–1800",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    # century → диапазон годов (18 → 1701–1800)
    year_from, year_to = args.year_from, args.year_to
    if args.century:
        if args.year_from == DEFAULT_YEAR_FROM:
            year_from = (args.century - 1) * 100 + 1
        if args.year_to == DEFAULT_YEAR_TO:
            year_to = args.century * 100

    objects = asyncio.run(load_target_objects())
    if args.only:
        wanted = {o.strip().lower() for o in args.only.split(",") if o.strip()}
        objects = [o for o in objects if o["name"].lower() in wanted]
        if not objects:
            logger.error("Ни один объект из --only не найден в БД/списке.")
            return 1
        logger.info("Отфильтровано по --only: %d объектов", len(objects))

    return asyncio.run(run_pipeline(objects, args.limit, not args.skip_post,
                                    args.mode, year_from, year_to,
                                    dry_run=args.dry_run, resume=args.resume))


if __name__ == "__main__":
    sys.exit(main())
