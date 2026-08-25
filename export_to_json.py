#!/usr/bin/env python3
"""Экспорт исторических объектов и ассетов из radar.db в единый JSON-файл.

Формат ориентирован на iOS-приложение Geo-History Spots (гибридный):
  - "arContent"   — одиночный контент, парсится текущей моделью HistoricalSite
                    (поле arContent: ARContent, transformArray, metadataYear: Double);
  - "arContents"  — все ассеты объекта (для будущего импорта в Firestore);
  - поле "source" — дополнительное, декодером приложения игнорируется.

Скрипт использует только стандартную библиотеку Python (sqlite3, json, os, re,
argparse), работает без интернета и без активированного виртуального окружения.

Запуск:
    python3 export_to_json.py                    # radar.db в корне проекта
    python3 export_to_json.py /path/radar.db     # явный путь к БД
    python3 export_to_json.py --absolute         # абсолютные пути к файлам
    python3 export_to_json.py -o out/data.json   # свой путь к выходному JSON

Аргументы:
    db_path          путь к radar.db (опционально; по умолчанию $DB_PATH или ./radar.db)
    --absolute       преобразовывать относительные пути к файлам в абсолютные
                     (на основе корня проекта / ASSETS_ROOT из .env)
    --output, -o     путь к выходному JSON (по умолчанию export/historical_data.json)
"""

import argparse
import json
import os
import re
import sqlite3
import sys

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DB_PATH = os.path.join(PROJECT_ROOT, "radar.db")
DEFAULT_OUTPUT_FILE = os.path.join(PROJECT_ROOT, "export", "historical_data.json")

DEFAULT_RADIUS = 30
IDENTITY_TRANSFORM = [
    1.0, 0.0, 0.0, 0.0,
    0.0, 1.0, 0.0, 0.0,
    0.0, 0.0, 1.0, 0.0,
    0.0, 0.0, 0.0, 1.0,
]

_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".tiff", ".bmp", ".heic"}
_MODEL_EXTS = {".usdz", ".usdc", ".usda", ".obj", ".glb", ".gltf"}
_VIDEO_EXTS = {".mp4", ".mov", ".m4v"}

# Локальные пути-кандидаты для url ассета (в порядке приоритета).
# file_url (внешняя ссылка) намеренно не используется: если файл не скачан —
# ассет пропускается, чтобы в JSON не было битых ссылок.
_URL_CANDIDATES = ("optimized_path", "local_path", "original_path")
_THUMB_CANDIDATES = ("thumbnail_path",)

# Транслитерация для генерации id из name (как в database.py)
_SLUG_TRANSLIT = str.maketrans({
    "ą": "a", "ć": "c", "ę": "e", "ł": "l", "ń": "n",
    "ó": "o", "ś": "s", "ź": "z", "ż": "z",
    "ü": "u", "ö": "o", "ä": "a", "ß": "ss", "é": "e",
})

# Годы в диапазоне 1000–2099: исторические материалы (карты, гравюры, планы)
# датируются вплоть до XI века, поэтому 19xx/20xx было бы слишком узко.
_YEAR_RE = re.compile(r"(?:1[0-9]{3}|20[0-9]{2})")  # первое четырёхзначное число 1000–2099


def _load_assets_root() -> str | None:
    """Прочитать ASSETS_ROOT из .env рядом со скриптом (без python-dotenv)."""
    env_path = os.path.join(PROJECT_ROOT, ".env")
    try:
        with open(env_path, encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if stripped.startswith("ASSETS_ROOT="):
                    value = stripped.split("=", 1)[1].strip().strip('"').strip("'")
                    return value or None
    except OSError:
        return None
    return None


ASSETS_ROOT = os.getenv("ASSETS_ROOT") or _load_assets_root()


def slugify(text: str) -> str:
    """Транслитерация и приведение к виду snake_case (для id объекта)."""
    text = (text or "").lower().translate(_SLUG_TRANSLIT)
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return text.strip("_")


def parse_year(value) -> int | None:
    """Достать год из строки ('1939', '1939–1945', 'circa 1900') или вернуть None."""
    if not value:
        return None
    match = _YEAR_RE.search(str(value))
    return int(match.group()) if match else None


def content_type(file_type: str, path: str) -> str:
    """Сопоставить file_type / расширение файла с ContentType из iOS-приложения."""
    ext = os.path.splitext((path or "").lower())[1]
    if ext in _MODEL_EXTS:
        return "model3D"
    if ext in _VIDEO_EXTS or (file_type or "").lower() in {"mp4", "mov", "video"}:
        return "video"
    return "image"


def resolve_local_path(path: str, use_absolute: bool) -> str | None:
    """Проверить существование локального файла и вернуть путь.

    Пути в БД относительные (assets/...), резолвятся относительно корня проекта
    (или ASSETS_ROOT из .env, если он задан абсолютным путём). При use_absolute
    возвращается абсолютный путь, иначе — исходный относительный.
    """
    if not path:
        return None
    if path.startswith(("http://", "https://")):
        return path

    if os.path.isabs(path):
        full_candidates = [path]
    else:
        full_candidates = [os.path.join(PROJECT_ROOT, path)]
        if ASSETS_ROOT and os.path.isabs(ASSETS_ROOT):
            full_candidates.append(os.path.join(ASSETS_ROOT, path))

    for full in full_candidates:
        if os.path.isfile(full):
            return full if use_absolute else path
    return None


def build_ar_content(asset: dict, use_absolute: bool) -> tuple[dict | None, str | None]:
    """Собрать ARContent-подобный словарь из записи ассета.

    Возвращает (content, warning). content равен None, если подходящего файла
    нет на диске — такой ассет пропускается. warning — если файл есть, но
    миниатюра отсутствует (thumbnailURL остаётся null).
    """
    url = resolve_local_path(
        next((asset.get(k) for k in _URL_CANDIDATES if asset.get(k)), None),
        use_absolute,
    )
    if url is None:
        return None, None

    thumbnail = resolve_local_path(asset.get("thumbnail_path"), use_absolute)
    warning = None
    if thumbnail is None:
        warning = (
            f"миниатюра отсутствует — thumbnailURL=null "
            f"(запустите regenerate_thumbnails.py)"
        )

    year = parse_year(asset.get("year"))

    content = {
        "type": content_type(asset.get("file_type"), url),
        "url": url,
        "transformArray": IDENTITY_TRANSFORM,
        "occlusionData": None,
        "metadataYear": year,
        "thumbnailURL": thumbnail,
        "blurb": (asset.get("description") or "").strip() or None,
        "source": (asset.get("source") or "").strip() or None,
        "materialType": (asset.get("material_type") or "unknown").strip() or "unknown",
    }
    return content, warning


def build_era(obj: dict, years: list[int]) -> str:
    """era из объекта, иначе диапазон по годам ассетов ('1939–1945') или ''."""
    era = (obj.get("era") or "").strip()
    if era:
        return era
    if years:
        return f"{min(years)}–{max(years)}"
    return ""


def load_objects_and_assets(db_path: str) -> tuple[list[dict], list[dict]]:
    """Прочитать все исторические объекты и ассеты из SQLite."""
    conn = sqlite3.connect(db_path)
    try:
        conn.row_factory = sqlite3.Row
        objects = [dict(r) for r in conn.execute(
            "SELECT * FROM historical_objects ORDER BY id"
        ).fetchall()]
        assets = [dict(r) for r in conn.execute(
            "SELECT * FROM historical_assets ORDER BY id"
        ).fetchall()]
    finally:
        conn.close()
    return objects, assets


def build_sites(
    objects: list[dict],
    assets: list[dict],
    use_absolute: bool,
) -> tuple[list[dict], list[str]]:
    """Сгруппировать ассеты по object_id и собрать список сайтов.

    Возвращает (sites, warnings). Warnings содержат предупреждения о
    пропущенных ассетах/объектах, отсутствующих миниатюрах и нулевых координатах.
    """
    assets_by_object: dict[int, list[dict]] = {}
    for asset in assets:
        assets_by_object.setdefault(int(asset["object_id"]), []).append(asset)

    sites: list[dict] = []
    warnings: list[str] = []

    for obj in objects:
        obj_id = int(obj["id"])
        grouped = assets_by_object.get(obj_id, [])
        if not grouped:
            warnings.append(f"Объект «{obj['name']}»: нет ассетов — сайт пропущен")
            continue

        contents: list[dict] = []
        for asset in grouped:
            content, warning = build_ar_content(asset, use_absolute)
            if content is None:
                warnings.append(
                    f"Ассет «{asset.get('title') or asset.get('file_url')}» объекта "
                    f"«{obj['name']}» пропущен: файл не найден на диске"
                )
                continue
            contents.append(content)
            if warning:
                warnings.append(
                    f"Ассет «{asset.get('title') or content['url']}» объекта "
                    f"«{obj['name']}»: {warning}"
                )

        if not contents:
            warnings.append(
                f"Объект «{obj['name']}»: ни один ассет не имеет файла — сайт пропущен"
            )
            continue

        years = [y for c in contents if (y := c["metadataYear"]) is not None]

        site_id = (obj.get("slug") or "").strip()
        if not site_id:
            site_id = slugify(obj.get("name"))
        if not site_id:
            site_id = f"site_{obj_id}"

        latitude = obj.get("latitude")
        longitude = obj.get("longitude")
        if latitude is None or longitude is None:
            warnings.append(
                f"Объект «{obj['name']}»: координаты отсутствуют в БД — "
                f"установлены 0.0 (запустите update_coordinates.py)"
            )
            latitude = latitude or 0.0
            longitude = longitude or 0.0
        elif float(latitude) == 0.0 and float(longitude) == 0.0:
            warnings.append(
                f"Объект «{obj['name']}»: координаты (0.0, 0.0) — "
                f"вероятно, не заполнены (запустите update_coordinates.py)"
            )

        sites.append({
            "id": site_id,
            "name": obj.get("name") or site_id,
            "latitude": float(latitude),
            "longitude": float(longitude),
            "altitude": obj.get("altitude"),
            "radius": DEFAULT_RADIUS,
            "era": build_era(obj, years),
            "arContent": contents[0],
            "arContents": contents,
        })

    return sites, warnings


def verify_integrity(sites: list[dict]) -> tuple[list[dict], list[str]]:
    """Итоговая проверка: все пути в JSON должны указывать на существующие файлы.

    Если файл отсутствует — ассет удаляется из arContent/arContents, добавляется
    предупреждение. Гарантирует, что в JSON не останется битых ссылок.
    """
    warnings: list[str] = []
    kept_sites: list[dict] = []

    for site in sites:
        valid = []
        for content in site["arContents"]:
            url_ok = resolve_local_path(content.get("url"), use_absolute=False) is not None
            thumb = content.get("thumbnailURL")
            thumb_ok = (
                thumb is None
                or (thumb.startswith(("http://", "https://")))
                or resolve_local_path(thumb, use_absolute=False) is not None
            )
            if url_ok and thumb_ok:
                valid.append(content)
            else:
                warnings.append(
                    f"Сайт «{site['id']}»: ассет «{content.get('url')}» исключён "
                    f"из-за отсутствующего файла"
                )

        if not valid:
            warnings.append(f"Сайт «{site['id']}»: не осталось валидных ассетов — пропущен")
            continue

        site = dict(site)
        site["arContents"] = valid
        site["arContent"] = valid[0]
        kept_sites.append(site)

    return kept_sites, warnings


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "db_path", nargs="?", default=None,
        help=f"путь к radar.db (по умолчанию $DB_PATH или {DEFAULT_DB_PATH})",
    )
    parser.add_argument(
        "--absolute", action="store_true",
        help="преобразовывать относительные пути к файлам в абсолютные",
    )
    parser.add_argument(
        "--output", "-o", default=DEFAULT_OUTPUT_FILE,
        help="путь к выходному JSON (по умолчанию export/historical_data.json)",
    )
    return parser.parse_args(argv)


def export_to_json(
    output_path: str = DEFAULT_OUTPUT_FILE,
    absolute: bool = False,
    db_path: str | None = None,
) -> int:
    """Сгенерировать JSON-дамп из radar.db.

    Параметры:
        output_path — путь к выходному JSON;
        absolute    — использовать абсолютные пути к файлам;
        db_path     — путь к БД (по умолчанию $DB_PATH или ./radar.db).

    Возвращает код возврата: 0 — успех, 1 — ошибка.
    """
    db_path = db_path or os.getenv("DB_PATH") or DEFAULT_DB_PATH
    db_path = os.path.abspath(db_path)

    if not os.path.isfile(db_path):
        print(f"Ошибка: база данных не найдена: {db_path}", file=sys.stderr)
        print("Укажите путь к radar.db аргументом или переменной DB_PATH.", file=sys.stderr)
        return 1

    try:
        objects, assets = load_objects_and_assets(db_path)
    except sqlite3.Error as exc:
        print(f"Ошибка: не удалось прочитать базу данных {db_path}: {exc}", file=sys.stderr)
        return 1

    print("Экспорт исторических данных")
    print("=" * 40)
    print(f"База: {db_path}")
    print(f"Объектов в БД: {len(objects)}")
    print(f"Ассетов в БД: {len(assets)}")
    print(f"Режим путей: {'абсолютные' if absolute else 'относительные'}")

    sites, warnings = build_sites(objects, assets, absolute)
    sites, integrity_warnings = verify_integrity(sites)
    warnings.extend(integrity_warnings)

    included_assets = sum(len(s["arContents"]) for s in sites)
    print(f"Включено ассетов: {included_assets}")
    print(f"Пропущено ассетов: {len(assets) - included_assets}")
    print(f"Сайтов в JSON: {len(sites)}")

    for warning in warnings:
        print(f"Предупреждение: {warning}")

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump({"sites": sites}, f, ensure_ascii=False, indent=2)

    print(f"Файл сохранён: {output_path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    return export_to_json(
        output_path=args.output,
        absolute=args.absolute,
        db_path=args.db_path,
    )


if __name__ == "__main__":
    sys.exit(main())
