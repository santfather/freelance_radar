# TODO: Низкий приоритет

> Выполнять **после TODO_HIGH.md и TODO_MEDIUM.md**.
> Группы не зависят друг от друга — можно в любом порядке.
> После каждой группы — обязательный прогон тестов.
> После каждого пункта — дефенсивный коммит.

---

## Группа 1: Комментарии и чистота кода

> Добавление пояснений в нетривиальные места + удаление мусора. ~40 минут.
> После группы — **Тесты 1**.

### □ 1.1 — R17: Добавить комментарии в ключевые места

**Файлы:** `main.py`, `upwork.py`, `toptal.py`, `workconnect.py`

**main.py** (возле BATCH_SIZE и цикла asyncio.gather):
```python
BATCH_SIZE = 10  # параллельных LLM-запросов; превышение может вызвать rate limiting

# Обрабатываем пачками по BATCH_SIZE — asyncio.gather отправляет запросы
# параллельно, что ускоряет анализ. return_exceptions=True не даёт одному
# сбою обрушить всю пачку.
```

**upwork.py** (перед link-based fallback):
```python
# Fallback: если селекторы не сработали (Upwork меняет вёрстку),
# ищем любые ссылки /jobs/ или /freelance-jobs/ и пытаемся извлечь
# описание из родительского контейнера.
```

**toptal.py** (перед JSON-LD разбором):
```python
# JSON-LD может содержать как одиночный JobPosting, так и ItemList
# со списком вакансий. Проверяем оба случая — @type может быть
# "JobPosting" (прямая) или "ItemList" (список с entries).
```

**workconnect.py** (перед проверкой статуса):
```python
# Закрытые заказы помечаются польскими фразами "zakończone" или
# "zamknięte" в div.t-12-medium. Используем частичное совпадение,
# так как точный текст может меняться (падежи, окончания).
```

**upwork.py, toptal.py** (где `parse_budget(description + ...)`):
```python
# На этой площадке бюджет отсутствует в отдельном поле,
# поэтому ищем его числами в тексте описания и заголовка.
```

---

### □ 1.2 — A6: Удалить избыточные docstring и разделители

**Файлы и строки:**
- `analyzer.py`, строка 48: удалить `"""Абстрактный анализатор заказов."""`
- `main.py`, строка 70: удалить `"""Только парсинг (без анализа)."""`
- `database.py`, строка 64: удалить `# ── Jobs ──`
- `database.py`, строка 184: удалить `# ── Settings ──`

---

### ✅ Тесты группы 1

```bash
cd /Users/vladislavkovalenko/Projects/agent-workspace/freelance-radar

# 1. Проверить, что комментарии появились в ключевых местах
echo "=== Проверка комментариев ==="
rg "BATCH_SIZE" main.py && echo "[OK] BATCH_SIZE с комментарием" || echo "⚠️  Нет комментария BATCH_SIZE"
rg "Fallback" upwork.py && echo "[OK] Fallback комментарий" || echo "⚠️  Нет fallback комментария"
rg "JSON-LD" toptal.py && echo "[OK] JSON-LD комментарий" || echo "⚠️  Нет JSON-LD комментария"
rg "zakończon" workconnect.py && echo "[OK] WorkConnect комментарий" || echo "⚠️  Нет workconnect комментария"

# 2. Docstring удалены
rg "Абстрактный анализатор заказов" analyzer.py && echo "⚠️  Docstring остался" || echo "[OK] Анализатор docstring удалён"
rg "Только парсинг \(без анализа\)" main.py && echo "⚠️  Docstring остался" || echo "[OK] main docstring удалён"
rg "# ── Jobs ──" database.py && echo "⚠️  Разделитель остался" || echo "[OK] Разделитель Jobs удалён"
rg "# ── Settings ──" database.py && echo "⚠️  Разделитель остался" || echo "[OK] Разделитель Settings удалён"

# 3. Импорты
python -c "
import main; import database; import analyzer; import models
from scrapers import ALL_SCRAPERS
print('[OK] Все импорты')
"

# Коммит
git add -A && git commit -m "checkpoint: low group 1 — comments & cleanup"
```

---

## Группа 2: Чистота кода (PEP 8 + типизация)

> Косметические улучшения без изменения логики. ~45 минут.
> После группы — **Тесты 2**.

### □ 2.1 — PEP 8 и консистентность

**Файлы:** `main.py`, `database.py`, `scrapers/*.py`

1. **database.py, строка 25:** Удалить лишнюю пустую строку между `_safe_category()` и `init_db()`.

2. **scrapers/*.py:** Заменить `print(f"[{source}] ...")` на `logger` для консистентности с main.py:
   - В `scrapers/base.py` добавить: `logger = logging.getLogger("freelance-radar.scraper")`
   - `print(f"[{self.source_name}] fetch error {url}: {e}")` → `logger.warning(...)`
   - `print(f"[{self.source_name}] session fetch error: {e}")` → `logger.warning(...)`

3. **Вынести константу MAX_DESC_LENGTH:**
   - В `scrapers/base.py` или `models.py` добавить: `MAX_DESC_LENGTH = 600`
   - Заменить все `[:600]` и `[:800]` в scraper'ах и analyzer.py на `[:MAX_DESC_LENGTH]`

---

### □ 2.2 — Типизация get_all_jobs()

**Файл:** `database.py`, строки 102–107

```python
async def get_all_jobs(
    category: Optional[str] = None,
    verdict: Optional[str] = None,
    analyzed: Optional[bool] = None,
    sort: str = "desc",
) -> list[dict]:
```

Обновить логику проверки:
```python
if category:
    where.append("category = ?")
    params.append(category)
if verdict:
    where.append("verdict = ?")
    params.append(verdict.upper())
if analyzed is not None:
    where.append("analyzed = ?")
    params.append(1 if analyzed else 0)
```

**В main.py, строка 230** — изменить вызов:
```python
async def jobs(
    category: str = Query(default="all"),
    verdict: str = Query(default="all"),
    analyzed: str = Query(default="all"),
    sort: str = Query(default="desc"),
):
    cat_arg = category if category != "all" else None
    verdict_arg = verdict if verdict != "all" else None
    analyzed_arg = None if analyzed == "all" else (analyzed == "1")
    rows = await get_all_jobs(category=cat_arg, verdict=verdict_arg, analyzed=analyzed_arg, sort=sort)
    return JSONResponse(rows)
```

---

### ✅ Тесты группы 2

```bash
cd /Users/vladislavkovalenko/Projects/agent-workspace/freelance-radar

# 1. PEP 8
ruff check . 2>/dev/null && echo "[OK] Ruff чист" || echo "⚠️  Есть замечания ruff"

# 2. print → logger
rg "print\(f\"\[" scrapers/base.py && echo "⚠️  Ещё есть print" || echo "[OK] print заменён на logger"

# 3. MAX_DESC_LENGTH
rg "MAX_DESC_LENGTH" scrapers/base.py || rg "MAX_DESC_LENGTH" models.py && echo "[OK] Константа есть" || echo "⚠️  MAX_DESC_LENGTH не найдена"

# 4. Типизация
python -c "
import asyncio
from database import get_all_jobs
r = asyncio.run(get_all_jobs(category=None, verdict=None, analyzed=None, sort='desc'))
print(f'[OK] get_all_jobs() без фильтров: {len(r)} записей')
r2 = asyncio.run(get_all_jobs(category='Web App'))
print(f'[OK] get_all_jobs(category=\"Web App\"): {len(r2)} записей')
"

# 5. Smoke-тест приложения
uvicorn main:app --port 8099 --host 127.0.0.1 &
PID=$!
sleep 3

echo "=== Фильтры jobs ==="
curl -s "http://localhost:8099/api/jobs?analyzed=1" | python -c "import sys,json; d=json.load(sys.stdin); print(f'analyzed=1: {len(d)}')"
curl -s "http://localhost:8099/api/jobs?analyzed=0" | python -c "import sys,json; d=json.load(sys.stdin); print(f'analyzed=0: {len(d)}')"
curl -s "http://localhost:8099/api/jobs?category=Web+App" | python -c "import sys,json; d=json.load(sys.stdin); print(f'Web App: {len(d)}')"
curl -s "http://localhost:8099/api/jobs?verdict=TAKE" | python -c "import sys,json; d=json.load(sys.stdin); print(f'TAKE: {len(d)}')"

kill $PID 2>/dev/null

# Коммит
git add -A && git commit -m "checkpoint: low group 2 — PEP8 & typing"
```

---

## Группа 3: Опциональные улучшения

> Независимые улучшения, каждое опционально. ~45 минут.
> После группы — **Тесты 3**.

### □ 3.1 — S2: API-ключ Gemini в заголовке (опционально)

**Файл:** `analyzer.py`, строка 267–268

Проверить, принимает ли Gemini API ключ в заголовке `X-Goog-Api-Key`:

```python
headers = {"X-Goog-Api-Key": self.api_key}
resp = await client.post(
    f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent",
    json=payload,
    headers=headers,
    timeout=90,
)
```

Если API не поддерживает заголовок — оставить как есть (через `?key=`).

---

### □ 3.2 — Кэширование get_stats()

**Файлы:** `services/state.py`, `main.py`

В `AppState` добавить:
```python
stats_cache: dict | None = None
stats_cache_time: float = 0
STATS_CACHE_TTL: float = 5.0  # секунд
```

В `main.py` в эндпоинте `/api/stats`:
```python
import time

async def stats(state: AppState = Depends(get_state)):
    now = time.time()
    if state.stats_cache and (now - state.stats_cache_time) < state.STATS_CACHE_TTL:
        data = state.stats_cache.copy()
    else:
        data = await get_stats()
        state.stats_cache = data
        state.stats_cache_time = now
    # ...остальная логика...
```

Инвалидировать кэш в `_run_scrape` и `_run_analysis`:
```python
state.stats_cache = None
```

---

### ✅ Тесты группы 3

```bash
cd /Users/vladislavkovalenko/Projects/agent-workspace/freelance-radar

# 1. Импорты
python -c "
import main; import database; import analyzer; import models
from services.state import AppState
s = AppState()
s.stats_cache = {'total': 5}
print(f'[OK] stats_cache в AppState: {s.stats_cache}')
"

# 2. Smoke-тест
uvicorn main:app --port 8099 --host 127.0.0.1 &
PID=$!
sleep 3

echo "=== STATS (проверить, что работает) ==="
curl -s http://localhost:8099/api/stats | python -m json.tool

echo "=== ALL ENDPOINTS ==="
for ep in status stats settings jobs; do
  code=$(curl -s -o /dev/null -w "%{http_code}" "http://localhost:8099/api/$ep")
  echo "  GET /api/$ep → $code"
done

echo "=== Gemini key check ==="
rg "X-Goog-Api-Key" analyzer.py && echo "[OK] Gemini key в заголовке" || echo "[OK] Gemini key через ?key= (стандарт)"

kill $PID 2>/dev/null

# Коммит
git add -A && git commit -m "checkpoint: low group 3 — optional improvements"
```

---

## Финальный smoke-тест всего LOW

```bash
cd /Users/vladislavkovalenko/Projects/agent-workspace/freelance-radar

# Полная проверка
python -c "
import main; import database; import analyzer; import models
from scrapers import ALL_SCRAPERS
from services.state import AppState
from models import SettingsUpdate
print('[OK] Все импорты проекта')
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

echo "=== FILTERED JOBS ==="
curl -s "http://localhost:8099/api/jobs?analyzed=1" | python -c "import sys,json; d=json.load(sys.stdin); print(f'  analyzed=1: {len(d)}')"
curl -s "http://localhost:8099/api/jobs?analyzed=0" | python -c "import sys,json; d=json.load(sys.stdin); print(f'  analyzed=0: {len(d)}')"
curl -s "http://localhost:8099/api/jobs?category=Web+App" | python -c "import sys,json; d=json.load(sys.stdin); print(f'  Web App: {len(d)}')"

echo "=== PEP 8 ==="
ruff check . 2>/dev/null && echo "[OK] Ruff чист" || echo "⚠️  Есть замечания (смотреть выше)"

echo "=== COMMENTS ==="
rg "BATCH_SIZE" main.py && rg "Fallback" upwork.py && echo "[OK] Ключевые комментарии"

kill $PID 2>/dev/null

echo ""
echo "=== LOW PRIORITY DONE ==="
```
