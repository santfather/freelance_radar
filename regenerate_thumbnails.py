#!/usr/bin/env python3
"""Перегенерация миниатюр для ассетов с оригиналом, но без миниатюры.

Выбираются ассеты, у которых:
  - есть исходное изображение на диске: original_path (или local_path для
    legacy-загрузок, сохранённых до введения original_path);
  - thumbnail_path пуст или файл миниатюры не существует.

Для каждого такого ассета создаётся миниатюра (JPEG, макс. 512 px, качество 75)
через MediaOptimizer.create_thumbnail в папке assets/thumbnails/<city>/<slug>/
и обновляется поле thumbnail_path в БД.

Запуск:
    .venv/bin/python regenerate_thumbnails.py
"""

import asyncio
import os
import re
import sqlite3
import sys

import aiosqlite

from collectors.optimizer import MediaOptimizer

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.getenv("DB_PATH", os.path.join(PROJECT_ROOT, "radar.db"))

THUMB_MAX_SIDE = 512
THUMB_QUALITY = 75

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _exists(path: str | None) -> bool:
    if not path:
        return False
    full = path if os.path.isabs(path) else os.path.join(PROJECT_ROOT, path)
    return os.path.isfile(full)


def _thumb_filename(source_path: str) -> str:
    """Имя файла миниатюры: <stem>_thumb.jpg (из '<year>_<id>_original.jpg' → '_thumb')."""
    stem = os.path.splitext(os.path.basename(source_path))[0]
    stem = re.sub(r"_original$", "", stem)
    return f"{stem}_thumb.jpg"


def _thumb_path_for(asset: dict, obj: dict) -> str:
    """Путь миниатюры по структуре MediaOptimizer: thumbnails/<city>/<slug>/..."""
    city = (obj.get("city") or "").strip().lower() or "unknown"
    slug = (obj.get("slug") or "").strip().lower()
    if not slug:
        slug = _SLUG_RE.sub("_", (obj.get("name") or "").lower()).strip("_") or "unknown"
    source = asset.get("original_path") or asset.get("local_path") or ""
    filename = _thumb_filename(source)
    return os.path.join("assets", "thumbnails", city, slug, filename)


def _source_path(asset: dict) -> str | None:
    """Исходный файл для миниатюры: original_path или legacy local_path."""
    for key in ("original_path", "local_path"):
        raw = (asset.get(key) or "").strip()
        if raw and _exists(raw):
            return raw
    return None


async def regenerate_all_thumbnails(db_path: str = DB_PATH) -> int:
    """Перегенерировать миниатюры для всех ассетов, у которых нет валидной.

    Возвращает код: 0 — без ошибок, 1 — были ошибки или БД недоступна.
    """
    if not os.path.isfile(db_path):
        print(f"Ошибка: база данных не найдена: {db_path}", file=sys.stderr)
        return 1

    # timeout — чтобы операции записи не падали мгновенно при кратковременной
    # блокировке БД (например, параллельным процессом).
    async with aiosqlite.connect(db_path, timeout=30) as db:
        db.row_factory = aiosqlite.Row
        try:
            cols = set()
            async with db.execute("PRAGMA table_info(historical_assets)") as cur:
                cols = {row[1] for row in await cur.fetchall()}
            if "original_path" not in cols or "thumbnail_path" not in cols:
                print(
                    "Ошибка: таблица historical_assets не содержит original_path/thumbnail_path",
                    file=sys.stderr,
                )
                return 1

            objects: dict[int, dict] = {}
            async with db.execute(
                "SELECT id, name, slug, city FROM historical_objects"
            ) as cur:
                for row in await cur.fetchall():
                    objects[int(row["id"])] = dict(row)

            assets: list[dict] = []
            async with db.execute(
                "SELECT id, object_id, original_path, local_path, thumbnail_path, "
                "year, title FROM historical_assets"
            ) as cur:
                for row in await cur.fetchall():
                    assets.append(dict(row))
        except sqlite3.Error as exc:
            print(f"Ошибка чтения БД: {exc}", file=sys.stderr)
            return 1

        processed = 0
        already_have = 0
        no_source = 0
        errors = 0

        for asset in assets:
            thumb_exists = _exists(asset.get("thumbnail_path"))
            if thumb_exists:
                already_have += 1
                continue

            source = _source_path(asset)
            if source is None:
                no_source += 1
                continue

            obj = objects.get(int(asset.get("object_id") or 0), {})
            thumb_rel = _thumb_path_for(asset, obj)
            thumb_abs = thumb_rel if os.path.isabs(thumb_rel) else os.path.join(PROJECT_ROOT, thumb_rel)
            source_abs = source if os.path.isabs(source) else os.path.join(PROJECT_ROOT, source)

            title = (asset.get("title") or f"asset #{asset['id']}").strip()
            try:
                width, height, size = await MediaOptimizer.create_thumbnail(
                    source_abs, thumb_abs
                )
                rel_for_db = thumb_rel.replace("\\", "/")
                await db.execute(
                    "UPDATE historical_assets SET thumbnail_path=? WHERE id=?",
                    (rel_for_db, asset["id"]),
                )
                await db.commit()
                processed += 1
                print(
                    f"  OK: «{title}» -> {thumb_rel} "
                    f"({width}x{height}, {size // 1024} KB)"
                )
            except Exception as exc:
                errors += 1
                print(f"  ОШИБКА: «{title}»: {exc}")

    print("\nСтатистика:")
    print(f"  Создано миниатюр: {processed}")
    print(f"  Уже были миниатюры: {already_have}")
    print(f"  Нет исходного файла (original_path/local_path): {no_source}")
    print(f"  Ошибки: {errors}")
    return 0 if errors == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(regenerate_all_thumbnails()))
