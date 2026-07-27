# AUDIT — Freelance Radar

> **Дата:** 2026-07-27
> **Метод:** статический анализ кода (Python 3.12+ / JS ES2020 / HTML5)
> **Правила:** PEP 8 (Python), общие практики JS, OWASP Top 10 (урезанно для локального приложения)
> **Изменения в код:** не вносились. Все рекомендации — описательные.

---

## Содержание

1. [Общее состояние проекта](#1-общее-состояние-проекта)
2. [Список проблем](#2-список-проблем)
   - [2.1 Избыточность и дублирование](#21-избыточность-и-дублирование)
   - [2.2 Сложные и трудноподдерживаемые участки](#22-сложные-и-трудноподдерживаемые-участки)
   - [2.3 «ИИ следы» — шаблонный код](#23-ии-следы--шаблонный-код)
   - [2.4 Потенциальные уязвимости безопасности](#24-потенциальные-уязвимости-безопасности)
   - [2.5 Недостаток комментариев](#25-недостаток-комментариев-в-ключевых-местах)
3. [Рекомендации по рефакторингу](#3-рекомендации-по-рефакторингу-с-приоритетом)
4. [План действий (этапы)](#4-предлагаемый-план-действий-поэтапно)
5. [Дефрагментация файлов](#5-список-файлов-для-дефрагментации)
6. [Дополнительные улучшения](#6-дополнительные-улучшения)

---

## 1. Общее состояние проекта

**Оценка: 🟢 Стабильный MVP, требует дефрагментации.**

Проект представляет собой работающее FastAPI-приложение с чётким разделением на слои (scrapers → database → analyzer → SPA). Архитектура простая и прагматичная — ровно то, что нужно для локального инструмента.

**Сильные стороны:**
- Чёткое разделение ответственности между модулями (scrapers / database / analyzer / main)
- Асинхронный I/O на всём стеке (httpx + aiosqlite + asyncio)
- Параметризованные SQL-запросы (без инъекций)
- Pydantic-подобные модели (через dataclasses)
- XSS-защита на фронте (функция `escHtml`)
- .env в .gitignore — ключи не попадают в репозиторий

**Слабые стороны:**
- Избыточное дублирование в scraper'ах (6 почти идентичных реализаций)
- 7 глобальных переменных состояния в main.py — хрупкая конструкция
- 3 неиспользуемых зависимости в requirements.txt
- 2 неиспользуемых импорта
- Нет индексов в SQLite (сканирование всей таблицы при фильтрации)
- 0.0.0.0 в start.sh — приложение открыто в локальную сеть
- Мёртвый параметр `provider` в `update_verdict()`
- Дублирование JS-кода (3 почти идентичных poll-цикла в index.html)

---

## 2. Список проблем

### 2.1 Избыточность и дублирование

#### P1. Дублирование scraper'ов (`scrapers/*.py`)

**Файлы:** `oferia.py`, `useme.py`, `workconnect.py`, `zleca.py`, `upwork.py`, `toptal.py`

Каждый scraper повторяет один и тот же паттерн:
1. Определить список URL
2. Пройти по URL, сделать HTTP-запрос
3. Распарсить BeautifulSoup
4. Извлечь поля (title, description, budget, date)
5. Вызвать `make_id()`, `detect_category()`, `parse_budget()`
6. Собрать `Job(...)` и добавить в список
7. Вывести `print(f"[source] scraped {len(jobs)} jobs")`
8. Вернуть список

**Конкретные дубликаты:**
- `seen: set[str] = set()` и проверка `if ... in seen: continue` — во всех 6 scraper'ах (кроме toptal, где дубляж по id)
- `print(f"[{self.source_name}] scraped {len(jobs)} jobs")` — во всех scraper'ах, с одинаковым паттерном
- Конструирование `Job(...)` с идентичным набором полей — повторяется ~12 раз в разных местах (включая `_extract_from_card`, `_scrape_rss`, `_add_from_ld`, `_scrape_listing`)

**Предложение:** Вынести в `BaseScraper` метод-шаблон `_make_job(title, url, description, budget_raw, posted_at)` + `_dedup_seen` set как поле базового класса. Добавить в `BaseScraper` метод `_scrape_urls(urls, parse_item)` — шаблонный метод для обхода URL и сбора Job'ов. Тогда каждый scraper будет содержать только логику извлечения полей из HTML.

#### P2. Дублирование форматирования промпта (`analyzer.py`)

**Строки:** 93–97, 174–178, 242–246

```python
prompt = USER_TEMPLATE.format(
    title=title, category=category,
    budget=budget or "not specified",
    description=description[:600] if description else "no description",
)
```

Один и тот же блок скопирован в `OllamaAnalyzer.analyze()`, `DeepSeekAnalyzer.analyze()` и `GeminiAnalyzer.analyze()`.

**Предложение:** Вынести в метод `BaseAnalyzer._build_prompt(title, category, budget, description)`.

#### P3. Дублирование обработки ошибок анализа (`analyzer.py`)

**Строки:** 109–115, 206–212, 276–282

Все три анализатора в `except` возвращают одинаковый словарь-заглушку:
```python
return {
    "verdict": "UNKNOWN",
    "reason": f"{provider} error: {e}",
    "complexity": 0,
    "estimated_hours": 0,
}
```

**Предложение:** Вынести в `BaseAnalyzer._error_result(error_msg: str) -> dict`.

#### P4. Дублирование poll-циклов в JS (`templates/index.html`)

**Строки:** 387–404, 422–439, 469–487

Три функции `startScrape()`, `startAnalysis()`, `startReanalysis()` содержат идентичный poll-цикл с `setInterval(1500)`, который обновляет stats, log, progress и проверяет `s.scraping / s.analyzing`.

Отличаются только: URL запроса, текст кнопки, сообщения.

**Предложение:** Вынести в общую функцию `pollUntilDone(endpoint, onDone, getButton)`.

#### P5. Дублирование в database.py — открытие соединения

**database.py (строки 67, 92, 108, 132, 154, 160, 170, 187, 194, 204):** Каждая функция открывает новое соединение через `aiosqlite.connect(DB_PATH)`. Для SQLite это допустимо, но в рамках одного batch-запроса (например, `upsert_jobs` на 500 записей) создаётся 1 соединение, а в `get_stats()` — 3 последовательных SELECT'а с тремя отдельными соединениями.

**Предложение:** Использовать `async with aiosqlite.connect(DB_PATH) as db` один раз на batch; для `get_stats()` — один запрос с `COUNT(*)` через `CASE WHEN`.

---

### 2.2 Сложные и трудноподдерживаемые участки

#### C1. Глобальное состояние в `main.py`

**Строки:** 48–56

```python
_is_scraping = False
_is_analyzing = False
_scrape_log: list[str] = []
_analyze_log: list[str] = []
_analyze_progress = 0
_analyze_total = 0
_scrape_running = False
_analyze_running = False
_analyze_current_provider = ""
```

7 глобальных переменных + дублирование флагов (`_is_scraping` и `_scrape_running` — по сути одно и то же). Это хрупкая конструкция: любая функция может их изменить, нет гарантий атомарности.

**Предложение:** Инкапсулировать в dataclass `AppState`:
```python
@dataclass
class AppState:
    scraping: bool = False
    analyzing: bool = False
    scrape_log: list[str] = field(default_factory=list)
    analyze_log: list[str] = field(default_factory=list)
    analyze_progress: int = 0
    analyze_total: int = 0
    analyze_provider: str = ""
```
Создать экземпляр в lifespan и передавать через зависимости FastAPI (`Depends`). Это сразу решит дублирование `_is_scraping`/`_scrape_running`.

#### C2. Длинные функции

| Функция | Файл | Строки | Линий |
|---------|------|--------|-------|
| `_run_analysis()` | main.py | 102–156 | 55 |
| `_scrape_listing()` | upwork.py | 53–119 | 67 |
| `loadJobs()` + `loadStats()` | index.html | 202–332 | ~130 суммарно |
| `scrape()` в toptal.py | toptal.py | 25–97 | 73 |

**`_run_analysis()` (main.py, 102–156):** Смешивает инициализацию, логирование, три разных try/except, batch-логику и обновление прогресса. Рекомендуется разбить на: `_init_analysis()`, `_process_batch(batch)`, `_finalize_analysis()`.

**`_scrape_listing()` (upwork.py, 53–119):** Содержит два альтернативных подхода к парсингу (селекторы + link-based fallback). Каждый подход — по 30+ строк и 4+ уровня вложенности. Рекомендуется выделить `_scrape_by_selectors()`, `_scrape_by_links()`.

#### C3. Глубокая вложенность

- **upwork.py `_scrape_listing()` (строка 82–117):** fallback link-based extraction — 5 уровней: `for link → if href → if title → card.find_parent → for tag → if txt`.
- **workconnect.py `scrape()` (строка 28–70):** `for link → if title → find_parent → if card → несколько select_one → status check → if is_closed`.
- **toptal.py `scrape()` (строка 37–96):** `for script → try → if data → for item → _add_from_ld → ...`, затем ещё один цикл с `_is_job_link`.

**Предложение:** Использовать ранние возвраты (guard clauses) и вынести вложенные блоки в отдельные методы.

#### C4. Неоптимальные SQL-запросы

**`get_stats()` (database.py, 159–167):** Три отдельных SELECT для total/analyzed/take — можно одним запросом:

```sql
SELECT
    COUNT(*) AS total,
    SUM(CASE WHEN analyzed=1 THEN 1 ELSE 0 END) AS analyzed,
    SUM(CASE WHEN verdict='TAKE' THEN 1 ELSE 0 END) AS take
FROM jobs
```

**Отсутствие индексов:**
- Нет индекса на `analyzed` — `get_unanalyzed_jobs()` и `get_unanalyzed_count()` сканируют всю таблицу
- Нет индекса на `verdict` — фильтрация по вердикту в `get_all_jobs()` сканирует всю таблицу
- Нет индекса на `category` — фильтрация по категории сканирует всю таблицу
- Нет индекса на `scraped_at` — сортировка по `scraped_at DESC` сканирует всю таблицу

Для таблицы на сотни-тысячи записей это не критично, но при росте (>10K) станет заметно.

---

### 2.3 «ИИ следы» — шаблонный код

#### A1. Неиспользуемые зависимости (`requirements.txt`)

| Пакет | Зачем добавлен | Реальность |
|-------|---------------|------------|
| `ollama==0.2.1` | Для вызова Ollama | В коде используется `httpx` напрямую (analyzer.py). Пакет `ollama` не импортируется нигде. |
| `openai==1.30.0` | Для DeepSeek (OpenAI-совместимый API) | DeepSeak вызывается через `httpx` напрямую (analyzer.py строки 197–203). |
| `google-generativeai==0.7.0` | Для Gemini API | Gemini вызывается через `httpx` напрямую (analyzer.py строки 266–274). |
| `jinja2==3.1.4` | Для шаблонов | `templates/index.html` читается как статический файл через `open()` (main.py строка 183). Jinja2 не используется. |

Все 4 пакета можно удалить — их функциональность реализована через `httpx`.

#### A2. Неиспользуемые импорты

| Файл | Строка | Импорт | Статус |
|------|--------|--------|--------|
| `database.py` | 3 | `import json` | Нигде не используется |
| `analyzer.py` | 10 | `Verdict` | Импортирован, но не используется (только `Job` используется) |

#### A3. Мёртвый параметр `provider` в `update_verdict()`

**database.py, строка 91:**
```python
async def update_verdict(job: Job, provider: str = ""):
```
Параметр `provider` принимается, но в теле функции (строки 92–99) нигде не используется. Все вызовы из main.py (строка 141) передают только `job`.

**Предложение:** Удалить параметр `provider`.

#### A4. Избыточный `_OLD_CATEGORY_MAP`

**database.py, строки 12–14:**
```python
_OLD_CATEGORY_MAP = {
    "CMS / WordPress": "CMS",
}
```
Единственное использование — функция `_safe_category()` (строка 19). Это миграционный костыль: если база уже обновлена (а миграция выполняется в `init_db()` строки 58–60), то маппинг больше не нужен. После пересоздания БД можно удалить.

#### A5. `check_provider_available()` не используется

**analyzer.py, строки 325–331:** Функция определена, но нигде не вызывается. В main.py проверки доступности делаются индивидуально для каждого провайдера (строки 261–273).

**Предложение:** Удалить или начать использовать.

#### A6. Избыточный docstring с тривиальным содержанием

- `analyzer.py, строка 48`: `"""Абстрактный анализатор заказов."""` — очевидно из названия класса.
- `main.py, строка 70`: `"""Только парсинг (без анализа)."""` — дублирует имя задачи и комментарий выше.
- `database.py, строка 64`: `# ── Jobs ──`, строка 184: `# ── Settings ──` — визуальные разделители, бесполезны в файле на 207 строк.

---

### 2.4 Потенциальные уязвимости безопасности

#### S1. Публичный хост в `start.sh` (средний)

**start.sh, строка 29:**
```bash
uvicorn main:app --port 8099 --host 0.0.0.0
```
Привязка к `0.0.0.0` открывает приложение для всей локальной сети. Если приложение будет запущено в общественной сети (WiFi коворкинга), API-эндпоинты (включая триггер парсинга и анализа) будут доступны любому устройству в сети. Для локального инструмента следует использовать `127.0.0.1`.

#### S2. API-ключ в URL (низкий)

**analyzer.py, строка 267–268:**
```python
resp = await client.post(
    f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"
    f"?key={self.api_key}",
```
Gemini API-ключ передаётся как query-параметр. Это стандартный метод аутентификации Gemini, но URL может быть сохранён в логах прокси, HTTP-клиента или сервера. Альтернатива — передавать ключ в заголовке `X-Goog-Api-Key`, если Gemini это поддерживает.

#### S3. Нет валидации входных данных в POST /api/settings (средний)

**main.py, строки 316–326:**
```python
async def settings_post(data: dict):
    if "provider" in data:
        provider = data["provider"].lower()
        if provider not in ("ollama", "deepseek", "gemini"):
            return JSONResponse(..., status_code=400)
        await set_setting("llm_provider", provider)
    return JSONResponse({"status": "ok"})
```
Эндпоинт принимает произвольный JSON без Pydantic-модели. Валидируется только ключ `provider`. Любые другие ключи в `data` игнорируются без предупреждения. Для локального приложения — не критично, но стоит использовать Pydantic для консистентности.

#### S4. SQL с f-string (низкий)

**database.py, строка 125:**
```python
sql += f" ORDER BY scraped_at {order} LIMIT 500"
```
Значение `order` валидируется (строка 121: `"DESC" if sort != "asc" else "ASC"`), но технически это конкатенация строк в SQL. Для защиты от future refactoring лучше передавать `order` как параметр.

#### S5. Отсутствие rate limiting / аутентификации (инфо)

Все API-эндпоинты доступны без аутентификации. POST /api/refresh и POST /api/analyze могут быть вызваны кем угодно в сети (см. S1). Для локального инструмента это допустимо, но стоит минимизировать exposure через S1.

---

### 2.5 Недостаток комментариев в ключевых местах

#### M1. Логика batch-обработки анализа (main.py, строки 124–143)

Почему `BATCH_SIZE = 10`? Почему `asyncio.gather` на 10 параллельных запросов к LLM? Какие риски превышения лимитов API? Нет пояснения.

#### M2. Fallback link-экстракция в Upwork (upwork.py, строки 81–117)

Нетривиальный код: поиск ссылок без явных селекторов, определение родительского контейнера, извлечение описания через поиск `len(txt) > 40`. Без комментария непонятно, почему этот fallback существует и когда он срабатывает.

#### M3. JSON-LD парсинг Toptal (toptal.py, строки 36–46, 119–144)

Логика обхода JSON-LD: `@type` может быть `JobPosting` или `ItemList`, внутри ItemList могут быть вложенные объекты. Без комментария непонятно, почему нужна проверка на list/dict и почему оба `title` и `name`.

#### M4. Детекция закрытых заказов в WorkConnect (workconnect.py, строки 64–70)

Поиск `"zakończon"` и `"zamknięt"` в тексте элементов — хрупкая проверка, зависящая от польского языка. Стоит пояснить, что это за элементы и почему используется частичное совпадение.

#### M5. Разделение budget_raw + description в parse_budget (upwork.py, toptal.py)

Во многих местах `parse_budget(budget_raw + " " + description)` или `parse_budget(description + " " + title)` — неочевидно, почему бюджет ищется в описании, а не только в `budget_raw`. Стоит пояснить, что на некоторых площадках бюджет только в тексте описания.

---

## 3. Рекомендации по рефакторингу (с приоритетом)

| ID | Описание | Приоритет | Трудозатраты |
|----|----------|-----------|--------------|
| R1 | Инкапсулировать глобальное состояние в `AppState` (main.py) | **Высокий** | 1 час |
| R2 | Удалить неиспользуемые зависимости (requirements.txt) | **Высокий** | 0.25 часа |
| R3 | Сменить `0.0.0.0` на `127.0.0.1` в `start.sh` | **Высокий** | 0.1 часа |
| R4 | Вынести общий шаблон scraper'ов в BaseScraper | **Высокий** | 2 часа |
| R5 | Удалить неиспользуемые импорты (json, Verdict) | **Средний** | 0.1 часа |
| R6 | Вынести общий код анализаторов в BaseAnalyzer | **Средний** | 0.5 часа |
| R7 | Вынести дублирующийся poll-цикл в JS | **Средний** | 0.5 часа |
| R8 | Добавить индексы в SQLite (analyzed, verdict, category, scraped_at) | **Средний** | 0.5 часа |
| R9 | Оптимизировать `get_stats()` в один SQL-запрос | **Средний** | 0.25 часа |
| R10 | Удалить мёртвый параметр `provider` из `update_verdict()` | **Низкий** | 0.1 часа |
| R11 | Удалить `_OLD_CATEGORY_MAP` (после миграции) | **Низкий** | 0.1 часа |
| R12 | Разбить `_run_analysis()` на подсмысловые функции | **Низкий** | 1 час |
| R13 | Разбить `_scrape_listing()` на `_scrape_by_selectors` + `_scrape_by_links` | **Низкий** | 0.5 часа |
| R14 | Удалить/использовать `check_provider_available()` | **Низкий** | 0.25 часа |
| R15 | Вынести JS в отдельный `static/app.js` | **Низкий** | 1 час |
| R16 | Добавить Pydantic-модель для POST /api/settings | **Низкий** | 0.5 часа |
| R17 | Добавить комментарии в ключевые места (см. §2.5) | **Низкий** | 0.5 часа |
| R18 | Переписать `get_unanalyzed_jobs()` с LIMIT (защита от бесконечного анализа) | **Средний** | 0.25 часа |
| R19 | Убрать дублирование флагов `_is_scraping`/`_scrape_running` | **Средний** | 0.25 часа |

---

## 4. Предлагаемый план действий (поэтапно)

### Этап 1: Безопасность и чистота (день 1, ~2 часа)

1. **start.sh:** `--host 0.0.0.0` → `--host 127.0.0.1` (R3, 5 мин)
2. **requirements.txt:** удалить `ollama`, `openai`, `google-generativeai`, `jinja2` — проверить, что всё работает через httpx (R2, 15 мин)
3. **database.py:** удалить `import json`, `import os` (если не используется) (R5, 5 мин)
4. **analyzer.py:** удалить `from models import Verdict` (только `Job`) (R5, 5 мин)
5. **analyzer.py:** удалить `provider`-параметр из `update_verdict()` (R10, 5 мин)
6. **database.py:** удалить `_OLD_CATEGORY_MAP` и упростить `_safe_category()` (R11, 5 мин)
7. **database.py:** оптимизировать `get_stats()` в один запрос с CASE WHEN (R9, 15 мин)
8. **database.py:** добавить индексы на `analyzed`, `verdict`, `category`, `scraped_at` при создании таблицы (R8, 30 мин)
9. **main.py + index.html:** добавить лимит на `get_unanalyzed_jobs()` (R18, 15 мин)

### Этап 2: Рефакторинг состояния (день 1–2, ~2 часа)

1. **main.py:** создать dataclass `AppState` (R1, 30 мин)
2. Перенести 7 глобальных переменных в `AppState`
3. Убрать дублирование `_is_scraping`/`_scrape_running` (R19, 15 мин)
4. Заменить обращение к глобальным переменным через `app.state` или зависимость `get_state()`
5. Разбить `_run_analysis()` на `_process_batch()` (R12, 1 час)

### Этап 3: Абстракция scraper'ов (день 2–3, ~3 часа)

1. **BaseScraper:** добавить поле `seen: set[str]` базового класса + метод `_make_job()` (R4, 1 час)
2. **BaseScraper:** добавить `_scrape_urls(urls, parse_item_callback)` — шаблонный метод (R4, 1 час)
3. Переписать каждый scraper: убрать дублирование `seen`, `print`, конструирование `Job` (R4, 1 час)
4. **BaseAnalyzer:** добавить `_build_prompt()` и `_error_result()` (R6, 30 мин)
5. Сократить каждый анализатор на ~15 строк (R6, 30 мин)

### Этап 4: Фронтенд и комментарии (день 3, ~2 часа)

1. **JS:** вынести общий poll-цикл в `pollUntilDone()` (R7, 30 мин)
2. **JS:** вынести в отдельный `static/app.js`, подключить через `<script src="/static/app.js">` (R15, 1 час)
3. Добавить комментарии в ключевые места (R17, 30 мин):
   - Пояснение `BATCH_SIZE=10` и `asyncio.gather` в `_run_analysis()`
   - Пояснение Upwork fallback link-экстракции
   - Пояснение JSON-LD парсинга Toptal
   - Пояснение детекции закрытых заказов WorkConnect

### Этап 5: Опционально (день 4, ~2 часа)

1. **POST /api/settings:** добавить Pydantic-модель `SettingsUpdate` (R16, 30 мин)
2. **Разбить `_scrape_listing()`** (R13, 30 мин)
3. Вернуться к `check_provider_available()` — или использовать, или удалить (R14, 15 мин)

---

## 5. Список файлов для дефрагментации

### `main.py` (327 строк) — Кандидат на дефрагментацию

**Проблема:** Смешивает lifespan, background-задачи, 7 эндпоинтов, глобальное состояние и логику анализа.

**Предлагаемая новая структура:**
```
main.py                    → только lifespan + app = FastAPI() + импорты роутеров
routes/
├── __init__.py             → пустой
├── jobs.py                 → GET /api/jobs, GET /api/stats
├── analysis.py             → POST /api/analyze
├── scrape.py               → POST /api/refresh
├── settings.py             → GET/POST /api/settings
└── status.py               → GET /api/status, GET /api/log
services/
├── __init__.py
├── scraper_service.py      → _run_scrape(), логика парсинга
├── analysis_service.py     → _run_analysis(), _analyze_one_job(), AppState
└── state.py                → dataclass AppState
```

**Примечание:** Для проекта на 327 строк полное выделение роутеров избыточно. Достаточно вынести `AppState` в отдельный модуль и background-задачи в `services/`. Роуты можно оставить в main.py, так как их всего 7 и каждый короткий.

### `analyzer.py` (331 строк) — Кандидат на дефрагментацию

**Проблема:** Содержит 3 реализации анализатора, фабрику, health-check для каждого провайдера, промпты, парсинг ответа.

**Предлагаемая новая структура:**
```
analyzer.py                  → BaseAnalyzer + _parse_response + _extract_result
analyzer_providers/
├── __init__.py              → PROVIDER_MAP, PROVIDER_NAMES, get_analyzer
├── ollama.py                → OllamaAnalyzer, check_ollama_available
├── deepseek.py              → DeepSeekAnalyzer, check_deepseek_available
└── gemini.py                → GeminiAnalyzer, check_gemini_available
```

**Примечание:** Каждый анализатор ~50–80 строк. Выделение оправдано, если планируется добавление новых провайдеров (как указано в ROADMAP.md).

### `templates/index.html` (528 строк) — Кандидат на дефрагментацию

**Проблема:** ~330 строк CSS + ~330 строк JavaScript в одном файле. JS содержит 3 дублирующихся poll-цикла.

**Предлагаемая новая структура:**
```
templates/
├── index.html               → только HTML (~150 строк) + ссылки на CSS/JS
static/
├── styles.css               → CSS (вынести из <style>)
└── app.js                   → JavaScript (вынести из <script>)
```

**Примечание:** Это также позволит включить кэширование статики браузером. FastAPI нужно добавить `StaticFiles` mount.

### `scrapers/base.py` (127 строк) — Улучшение без увеличения размера

**Что добавить:**
- Поле `seen: set[str] = field(default_factory=set)` для дедупликации
- Метод `_make_job(...)` для единообразного конструирования Job
- Метод `_scrape_urls(urls, parser)` — шаблонный обход URL
- Логирование через `logger` вместо `print`

### `database.py` (207 строк) — Улучшение без увеличения размера

**Что изменить:**
- Оптимизировать `get_stats()` в один запрос
- Добавить индексы в `init_db()`
- Удалить `_OLD_CATEGORY_MAP` и упростить `_safe_category()`
- Удалить мёртвый параметр `provider` из `update_verdict()`

---

## 6. Дополнительные улучшения

### Производительность

1. **Кэширование `get_stats()`:** Статистика редко меняется (только после scrape/analyze). Можно кэшировать на 5 секунд в `AppState` и обновлять только после изменений.

2. **Параллельный парсинг:** Сейчас scraper'ы запускаются последовательно (main.py, строка 81). Для 6 площадок с задержками 1–3с это ~20–30 секунд. Можно запускать через `asyncio.gather(*[ScraperClass().scrape() for ScraperClass in ALL_SCRAPERS])`.

3. **Лимит на `get_unanalyzed_jobs()`:** Если БД содержит 10K записей, `get_unanalyzed_jobs()` выгрузит все неанализированные (потенциально тысячи) в память. Добавить `LIMIT 100` — анализировать пачками по 100 (сейчас batch по 10, но это параллельно; всё равно защита от бесконечного потребления памяти).

4. **Лимит `BATCH_SIZE`:** 10 параллельных LLM-запросов могут привести к rate limiting у DeepSeek/Gemini. Стоит сделать BATCH_SIZE настраиваемым через .env.

### Читаемость

1. **PEP 8:** В целом соблюдается. Замечания:
   - database.py строка 25: пустая строка между `_safe_category()` и `init_db()` — лишняя
   - main.py строка 10: длинный import `HTMLResponse, JSONResponse` — можно перенести на отдельные строки
   - `print()` вместо `logger.info()` в scraper'ах — неконсистентно с main.py, где используется `logger.error()`

2. **Консистентность языка:** Русские докстринги в main.py (строки 70, 103), английские в database.py и analyzer.py. Стоит выбрать один язык и привести всё к нему.

3. **Типизация:** В `get_all_jobs()` (database.py, строки 102–107) параметры имеют строковые значения "all", "0", "1" — лучше использовать Union типов: `category: Optional[str] = None`, `analyzed: Optional[bool] = None`.

4. **Магические числа:** `description[:600]` и `description[:800]` в разных scraper'ах — нет единой константы для максимальной длины описания.

### Тестируемость

1. **Нет тестов.** Весь проект — ни одного теста (ни unit, ни integration). Для scraper'ов это сложно (зависимость от HTTP), но analyzer и database можно тестировать с моками.

2. **Глобальные переменные** (пункт C1) — главное препятствие для тестирования. После инкапсуляции в `AppState` тесты смогут создавать изолированный экземпляр состояния.

3. **`database.py`** использует глобальный `DB_PATH` — нельзя подменить на `test.db` без перезаписи переменной окружения. Стоит сделать `init_db()` принимающим путь как параметр с fallback на `os.getenv()`.

### Несоответствия README / ROADMAP

1. **README.md:**
   - Утверждает, что поддерживаются API-эндпоинты для настроек — OK.
   - Упоминает `jinja2` в tech stack — на самом деле не используется.
   - Упоминает `ollama` Python-библиотеку — на самом деле httpx.
   - Не упоминает, что приложение доступно по сети (0.0.0.0).
   - Все API-эндпоинты перечислены корректно.

2. **ROADMAP.md:**
   - Phase 2: упоминает "NLP budget parsing" — в `parse_budget()` уже есть regex, это не NLP.
   - Phase 3: "Deployment to Vercel/Next.js + Railway" — текущая архитектура (FastAPI + SQLite) несовместима с Vercel (serverless) и требует миграции на PostgreSQL/Neon.
   - Не упоминает текущие проблемы (дефрагментация, тесты, индексы), которые стоит решить до Phase 3.

---

## Итого по файлам

| Файл | Строк | Статус | Действие |
|------|-------|--------|----------|
| main.py | 327 | Дефрагментация | Вынести глобальное состояние + background-задачи |
| analyzer.py | 331 | Дефрагментация | Вынести общего предка анализаторов, убрать дублирование |
| templates/index.html | 528 | Дефрагментация | Вынести JS и CSS в static/ |
| scrapers/base.py | 127 | Доработка | Добавить шаблонные методы |
| scrapers/oferia.py | 81 | Упрощение | ~50% кода уйдёт в base.py |
| scrapers/useme.py | 72 | Упрощение | ~40% кода уйдёт в base.py |
| scrapers/workconnect.py | 87 | Упрощение | ~45% кода уйдёт в base.py |
| scrapers/zleca.py | 80 | Упрощение | ~50% кода уйдёт в base.py |
| scrapers/upwork.py | 223 | Упрощение | Вынести _scrape_by_selectors / _scrape_by_links |
| scrapers/toptal.py | 144 | Упрощение | ~30% кода уйдёт в base.py |
| database.py | 207 | Доработка | Индексы, оптимизация get_stats, удаление мусора |
| models.py | 55 | Не требуется | Чисто |
| scrapers/__init__.py | 15 | Не требуется | Чисто |
| requirements.txt | 11 | Очистка | -4 пакета |
| start.sh | 29 | Исправление | 0.0.0.0 → 127.0.0.1 |

---

*Аудит проведён без внесения изменений в код. Все рекомендации описательные. Ни один файл не был модифицирован.*
