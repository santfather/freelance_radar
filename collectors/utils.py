"""Общие утилиты коллекторов исторических материалов.

- `extract_year` — извлечение года с приоритетом: явные метаданные →
  описание/текст → регулярка по всей строке. Защита от ложных срабатываний:
  номера из URL, даты создания страницы и длинные числовые строки отбрасываются.
  Если точного года нет, но в тексте есть обозначение века («XVIIe siècle»,
  «18th century», «XX век») — возвращается первый год века (1701 для XVII).
- `extract_century` — номер века по словесному обозначению.
- `coerce_year` — приведение к целому году 1000–2099.
- `to_roman` / `century_era` / `century_to_years` — работа с веками для поля `era`.
- `detect_material_type` / `material_type_dir` — тип материала ассета и его
  подпапка в структуре `assets/` (photos/paintings/prints/maps/drawings/unknown).
- `is_bot_block` — детект страниц-заглушек антибот-защиты (Incapsula/Cloudflare).
"""

import re

# Год: 1000–2099. Старая иконография (XII–XIX вв.) требует 11xx–18xx,
# поэтому нижняя граница снижена с 1500 до 1000.
YEAR_RE = re.compile(r"\b(1[0-9]{3}|20[0-2]\d)\b")

# Обозначения века: «XVIIe siècle», «18th century», «XX век», «XVII wiek»,
# «13. Jahrhundert». Римская часть ограничена 1–5 символами и должна быть
# «красивой» цифрой, арабская — 1–2 цифрами (1..30), чтобы не цеплять
# произвольные числа.
_CENTURY_WORD = r"(?:si[eè]cle|centur[y]|centurie| век[а]?|wiek(?:u)?|jahrhundert)"
CENTURY_RE = re.compile(
    rf"\b(?P<rom>[IVXLCDM]{{1,5}})(?:e|ème|th|st|nd|rd)?\s*{_CENTURY_WORD}"
    rf"|\b(?P<num>\d{{1,2}})(?:e|ème|th|st|nd|rd|\.)?\s*{_CENTURY_WORD}",
    re.IGNORECASE,
)

# Числа, которые легко принять за год, но это не дата создания материала:
# "012345", длинные последовательности, года из сигнатур страниц.
_YEAR_CONTEXT_BLACKLIST = (
    "tel:", "+48", "e-mail", "http", "www", ".pl", ".gov", ".jpg", ".png",
    "pages", "stron", "dnia", "data utworzenia", "ostatnia",
)

_ROMAN_VALUES = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}


def _safe_year(match: str) -> bool:
    """Отфильтровать заведомо ложные «годы» (служебные строки)."""
    low = match.lower()
    return not any(marker in low for marker in _YEAR_CONTEXT_BLACKLIST)


def _as_text(field) -> str:
    """Привести поле к строке: строки как есть, списки — через запятую."""
    if field is None:
        return ""
    if isinstance(field, str):
        return field
    if isinstance(field, (list, tuple)):
        return ", ".join(str(x) for x in field if x is not None)
    return str(field)


def coerce_year(value) -> int | None:
    """Привести строку/число к целому году (1000–2099) или None."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        v = int(value)
        return v if 1000 <= v <= 2099 else None
    if isinstance(value, str):
        m = re.match(r"^\s*(1[0-9]{3}|20[0-2]\d)\s*$", value.strip())
        if m:
            return int(m.group(1))
    return None


def _roman_to_int(text: str) -> int | None:
    """Римское число (XIV, XVIII) → int. Строго убывающие/вычитающие формы."""
    total = 0
    prev = 0
    for ch in (text or "").upper():
        if ch not in _ROMAN_VALUES:
            return None
        value = _ROMAN_VALUES[ch]
        if value > prev:
            total += value - 2 * prev
        else:
            total += value
        prev = value
    return total if 1 <= total <= 30 else None


def extract_century(text) -> int | None:
    """Номер века из обозначения: 'XVIIe siècle' → 17, '18th century' → 18."""
    for match in CENTURY_RE.finditer(_as_text(text)):
        rom = match.group("rom")
        if rom:
            value = _roman_to_int(rom)
            if value:
                return value
        num = match.group("num")
        if num:
            value = int(num)
            if 1 <= value <= 30:
                return value
    return None


def to_roman(number: int) -> str:
    """Арабское число → римское (1..3999). Вне диапазона — исходное число."""
    if not isinstance(number, int) or not 1 <= number <= 3999:
        return str(number)
    digits = [
        (1000, "M"), (900, "CM"), (500, "D"), (400, "CD"),
        (100, "C"), (90, "XC"), (50, "L"), (40, "XL"),
        (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I"),
    ]
    out: list[str] = []
    for value, symbol in digits:
        while number >= value:
            out.append(symbol)
            number -= value
    return "".join(out)


def century_era(years: list[int]) -> str:
    """Диапазон веков римскими цифрами из списка годов.

    Век считается как `год // 100 + 1` (1500 → XVI, 1600 → XVII, 1700 → XVIII),
    что совпадает с SQL-выражением `year / 100 + 1` из постановки задачи.
    [1450, 1550, 1600] → "XV–XVII вв.", один век → "XVI в.", пусто → "".
    """
    centuries = sorted({y // 100 + 1 for y in years if y and y >= 1000})
    if not centuries:
        return ""
    first, last = centuries[0], centuries[-1]
    if first == last:
        return f"{to_roman(first)} в."
    return f"{to_roman(first)}–{to_roman(last)} вв."


def century_to_years(century: int) -> tuple[int, int]:
    """Диапазон годов века: 18 → (1701, 1800), 20 → (1901, 2000), 1 → (1, 100)."""
    c = int(century)
    if c < 1:
        c = 1
    return (c - 1) * 100 + 1, c * 100


# ── Тип материала ассета ─────────────────────────────────────────────────────

MATERIAL_TYPES: tuple[str, ...] = (
    "photo", "painting", "print", "map", "drawing", "unknown",
)

# Подпапка для каждого типа материала в структуре assets/ (множественное число).
MATERIAL_TYPE_DIRS: dict[str, str] = {
    "photo": "photos",
    "painting": "paintings",
    "print": "prints",
    "map": "maps",
    "drawing": "drawings",
    "unknown": "unknown",
}

# Дефолтные типы по источнику — используются, когда по ключевым словам тип
# не определился. Ключевые слова всегда приоритетнее дефолта источника.
# Wikimedia Commons и Muzeum Warszawy по преимуществу отдают фотографии,
# MET — живопись/объекты, Gallica — гравюры/печатные материалы.
_SOURCE_DEFAULT_MATERIAL: dict[str, str] = {
    "wikimedia": "photo",
    "metmuseum": "painting",
    "gallica": "print",
    "muzeum_warszawy": "photo",
}

# Ключевые слова определения типа по title/description (регистронезависимо,
# по границам слова, чтобы «plan» не цеплялся за «planning»). Порядок задаёт
# приоритет: первый совпавший тип побеждает. Покрыты EN/FR/PL/DE.
_MATERIAL_KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    ("photo", (
        "photo", "photograph", "photographic", "fotografia", "zdjęcie",
        "zdjecie", "zdjęcia", "zdjecia", "fotograf", "foto", "snapshot",
        "negatyw", "negative", "albumen",
    )),
    ("map", (
        "map", "mappa", "karta", "plan miasta", "city plan", "carte",
        "plan", "atlas", "cartography", "cartographic", "geograficzna",
    )),
    ("drawing", (
        "drawing", "drawings", "sketch", "sketches", "rysunek", "rysunki",
        "szkic", "dessin", "caricature", "karikatura", "architecture drawing",
    )),
    ("painting", (
        "painting", "oil", "canvas", "obraz", "tempera", "fresco",
        "gouache", "mural", "malarstwo", "olej", "płótno", "plutno",
    )),
    ("print", (
        "engraving", "etching", "lithograph", "lithography", "rycina",
        "grawiura", "miedzioryt", "drzeworyt", "woodcut", "print",
        "gravure", "mezzotint", "litografia", "druk",
    )),
]


def detect_material_type(source: str, title: str = "", description: str = "") -> str:
    """Определить тип материала ассета.

    Возвращает один из MATERIAL_TYPES: photo/painting/print/map/drawing/unknown.
    Приоритет: ключевые слова в title/description → дефолт источника
    (metmuseum → painting, gallica → print) → unknown.
    """
    text = f"{_as_text(title)} {_as_text(description)}".lower()
    for material_type, keywords in _MATERIAL_KEYWORDS:
        for kw in keywords:
            if re.search(rf"\b{re.escape(kw)}\b", text):
                return material_type
    default = _SOURCE_DEFAULT_MATERIAL.get((source or "").lower())
    return default or "unknown"


def material_type_dir(material_type: str) -> str:
    """Имя подпапки для типа материала (photos/paintings/.../unknown)."""
    return MATERIAL_TYPE_DIRS.get((material_type or "").lower(), "unknown")


def extract_year(*fields: str) -> str:
    """Первый подходящий год из полей в порядке приоритета.

    Каждое поле проверяется по словам-маркерам даты; если поле содержит явные
    метки типа 'rok', 'date', 'data', 'czas', '1939-1945' — приоритет выше.
    Если точный год не найден ни в одном поле, но встретилось обозначение века
    («XVIIe siècle», «18th century») — возвращается первый год этого века
    (для 17-го века это 1701), чтобы фильтрация по периоду работала.
    """
    for field in fields:
        text = _as_text(field).strip()
        if not text:
            continue
        # Диапазон "1939-1945" / "1939–1945": берём первый год
        m = YEAR_RE.search(text)
        if m and _safe_year(text):
            return m.group(1)

    # Резерв: обозначение века без точного года
    for field in fields:
        century = extract_century(field)
        if century:
            return str((century - 1) * 100 + 1)
    return ""


def extract_year_iso(iso: str) -> str:
    """Год из ISO-даты ('1937-01-01T00:00:00' → '1937')."""
    if not iso:
        return ""
    m = re.match(r"(\d{4})", iso)
    return m.group(1) if m else ""


def is_bot_block(text: str) -> bool:
    """Есть ли на странице/в ответе признаки антибот-заглушки."""
    low = (text or "").lower()
    markers = (
        "incapsula",
        "_incapsula_resource",
        "security verification",
        "just a moment",
        "cf-chl",
        "captcha",
        "attention required",
        "please enable cookies",
        "access denied",
        "vérification de sécurité",
        "access interdit",
    )
    return any(marker in low for marker in markers)


def limit_text(text: str, max_len: int = 400) -> str:
    """Обрезать текст и схлопнуть пробелы."""
    if not text:
        return ""
    return re.sub(r"\s+", " ", text).strip()[:max_len]
