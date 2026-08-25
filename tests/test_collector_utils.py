"""Юнит-тесты ключевой логики модуля collectors.

Покрывают: извлечение года, римские цифры/века (era), фильтр по периоду,
определение типа материала и работу с подпапками типов.

Запуск:  .venv/bin/pytest tests/ -v
"""

from collectors.base_collector import BaseCollector
from collectors.utils import (
    century_era,
    century_to_years,
    coerce_year,
    detect_material_type,
    extract_century,
    extract_year,
    material_type_dir,
    to_roman,
)


class _FakeCollector(BaseCollector):
    """Минимальный конкретный коллектор для тестов фильтрации по периоду."""

    source_name = "fake"
    base_url = ""

    async def scrape(self) -> list[dict]:
        return []


def _collector(year_from=None, year_to=None) -> _FakeCollector:
    return _FakeCollector(query="test", limit=10, year_from=year_from, year_to=year_to)


def test_extract_year():
    assert extract_year("painted in 1652") == "1652"
    assert extract_year("Date: 1850") == "1850"
    assert extract_year("circa 1600") == "1600"
    assert extract_year("") == ""


def test_extract_year_century_word():
    """«XVII wiek» → первый год века (1601) или пусто, если не распознан."""
    year = extract_year("XVII wiek")
    assert year == "" or 1601 <= int(year) <= 1700
    year_ru = extract_year("гравюра, XVIII век")
    assert year_ru == "" or 1701 <= int(year_ru) <= 1800


def test_to_roman():
    assert to_roman(1) == "I"
    assert to_roman(4) == "IV"
    assert to_roman(9) == "IX"
    assert to_roman(10) == "X"
    assert to_roman(18) == "XVIII"
    assert to_roman(21) == "XXI"


def test_to_roman_out_of_range():
    assert to_roman(0) == "0"
    assert to_roman(4000) == "4000"


def test_century_era():
    assert century_era([1500, 1600, 1700]) == "XVI–XVIII вв."
    assert century_era([1850, 1860, 1870]) == "XIX в."
    assert century_era([]) == ""


def test_century_to_years():
    assert century_to_years(18) == (1701, 1800)
    assert century_to_years(20) == (1901, 2000)
    assert century_to_years(1) == (1, 100)


def test_filter_by_period():
    c = _collector(year_from=1600, year_to=1700)
    assert c._year_in_period(1650) is True
    assert c._year_in_period(1800) is False
    assert c._year_in_period(None) is True
    assert c._year_in_period("") is True


def test_filter_by_period_disabled():
    c = _collector()
    assert c._year_in_period(1650) is True
    assert c._year_in_period(None) is True


def test_detect_material_type_keywords():
    assert detect_material_type("wikimedia", "Old photograph of Warsaw") == "photo"
    assert detect_material_type("wikimedia", "Oil painting on canvas") == "painting"
    assert detect_material_type("wikimedia", "Engraving of the palace") == "print"
    assert detect_material_type("wikimedia", "Map of Warsaw, 1700") == "map"
    assert detect_material_type("wikimedia", "Sketch of the church") == "drawing"


def test_detect_material_type_source_defaults():
    # ключевые слова приоритетнее дефолта источника
    assert detect_material_type("gallica", "Carte de Paris") == "map"
    assert detect_material_type("metmuseum", "Vase") == "painting"
    assert detect_material_type("wikimedia", "Some artifact") == "photo"
    assert detect_material_type("muzeum_warszawy", "Eksponat") == "photo"


def test_material_type_dir():
    assert material_type_dir("photo") == "photos"
    assert material_type_dir("map") == "maps"
    assert material_type_dir("painting") == "paintings"
    assert material_type_dir("unknown") == "unknown"
    assert material_type_dir("") == "unknown"
    assert material_type_dir(None) == "unknown"


def test_coerce_year():
    assert coerce_year("1652") == 1652
    assert coerce_year(1800) == 1800
    assert coerce_year("500") is None
    assert coerce_year("") is None
    assert coerce_year(None) is None


def test_extract_century():
    assert extract_century("XVIIe siècle") == 17
    assert extract_century("18th century") == 18
    assert extract_century("XX век") == 20
    assert extract_century("") is None
