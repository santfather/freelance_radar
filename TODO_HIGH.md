# TODO: Высокий приоритет

> Основано на аудите AUDIT.md. Выполнять **группами строго по порядку**.
> После каждой группы — обязательный прогон тестов.
> После каждого пункта — дефенсивный коммит (`git add -A && git commit -m "checkpoint: ..."`).

---

## Группа 1: Быстрая чистка (безопасность + мусор)

> Независимые правки, не затрагивают логику приложения. ~20 минут.
> После группы — **Тесты 1**.

### □ 1.1 — R3: Сменить хост в start.sh

**Файл:** `start.sh`, строка 29

```bash
# Было:
uvicorn main:app --port 8099 --host 0.0.0.0
# Стало:
uvicorn main:app --port 8099 --host 127.0.0.1
```

---

### □ 1.2 — R2: Удалить неиспользуемые зависимости

**Файл:** `requirements.txt`

Удалить строки:
- `ollama==0.2.1`
- `openai==1.30.0`
- `google-generativeai==0.7.0`
- `jinja2==3.1.4`

Проверить `rg "ollama|openai|google|jinja2" --type py` — ни один не импортируется.

---

### □ 1.3 — R5: Удалить неиспользуемые импорты

**Файлы:**
- `database.py` строка 3: удалить `import json`
- `analyzer.py` строка 10: `from models import Job, Verdict` → `from models import Job`

---

### □ 1.4 — R10: Удалить мёртвый параметр provider из update_verdict()

**Файл:** `database.py`, строка 91

```python
# Было:
async def update_verdict(job: Job, provider: str = ""):
# Стало:
async def update_verdict(job: Job):
```

Проверить вызов в `main.py` строка 141 — передаётся только `job`.

---

### □ 1.5 — R11: Удалить _OLD_CATEGORY_MAP

**Файл:** `database.py`, строки 12–14

1. Удалить словарь `_OLD_CATEGORY_MAP`
2. Упростить `_safe_category()`:
```python
def _safe_category(name: str) -> Category:
    try:
        return Category(name)
    except ValueError:
        return Category.OTHER_IT
```
3. Удалить миграцию строк 58–60:
```python
# Удалить целиком:
await db.execute(
    "UPDATE jobs SET category='CMS' WHERE category='CMS / WordPress'"
)
```

---

### ✅ Тесты группы 1

```bash
cd /Users/vladislavkovalenko/Projects/agent-workspace/freelance-radar

# 1. Импорты
python -c "import main; import database; import analyzer; import models; from scrapers import ALL_SCRAPERS; print('[OK] Все импорты')"

# 2. Зависимости
pip install -r requirements.txt  # проверить, что установка проходит
pip list 2>/dev/null | rg -i "ollama|openai|google-generativeai|jinja2" && echo "⚠️  Есть лишние пакеты" || echo "[OK] Лишних пакетов нет"

# 3. start.sh
grep "host 0.0.0.0" start.sh && echo "⚠️  Хост не исправлен" || echo "[OK] Хост 127.0.0.1"

# 4. Мёртвый параметр
rg "async def update_verdict" database.py | rg "provider" && echo "⚠️  Параметр остался" || echo "[OK] Параметр удалён"

# 5. _OLD_CATEGORY_MAP
rg "_OLD_CATEGORY_MAP" database.py && echo "⚠️  Маппинг остался" || echo "[OK] Маппинг удалён"

# Коммит
git add -A && git commit -m "checkpoint: high group 1 — cleanup & security"
```

---

## Группа 2: База данных (улучшение persistence-слоя)

> Только `database.py`. Независимо от состояния в main.py. ~50 минут.
> После группы — **Тесты 2**.

### □ 2.1 — R9: Оптимизировать get_stats() в один SQL-запрос

**Файл:** `database.py`, строки 159–167

```python
async def get_stats() -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("""
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN analyzed=1 THEN 1 ELSE 0 END) AS analyzed,
                SUM(CASE WHEN verdict='TAKE' THEN 1 ELSE 0 END) AS take
            FROM jobs
        """) as c:
            row = await c.fetchone()
            return {"total": row[0], "analyzed": row[1], "take": row[2]}
```

---

### □ 2.2 — R8: Добавить индексы в SQLite

**Файл:** `database.py`, функция `init_db()`

После создания таблицы `jobs` (после `await db.commit()` на строках 60–61, или добавить в то же `async with`) добавить:

```sql
CREATE INDEX IF NOT EXISTS idx_jobs_analyzed ON jobs(analyzed);
CREATE INDEX IF NOT EXISTS idx_jobs_verdict ON jobs(verdict);
CREATE INDEX IF NOT EXISTS idx_jobs_category ON jobs(category);
CREATE INDEX IF NOT EXISTS idx_jobs_scraped_at ON jobs(scraped_at);
```

---

### □ 2.3 — R18: Добавить LIMIT в get_unanalyzed_jobs()

**Файл:** `database.py`, строка 134

```python
# Было:
async with db.execute("SELECT * FROM jobs WHERE analyzed=0") as cur:
# Стало:
async with db.execute("SELECT * FROM jobs WHERE analyzed=0 LIMIT 100") as cur:
```

---

### ✅ Тесты группы 2

```bash
cd /Users/vladislavkovalenko/Projects/agent-workspace/freelance-radar

# 1. Пересоздать БД с новыми индексами
rm -f radar.db
python -c "
import asyncio
from database import init_db
asyncio.run(init_db())
print('[OK] БД создана')
"

# 2. Проверить индексы
sqlite3 radar.db '.indices jobs'

# 3. Проверить get_stats
python -c "
import asyncio
from database import get_stats
s = asyncio.run(get_stats())
assert 'total' in s and 'analyzed' in s and 'take' in s
print(f'[OK] get_stats: {s}')
"

# 4. Импорты
python -c "import database; print('[OK] database.py без ошибок')"

# Коммит
git add -A && git commit -m "checkpoint: high group 2 — database improvements"
```

---

## Группа 3: Состояние приложения (AppState)

> Главное архитектурное изменение — отказ от глобальных переменных. ~1.5 часа.
> После группы — **Тесты 3**.

### □ 3.1 — R1+R19: Инкапсулировать глобальное состояние в AppState

**Шаг 1:** Создать директорию и файл `services/state.py`:

```python
from dataclasses import dataclass, field

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

**Шаг 2:** В `main.py` — создать экземпляр в lifespan и зависимость:

```python
from services.state import AppState
# ...внутри lifespan:
app.state.app_state = AppState()

# Функция-зависимость:
from fastapi import Request
async def get_state(request: Request) -> AppState:
    return request.app.state.app_state
```

**Шаг 3:** Везде, где используются `global _scrape_running`, `_analyze_log` и т.д.:
- Удалить все `global`-объявления
- Передавать `state: AppState` аргументом в `_run_scrape(state)`, `_run_analysis(provider, state)`
- В эндпоинтах использовать `Depends(get_state)`

**Шаг 4:** Убрать дублирование `_is_scraping`/`_scrape_running` (R19). Везде использовать `state.scraping`.

---

### □ 3.2 — R12: Разбить _run_analysis() на подфункции

**Файл:** `main.py`, строки 102–156

Выделить:

```python
BATCH_SIZE = 10

async def _run_analysis(provider: str, state: AppState):
    if state.analyzing:
        return
    state.analyzing = True
    _init_analysis(state, provider)
    try:
        analyzer = get_analyzer(provider)
        await _process_all_batches(analyzer, state)
    except Exception as e:
        state.analyze_log.append(f"❌ Ошибка анализа: {e}")
        logger.error(f"Analysis error: {e}")
    finally:
        _finalize_analysis(state)

async def _process_all_batches(analyzer, state: AppState):
    unanalyzed = await get_unanalyzed_jobs()
    state.analyze_total = len(unanalyzed)
    for batch_start in range(0, len(unanalyzed), BATCH_SIZE):
        batch = unanalyzed[batch_start:batch_start + BATCH_SIZE]
        await _process_batch(analyzer, batch, state)

async def _process_batch(analyzer, batch, state: AppState):
    tasks = [_analyze_one_job(analyzer, job) for job in batch]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    for job, result in zip(batch, results):
        if isinstance(result, Exception):
            state.analyze_log.append(f"  ❌ Ошибка: {result}")
            logger.error(f"Analysis error for job {job.id}: {result}")
        else:
            await update_verdict(job)
            state.analyze_log.append(f"  → {job.verdict.value}")
        state.analyze_progress += 1
```

Функции-помощники:
```python
def _init_analysis(state: AppState, provider: str):
    state.analyze_log = [f"▶ Анализ запущен (провайдер: {PROVIDER_NAMES.get(provider, provider)})..."]
    state.analyze_progress = 0
    state.analyze_total = 0

def _finalize_analysis(state: AppState):
    state.analyzing = False
    state.analyze_provider = ""
    state.analyze_log.append(f"✅ Проанализировано {state.analyze_total} заказов")
```

---

### ✅ Тесты группы 3

```bash
cd /Users/vladislavkovalenko/Projects/agent-workspace/freelance-radar

# 1. Импорты (включая новый модуль)
python -c "
from services.state import AppState
s = AppState()
assert s.scraping == False
assert s.analyze_log == []
print('[OK] AppState dataclass работает')
"

python -c "
import main; import database; import analyzer; import models
from scrapers import ALL_SCRAPERS
print('[OK] Все импорты — без ошибок')
"

# 2. Smoke-тест эндпоинтов (приложение должно быть запущено)
uvicorn main:app --port 8099 --host 127.0.0.1 &
PID=$!
sleep 3

echo "=== GET /api/status ==="
curl -s http://localhost:8099/api/status | python -m json.tool

echo "=== GET /api/stats ==="
curl -s http://localhost:8099/api/stats | python -m json.tool

echo "=== GET /api/settings ==="
curl -s http://localhost:8099/api/settings | python -m json.tool

echo "=== GET /api/jobs ==="
curl -s "http://localhost:8099/api/jobs" | python -c "import sys,json; d=json.load(sys.stdin); print(f'Jobs: {len(d)}')"

echo "=== POST /api/settings ==="
curl -s -X POST http://localhost:8099/api/settings \
  -H "Content-Type: application/json" \
  -d '{"provider": "ollama"}' | python -m json.tool

echo "=== POST /api/refresh ==="
curl -s -X POST http://localhost:8099/api/refresh | python -m json.tool

sleep 5

echo "=== POST /api/analyze (без провайдера — тест только старта) ==="
curl -s -X POST http://localhost:8099/api/analyze | python -m json.tool

kill $PID 2>/dev/null

# 3. Нет глобальных переменных
rg "global _is_scraping|global _is_analyzing|global _scrape_running|global _analyze_running" main.py && echo "⚠️  Глобальные переменные остались" || echo "[OK] Глобальные переменные удалены"

# Коммит
git add -A && git commit -m "checkpoint: high group 3 — AppState & decomposition"
```

---

## Группа 4: Рефакторинг scraper'ов и анализаторов

> Две параллельных подгруппы: scraper'ы (R4+R13) и анализаторы (R6). ~3 часа.
> После группы — **Тесты 4**.

### □ 4.1 — R4: Вынести общий шаблон scraper'ов в BaseScraper

**Файлы:** `scrapers/base.py`, `oferia.py`, `useme.py`, `workconnect.py`, `zleca.py`, `upwork.py`, `toptal.py`

**В `BaseScraper` добавить:**

```python
from dataclasses import field

class BaseScraper(ABC):
    source_name: str = ""
    seen: set[str] = field(default_factory=set)

    def _make_job(self, title: str, url: str, description: str = "",
                  budget_raw: str = "", budget_min: int = None, budget_max: int = None,
                  posted_at: str = "") -> Job:
        return Job(
            id=make_id(title, self.source_name),
            title=title,
            description=description,
            url=url,
            source=self.source_name,
            category=detect_category(title, description),
            budget_raw=budget_raw,
            budget_min=budget_min,
            budget_max=budget_max,
            posted_at=posted_at,
        )
```

**Каждый scraper:** убрать `seen: set[str] = set()`, заменить конструирование `Job(...)` на `self._make_job(...)`, убрать `print(...scraped...)`.

**Для `oferia`, `useme`, `workconnect`, `zleca`:** дополнительно вынести общий цикл по URL.

---

### □ 4.2 — R13: Разбить _scrape_listing() в Upwork

**Файл:** `upwork.py`, строки 53–119

```python
async def _scrape_listing(self, url: str, seen: set[str]) -> list[Job]:
    resp = await self._get(url)
    if not resp:
        return []
    soup = BeautifulSoup(resp.text, "lxml")

    results = self._scrape_by_selectors(soup, seen)
    if not results:
        results = self._scrape_by_links(soup, seen)
    return results

def _scrape_by_selectors(self, soup, seen: set[str]) -> list[Job]:
    """Парсинг через data-test атрибуты."""
    ...

def _scrape_by_links(self, soup, seen: set[str]) -> list[Job]:
    """Fallback: поиск любых ссылок /jobs/ или /freelance-jobs/."""
    ...
```

---

### □ 4.3 — R6: Вынести общий код анализаторов в BaseAnalyzer

**Файл:** `analyzer.py`

**Добавить в `BaseAnalyzer`:**

```python
class BaseAnalyzer(ABC):
    @abstractmethod
    async def analyze(self, title: str, category: str, budget: str, description: str) -> dict:
        ...

    def _build_prompt(self, title: str, category: str, budget: str, description: str) -> str:
        return USER_TEMPLATE.format(
            title=title, category=category,
            budget=budget or "not specified",
            description=description[:600] if description else "no description",
        )

    def _error_result(self, error_msg: str) -> dict:
        return {
            "verdict": "UNKNOWN",
            "reason": error_msg,
            "complexity": 0,
            "estimated_hours": 0,
        }
```

**Заменить дублирование** в `OllamaAnalyzer`, `DeepSeekAnalyzer`, `GeminiAnalyzer`:
- `USER_TEMPLATE.format(...)` → `self._build_prompt(...)`
- Словарь-заглушка в `except` → `self._error_result(...)`

---

### ✅ Тесты группы 4

```bash
cd /Users/vladislavkovalenko/Projects/agent-workspace/freelance-radar

# 1. Импорты
python -c "
import main; import database; import analyzer; import models
from scrapers import ALL_SCRAPERS
from scrapers.base import BaseScraper, make_id, detect_category, parse_budget
print('[OK] Все импорты — без ошибок')
"

# 2. Проверить, что все scraper'ы инициализируются
python -c "
from scrapers import ALL_SCRAPERS
for cls in ALL_SCRAPERS:
    s = cls()
    assert s.source_name != '', f'{cls.__name__} без source_name'
    print(f'  ✓ {cls.__name__}: source_name={s.source_name}')
print('[OK] Все scraper\'ы инициализируются')
"

# 3. Проверить фабрику анализаторов
python -c "
from analyzer import get_analyzer, PROVIDER_MAP
for name in PROVIDER_MAP:
    a = get_analyzer(name)
    print(f'  ✓ {name}: {type(a).__name__}')
print('[OK] Все анализаторы создаются')
"

# 4. Smoke-тест приложения
uvicorn main:app --port 8099 --host 127.0.0.1 &
PID=$!
sleep 3

curl -s http://localhost:8099/api/status | python -m json.tool
curl -s http://localhost:8099/api/stats | python -m json.tool
curl -s http://localhost:8099/api/settings | python -m json.tool
curl -s "http://localhost:8099/api/jobs" | python -c "import sys,json; d=json.load(sys.stdin); print(f'Jobs: {len(d)}')"

kill $PID 2>/dev/null

# Коммит
git add -A && git commit -m "checkpoint: high group 4 — scrapers & analyzers refactor"
```

---

## Финальный smoke-тест всего HIGH

```bash
cd /Users/vladislavkovalenko/Projects/agent-workspace/freelance-radar

# Полная перепроверка
python -c "
import main; import database; import analyzer; import models
from scrapers import ALL_SCRAPERS
from services.state import AppState
print('[OK] Полный цикл импортов')
"

# Запуск
uvicorn main:app --port 8099 --host 127.0.0.1 &
PID=$!
sleep 3

echo "=== ALL ENDPOINTS ==="
for ep in status stats settings jobs log; do
  code=$(curl -s -o /dev/null -w "%{http_code}" "http://localhost:8099/api/$ep")
  echo "  GET /api/$ep → $code"
done

echo "=== POST /api/settings ==="
curl -s -X POST http://localhost:8099/api/settings -H "Content-Type: application/json" -d '{"provider": "ollama"}' | python -m json.tool

echo "=== POST /api/refresh ==="
curl -s -X POST http://localhost:8099/api/refresh | python -m json.tool

echo "=== POST /api/analyze ==="
curl -s -X POST http://localhost:8099/api/analyze | python -m json.tool

kill $PID 2>/dev/null

# Проверка, что нет глобальных переменных
rg "global _" main.py && echo "⚠️  Есть global переменные" || echo "[OK] global нет"

# Проверка start.sh
grep "host 127.0.0.1" start.sh && echo "[OK] Хост 127.0.0.1"

echo ""
echo "=== HIGH PRIORITY DONE ==="
```
