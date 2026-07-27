# Freelance Radar 🎯

Парсер и AI-аналитик заказов с фриланс-бирж. Собирает заказы с нескольких площадок,
анализирует через LLM (Ollama / DeepSeek / Gemini) и показывает, какие заказы стоит брать.

## Возможности

- **Парсинг 6 площадок:** Oferia.pl, Useme.com, WorkConnect.app, Zleca.pl, Upwork.com, Toptal.com
- **LLM-анализ** каждым из трёх провайдеров на выбор:
  - **Ollama** — локально, бесплатно, без интернета
  - **DeepSeek API** — дешёвый и быстрый облачный API
  - **Gemini API** — Google Gemini с бесплатным tier
- **Раздельные этапы:** парсинг и анализ запускаются независимо друг от друга
- **Переанализ:** кнопка «Переанализировать всё» сбрасывает старые вердикты и запускает
  полный анализ заново (с подтверждением)
- **Автоопределение категорий:** Web App, Mobile App, CMS (WordPress / Drupal / MODX / Bitrix
  и др.), Other IT — на основе ключевых слов в заголовке и описании
- **Вердикты:** TAKE / SKIP / UNKNOWN — каждый заказ получает оценку сложности (1–5)
  и примерное время в часах
- **Веб-интерфейс:** SPA с тёмной темой, фильтрацией по категориям, вердикту и статусу анализа
- **Без Playwright:** парсинг статического HTML через httpx + BeautifulSoup, без браузера

## Быстрый старт

```bash
# 1. Перейти в директорию
cd freelance-radar

# 2. Быстрый запуск (создаёт venv + устанавливает зависимости)
./start.sh
```

Или вручную:

```bash
# 2. Создать виртуальное окружение
python3 -m venv .venv
source .venv/bin/activate

# 3. Установить зависимости
pip install -r requirements.txt

# 4. Настроить окружение
cp .env.example .env
# отредактировать .env (указать ключи API при необходимости)

# 5. Запустить
uvicorn main:app --port 8099 --host 0.0.0.0
```

Открой `http://localhost:8099` в браузере.

## Требования

- **Python 3.11+**
- **Для Ollama** (локальный анализ):
  ```bash
  # Установи Ollama: https://ollama.com
  ollama pull qwen2.5:14b
  ```
- **Для DeepSeek:** API-ключ в `.env` (`DEEPSEEK_API_KEY`)
- **Для Gemini:** API-ключ в `.env` (`GEMINI_API_KEY`)
- Достаточно одного провайдера — остальные опциональны

## Переменные окружения (`.env`)

| Переменная | По умолчанию | Описание |
|---|---|---|
| `LLM_PROVIDER` | `ollama` | Провайдер по умолчанию: `ollama`, `deepseek` или `gemini` |
| `OLLAMA_MODEL` | `qwen2.5:14b` | Модель Ollama |
| `OLLAMA_HOST` | `http://localhost:11434` | Адрес Ollama API |
| `DEEPSEEK_API_KEY` | — | API-ключ DeepSeek |
| `DEEPSEEK_MODEL` | `deepseek-chat` | Модель DeepSeek |
| `GEMINI_API_KEY` | — | API-ключ Google Gemini |
| `GEMINI_MODEL` | `gemini-2.5-flash` | Модель Gemini |
| `DB_PATH` | `radar.db` | Путь к SQLite базе |

## API эндпоинты

| Метод | Путь | Описание |
|---|---|---|
| `GET` | `/` | SPA фронтенд |
| `POST` | `/api/refresh` | Запустить только парсинг (без анализа) |
| `POST` | `/api/analyze?provider=&force=` | Запустить анализ (параметр `force=true` сбрасывает и переанализирует всё) |
| `GET` | `/api/jobs?category=&verdict=&analyzed=` | Список заказов с фильтрацией |
| `GET` | `/api/stats` | Статистика + статус задач + доступность провайдеров |
| `GET` | `/api/status` | Статус фоновых задач (парсинг / анализ) |
| `GET` | `/api/settings` | Текущие настройки |
| `POST` | `/api/settings` | Обновить настройки (`{"provider": "deepseek"}`) |
| `GET` | `/api/log` | Полный лог последнего запуска |

### Параметры `/api/analyze`

- `provider` — один из: `ollama`, `deepseek`, `gemini`. Если не указан — используется
  сохранённая настройка (из БД или `.env`)
- `force` — `true` или `false`. При `true` все существующие вердикты сбрасываются,
  и анализ запускается заново для всех заказов

### Параметры `/api/jobs`

- `category` — фильтр по категории: `all`, `Web App`, `Mobile App`, `CMS`, `Other IT`
- `verdict` — фильтр по вердикту: `all`, `TAKE`, `SKIP`, `UNKNOWN`
- `analyzed` — фильтр по статусу анализа: `all`, `0` (непроанализированные), `1` (проанализированные)

## Использование

### 1. Парсинг

Нажми **«Запустить парсинг»** — парсеры пройдут по всем 6 площадкам, соберут новые заказы
и сохранят в БД. Анализ **не запускается** — это быстрая операция (секунды).

### 2. Выбор анализатора

В выпадающем списке **«Анализатор»** выбери провайдера:
- **Ollama (локально)** — работает без интернета, использует локальную модель
- **DeepSeek API** — быстрый облачный API, нужен ключ в `.env`
- **Gemini API** — Google Gemini, нужен ключ в `.env`

Выбор сохраняется в БД и применяется при следующем анализе. В хедере отображается
статус выбранного провайдера (🟢 / 🔴).

### 3. Анализ

Нажми **«Запустить анализ»** — все непроанализированные заказы будут обработаны
выбранной LLM. Анализ работает **пачками по 10 параллельно** — это ускоряет обработку
сотен заказов. Прогресс отображается в реальном времени.

### 4. Переанализ

Нажми **«Переанализировать всё»** — появится подтверждение, после которого все старые
вердикты сбрасываются, и запускается полный анализ заново. Удобно, чтобы попробовать
разных провайдеров или после обновления промпта.

### 5. Просмотр

- Карточки сгруппированы по категориям
- Каждая показывает: вердикт, заголовок-ссылку, бюджет, сложность (точки),
  оценку времени, источник и причину вердикта от LLM
- Фильтры в тулбаре: по вердикту, по статусу анализа, по категории

## Категории заказов

| Категория | Примеры технологий |
|---|---|
| **Web App** | React, Vue, Angular, Next.js, Django, FastAPI, Laravel, HTML/CSS |
| **Mobile App** | Android, iOS, Flutter, React Native, Swift, Kotlin |
| **CMS** | WordPress, Drupal, MODX, Bitrix, Joomla, Magento, Shopify, Wix |
| **Other IT** | Всё остальное (тестирование, девопс, администрирование и т.п.) |

Категория определяется автоматически по ключевым словам в заголовке и описании заказа.

## Архитектура

```
freelance-radar/
├── main.py              # FastAPI приложение + роуты
├── database.py          # SQLite (aiosqlite), upsert, настройки, миграции
├── models.py            # Job, Category, Verdict — модели данных
├── analyzer.py          # BaseAnalyzer + реализации: Ollama, DeepSeek, Gemini
├── scrapers/
│   ├── __init__.py      # Реестр всех скраперов
│   ├── base.py          # BaseScraper, детектор категорий, парсинг бюджета
│   ├── oferia.py        # Oferia.pl (3 категории, session-based)
│   ├── useme.py         # Useme.com (3 категории)
│   ├── workconnect.py   # WorkConnect.app (3 категории)
│   ├── zleca.py         # Zleca.pl (3 категории)
│   ├── upwork.py        # Upwork.com (listing + RSS fallback)
│   └── toptal.py        # Toptal.com (JSON-LD + HTML links)
├── templates/
│   └── index.html       # SPA фронтенд (HTML + CSS + Vanilla JS)
├── start.sh             # Скрипт запуска
├── radar.db             # SQLite БД (создаётся автоматически)
├── requirements.txt     # Зависимости Python
├── .env.example         # Шаблон конфигурации
├── .env                 # Конфигурация (не коммитится)
├── README.md            # Этот файл
├── ROADMAP.md           # План развития
└── .gitignore
```

### Поток данных

```
┌──────────────┐     ┌───────────────────────┐     ┌──────────────┐
│  Scraper 1   │     │                       │     │              │
│  Scraper 2   │────▶│  SQLite (jobs)        │────▶│  Analyzer    │
│  Scraper 3   │     │  analyzed=0            │     │  Ollama      │
│  ...         │     │  analyzed=1 (после     │     │  DeepSeek    │
│  Scraper 6   │     │  анализа)             │     │  Gemini      │
└──────────────┘     └───────────────────────┘     └──────────────┘
         ↑                        ↑                        ↑
    POST /api/refresh        POST /api/analyze       Выбор провайдера
```

### Компоненты

**main.py** — точка входа FastAPI:
- Фоновые задачи через `BackgroundTasks`
- Раздельные статусы для парсинга и анализа (in-memory)
- Логирование цветными эмодзи-префиксами

**database.py** — слой данных:
- SQLite через `aiosqlite` (асинхронный)
- Upsert-вставка (дубли обновляются, а не создаются заново)
- Миграции при старте (переименование категорий и т.п.)
- Таблица `settings` (key-value) для хранения настроек пользователя

**analyzer.py** — абстрактный анализатор с фабрикой:
- `BaseAnalyzer` — общий интерфейс
- `OllamaAnalyzer` — локальная Ollama (chat/generate fallback)
- `DeepSeekAnalyzer` — OpenAI-совместимый API
- `GeminiAnalyzer` — Google Generative AI API
- Фабрика `get_analyzer(provider)` + проверки доступности

**scrapers/** — парсеры площадок:
- Каждый наследует `BaseScraper`
- Случайный User-Agent, задержки 1–3 с
- Автоопределение категорий через keyword-matching
- Парсинг бюджета из текста (диапазоны `500-1000 zł`)

## Разработка

```bash
# Активировать окружение
source .venv/bin/activate

# Запуск с авто-перезагрузкой
uvicorn main:app --reload --port 8099

# Проверка синтаксиса
python3 -c "import py_compile; py_compile.compile('main.py', doraise=True); print('OK')"
```

## Технологический стек

| Компонент | Технология |
|---|---|
| **Веб-фреймворк** | FastAPI + uvicorn |
| **База данных** | SQLite (aiosqlite) |
| **Фронтенд** | HTML + CSS + Vanilla JS (без фреймворков) |
| **Парсинг** | httpx + BeautifulSoup4 + lxml |
| **LLM** | Ollama / DeepSeek API / Gemini API |
| **Асинхронность** | asyncio, BackgroundTasks |

## Дорожная карта

См. [ROADMAP.md](ROADMAP.md) — Telegram-бот, новые площадки, деплой на Vercel, персонализация.

## Лицензия

MIT
