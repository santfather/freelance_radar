# TODO: Средний приоритет

> Выполнять **после TODO_HIGH.md**. Группы строго по порядку.
> После каждой группы — обязательный прогон тестов.
> После каждого пункта — дефенсивный коммит.

---

## Группа 1: Фронтенд (JS + статика)

> Только `templates/index.html` и новые файлы. ~1.5 часа.
> После группы — **Тесты 1**.

### □ 1.1 — R7: Вынести дублирующийся poll-цикл в JS

**Файл:** `templates/index.html`

Создать общую функцию `pollUntilDone`:

```javascript
async function pollUntilDone(options) {
  const { getButton, onComplete } = options;
  if (pollInterval) clearInterval(pollInterval);
  pollInterval = setInterval(async () => {
    const s = await fetch('/api/stats').then(r => r.json()).catch(() => ({}));
    updateProgressUI(s);
    updateScrapeStatus(s.scraping);
    updateAnalyzeStatus(s.analyzing, s.analyze_progress, s.analyze_total);
    if (s.log) document.getElementById('log-box').innerHTML = s.log.map(l => `<div>${escHtml(l)}</div>`).join('');
    ['total','analyzed','unanalyzed','take'].forEach(k => {
      const el = document.getElementById(`stat-${k}`);
      if (el) el.textContent = s[k] ?? '—';
    });
    if (!s.scraping && !s.analyzing) {
      clearInterval(pollInterval);
      pollInterval = null;
      if (getButton) getButton().disabled = false;
      if (onComplete) await onComplete();
      await loadJobs();
      await loadStats();
    }
  }, 1500);
}
```

Переписать `startScrape`, `startAnalysis`, `startReanalysis` на вызов `pollUntilDone`:

```javascript
async function startScrape() {
  const btn = document.getElementById('btn-scrape');
  btn.disabled = true;
  btn.textContent = '⏳ Парсинг...';
  document.getElementById('log-box').classList.add('visible');
  logVisible = true;
  await fetch('/api/refresh', {method: 'POST'});
  pollUntilDone({
    getButton: () => {
      const b = document.getElementById('btn-scrape');
      b.textContent = '🔄 Запустить парсинг';
      return b;
    },
  });
}

async function startAnalysis() {
  const btn = document.getElementById('btn-analyze');
  btn.disabled = true;
  btn.textContent = '⏳ Анализ...';
  document.getElementById('log-box').classList.add('visible');
  logVisible = true;
  const r = await fetch('/api/analyze', {method: 'POST'}).then(r => r.json());
  if (r.status === 'already_running') {
    btn.disabled = false;
    btn.textContent = '🧠 Запустить анализ';
    return;
  }
  pollUntilDone({
    getButton: () => {
      const b = document.getElementById('btn-analyze');
      b.textContent = '🧠 Запустить анализ';
      return b;
    },
  });
}

async function startReanalysis() {
  const btn = document.getElementById('btn-reanalyze');
  const btnAnalyze = document.getElementById('btn-analyze');
  if (!confirm(`Сбросить все вердикты и переанализировать все ${document.getElementById('stat-total').textContent} заказов?`)) return;
  btn.disabled = true;
  btnAnalyze.disabled = true;
  btn.textContent = '⏳ Переанализ...';
  document.getElementById('log-box').classList.add('visible');
  logVisible = true;
  await fetch('/api/analyze?force=true', {method: 'POST'});
  pollUntilDone({
    getButton: () => {
      const b = document.getElementById('btn-reanalyze');
      b.textContent = '🔄 Переанализировать всё';
      document.getElementById('btn-analyze').disabled = false;
      return b;
    },
  });
}
```

---

### □ 1.2 — R15: Вынести JS и CSS в отдельные файлы

**Создать:**

```
static/
├── styles.css    → весь CSS из тега <style> (все ~330 строк)
└── app.js        → весь JS из тега <script> (все ~330 строк)
```

**Изменить `templates/index.html`:**
```html
<!DOCTYPE html>
<html lang="pl">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <title>🎯 Freelance Radar</title>
  <link rel="stylesheet" href="/static/styles.css"/>
</head>
<body>
  <!-- весь HTML без CSS и JS -->
  <script src="/static/app.js"></script>
</body>
</html>
```

**Добавить в `main.py`:**
```python
from fastapi.staticfiles import StaticFiles
app.mount("/static", StaticFiles(directory="static"), name="static")
```

---

### ✅ Тесты группы 1

```bash
cd /Users/vladislavkovalenko/Projects/agent-workspace/freelance-radar

# 1. Файлы статики существуют
ls -la static/styles.css static/app.js

# 2. Синтаксис JS
node -c static/app.js && echo "[OK] JS синтаксис"

# 3. Импорты
python -c "
import main
from fastapi.staticfiles import StaticFiles
print('[OK] StaticFiles подключён')
"

# 4. Запуск приложения
uvicorn main:app --port 8099 --host 127.0.0.1 &
PID=$!
sleep 3

echo "=== Проверка статики ==="
curl -s -o /dev/null -w "styles.css: %{http_code}\n" http://localhost:8099/static/styles.css
curl -s -o /dev/null -w "app.js: %{http_code}\n" http://localhost:8099/static/app.js

echo "=== Проверка главной ==="
curl -s http://localhost:8099 | rg "href='/static/styles.css'" && echo "[OK] CSS подключён"
curl -s http://localhost:8099 | rg "src='/static/app.js'" && echo "[OK] JS подключён"

echo "=== Проверка API ==="
curl -s http://localhost:8099/api/status | python -m json.tool
curl -s http://localhost:8099/api/stats | python -m json.tool

kill $PID 2>/dev/null

# Коммит
git add -A && git commit -m "checkpoint: medium group 1 — frontend extraction"
```

---

## Группа 2: API и утилиты

> Чистка API-слоя. ~45 минут.
> После группы — **Тесты 2**.

### □ 2.1 — R14: Убрать check_provider_available()

**Файл:** `analyzer.py`, строки 325–331

Рекомендуется **Вариант А** (удалить функцию — она не используется, в main.py проверки делаются индивидуально):

```python
# Удалить целиком:
async def check_provider_available(provider: str) -> tuple[bool, str]:
    ...
```

Или **Вариант Б** (использовать в main.py вместо прямых вызовов) — если хочется унификации.

---

### □ 2.2 — R16: Добавить Pydantic-модель для POST /api/settings

**Файлы:** `main.py` (строка 315), `models.py`

В `models.py` добавить:

```python
from pydantic import BaseModel

class SettingsUpdate(BaseModel):
    provider: str | None = None
```

В `main.py`:

```python
from models import SettingsUpdate

@app.post("/api/settings")
async def settings_post(data: SettingsUpdate):
    if data.provider:
        provider = data.provider.lower()
        if provider not in ("ollama", "deepseek", "gemini"):
            return JSONResponse(
                {"status": "error", "message": f"Unknown provider '{provider}'"},
                status_code=400,
            )
        await set_setting("llm_provider", provider)
    return JSONResponse({"status": "ok"})
```

---

### ✅ Тесты группы 2

```bash
cd /Users/vladislavkovalenko/Projects/agent-workspace/freelance-radar

# 1. Импорты
python -c "
import main; import database; import analyzer; import models
from models import SettingsUpdate
s = SettingsUpdate(provider='ollama')
assert s.provider == 'ollama'
s2 = SettingsUpdate()
assert s2.provider is None
print('[OK] Pydantic модель работает')
"

# 2. check_provider_available (если удалён — проверить, что не импортируется)
rg "check_provider_available" --type py | rg -v "AUDIT.md|TODO" && echo "⚠️  Функция ещё есть" || echo "[OK] Не используется"

# 3. Smoke-тест
uvicorn main:app --port 8099 --host 127.0.0.1 &
PID=$!
sleep 3

echo "=== POST /api/settings — валидный ==="
curl -s -X POST http://localhost:8099/api/settings \
  -H "Content-Type: application/json" \
  -d '{"provider": "deepseek"}' | python -m json.tool

echo "=== POST /api/settings — невалидный ==="
curl -s -X POST http://localhost:8099/api/settings \
  -H "Content-Type: application/json" \
  -d '{"provider": "invalid"}' | python -m json.tool

echo "=== POST /api/settings — пустой ==="
curl -s -X POST http://localhost:8099/api/settings \
  -H "Content-Type: application/json" \
  -d '{}' | python -m json.tool

echo "=== GET /api/settings ==="
curl -s http://localhost:8099/api/settings | python -m json.tool

kill $PID 2>/dev/null

# Коммит
git add -A && git commit -m "checkpoint: medium group 2 — API cleanup"
```

---

## Финальный smoke-тест всего MEDIUM

```bash
cd /Users/vladislavkovalenko/Projects/agent-workspace/freelance-radar

# Полная перепроверка
python -c "
import main; import database; import analyzer; import models
from scrapers import ALL_SCRAPERS
from models import SettingsUpdate
print('[OK] Все импорты — без ошибок')
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

echo "=== STATIC ==="
for f in styles.css app.js; do
  code=$(curl -s -o /dev/null -w "%{http_code}" "http://localhost:8099/static/$f")
  echo "  /static/$f → $code"
done

echo "=== SETTINGS (Pydantic validation) ==="
curl -s -X POST http://localhost:8099/api/settings -H "Content-Type: application/json" -d '{"provider": "invalid"}' | python -c "
import sys,json
d = json.load(sys.stdin)
assert d.get('status') == 'error'
print(f'[OK] 400 для invalid провайдера')
"

echo "=== POLL CYCLE CHECK ==="
curl -s http://localhost:8099 | rg "pollUntilDone" && echo "[OK] pollUntilDone существует" || echo "⚠️  pollUntilDone не найден"

kill $PID 2>/dev/null

echo ""
echo "=== MEDIUM PRIORITY DONE ==="
```
