#!/usr/bin/env python3
"""Заполнение координат для объектов, у которых они отсутствуют.

Порядок обработки каждой записи (latitude IS NULL OR longitude IS NULL):
  1. Попытка геокодирования через Nominatim (geopy) по "name, city, Poland"
     (или "name, Poland", если город не указан).
  2. Если геокодер недоступен, запрос не дал результата или произошла
     ошибка сети — используются fallback-координаты центра города из
     CITY_FALLBACKS (для известных городов), иначе (0.0, 0.0).

Запуск:
    .venv/bin/python update_coordinates.py

Зависимость: geopy (см. requirements.txt). Геокодирование требует интернет;
без него скрипт работает на fallback-значениях.
"""

import os
import sqlite3
import sys
import time

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.getenv("DB_PATH", os.path.join(PROJECT_ROOT, "radar.db"))

USER_AGENT = "freelance-radar-update-coordinates/1.0 (data sync for personal AR app)"
GEOCODE_TIMEOUT = 10       # секунд на запрос к Nominatim
GEOCODE_DELAY = 1.0        # пауза между запросами (правила Nominatim: 1 req/s)

# Fallback-координаты центров городов (ключи — нижний регистр).
CITY_FALLBACKS: dict[str, tuple[float, float]] = {
    "warsaw": (52.2297, 21.0122),
    "warszawa": (52.2297, 21.0122),
    "krakow": (50.0647, 19.9450),
    "kraków": (50.0647, 19.9450),
    "cracow": (50.0647, 19.9450),
    "gdansk": (54.3520, 18.6466),
    "gdańsk": (54.3520, 18.6466),
    "danzig": (54.3520, 18.6466),
    "wroclaw": (51.1079, 17.0385),
    "wrocław": (51.1079, 17.0385),
    "breslau": (51.1079, 17.0385),
    "poznan": (52.4064, 16.9252),
    "poznań": (52.4064, 16.9252),
    "lodz": (51.7592, 19.4560),
    "łódź": (51.7592, 19.4560),
    "lublin": (51.2465, 22.5684),
    "katowice": (50.2649, 19.0238),
    "prague": (50.0755, 14.4378),
    "praha": (50.0755, 14.4378),
    "praga": (50.0755, 14.4378),
    "berlin": (52.5200, 13.4050),
    "vienna": (48.2082, 16.3738),
    "wien": (48.2082, 16.3738),
    "wiedeń": (48.2082, 16.3738),
    "paris": (48.8566, 2.3522),
    "paryż": (48.8566, 2.3522),
    "london": (51.5074, -0.1278),
    "kyiv": (50.4501, 30.5234),
    "kiev": (50.4501, 30.5234),
    "kijów": (50.4501, 30.5234),
    "vilnius": (54.6872, 25.2797),
    "wilno": (54.6872, 25.2797),
    "riga": (56.9496, 24.1052),
    "ryga": (56.9496, 24.1052),
    "stockholm": (59.3293, 18.0686),
    "sztokholm": (59.3293, 18.0686),
    "moscow": (55.7558, 37.6173),
    "moskwa": (55.7558, 37.6173),
    "stpetersburg": (59.9343, 30.3351),
    "saint-petersburg": (59.9343, 30.3351),
    "budapest": (47.4979, 19.0402),
    "budapeszt": (47.4979, 19.0402),
}

DEFAULT_FALLBACK = (0.0, 0.0)


def fallback_coords(name: str, city: str) -> tuple[float, float]:
    """Координаты центра города из таблицы, иначе попытка определить город по
    названию объекта, иначе (0.0, 0.0)."""
    city_key = (city or "").strip().lower()
    if city_key in CITY_FALLBACKS:
        return CITY_FALLBACKS[city_key]
    lowered = (name or "").lower()
    for alias, coords in CITY_FALLBACKS.items():
        if alias in lowered:
            return coords
    return DEFAULT_FALLBACK


def _make_geocoder():
    """Создать геокодер Nominatim или None, если geopy не установлен."""
    try:
        from geopy.geocoders import Nominatim
    except ImportError:
        return None
    return Nominatim(user_agent=USER_AGENT, timeout=GEOCODE_TIMEOUT)


def _geocode(geocoder, query: str) -> tuple[float, float] | None:
    """Один запрос к Nominatim. Возвращает координаты или None при ошибке/пустоте."""
    try:
        location = geocoder.geocode(query, language="en")
    except Exception as exc:
        print(f"      геокодер недоступен: {exc}")
        return None
    if location is None:
        return None
    return location.latitude, location.longitude


def update_missing_coordinates(db_path: str = DB_PATH) -> dict:
    """Заполнить координаты для объектов, где latitude/longitude пустые.

    Возвращает статистику: total, via_geocode, via_fallback, failed.
    """
    if not os.path.isfile(db_path):
        raise FileNotFoundError(f"база данных не найдена: {db_path}")

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(historical_objects)")}
        if "latitude" not in cols or "longitude" not in cols:
            raise RuntimeError(
                "таблица historical_objects не содержит колонок latitude/longitude"
            )

        rows = conn.execute(
            "SELECT id, name, city FROM historical_objects "
            "WHERE latitude IS NULL OR longitude IS NULL"
        ).fetchall()
    except sqlite3.Error as exc:
        conn.close()
        raise RuntimeError(f"не удалось прочитать базу данных: {exc}") from exc

    if not rows:
        conn.close()
        return {"total": 0, "via_geocode": 0, "via_fallback": 0, "failed": 0}

    geocoder = _make_geocoder()
    if geocoder is None:
        print("Внимание: geopy не установлен — используются только fallback-координаты.")
        print("Установите: .venv/bin/pip install geopy")

    stats = {"total": len(rows), "via_geocode": 0, "via_fallback": 0, "failed": 0}
    try:
        for row in rows:
            name = row["name"] or ""
            city = row["city"] or ""
            query = f"{name}, {city}, Poland" if city else f"{name}, Poland"
            print(f"  «{name}» (город: {city or '—'})")

            coords = None
            if geocoder is not None:
                print(f"      запрос: {query}")
                coords = _geocode(geocoder, query)
                time.sleep(GEOCODE_DELAY)

            if coords is None:
                coords = fallback_coords(name, city)
                if coords == DEFAULT_FALLBACK:
                    stats["failed"] += 1
                    print(f"      fallback не найден — установлены (0.0, 0.0)")
                else:
                    stats["via_fallback"] += 1
                    print(f"      fallback (центр города): {coords[0]:.4f}, {coords[1]:.4f}")
            else:
                stats["via_geocode"] += 1
                print(f"      геокодер: {coords[0]:.4f}, {coords[1]:.4f}")

            conn.execute(
                "UPDATE historical_objects SET latitude=?, longitude=? WHERE id=?",
                (coords[0], coords[1], row["id"]),
            )
        conn.commit()
    finally:
        conn.close()

    return stats


def main() -> int:
    try:
        stats = update_missing_coordinates()
    except (FileNotFoundError, RuntimeError) as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 1

    print("\nСтатистика:")
    print(f"  Обработано объектов: {stats['total']}")
    print(f"  Обновлено через геокодер: {stats['via_geocode']}")
    print(f"  Обновлено через fallback: {stats['via_fallback']}")
    print(f"  Не удалось (нет данных о городе): {stats['failed']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
