# Freelance Radar 🎯

Парсер и AI-аналитик заказов с фриланс-бирж. Собирает заказы с нескольких площадок,
анализирует через LLM (Ollama / DeepSeek / Gemini) и показывает, какие заказы стоит брать.

## Возможности

- **Парсинг 14 площадок:** Oferia.pl, Useme.com, WorkConnect.app, Zleca.pl, Upwork.com,
  Toptal.com, Freelancehunt.com, Fixly.pl, Freelance.pl, Outwork.pl, Freelancer.com,
  Fiverr.com, Gigster.com, Freelancermap.com
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
- **Веб-интерфейс:** SPA с кавайным дизайном, фильтрацией по категориям, вердикту и статусу анализа
- **Аутентификация:** регистрация и вход по email, JWT-токен в localStorage, сессия не истекает
- **Настройки LLM через UI:** управление API-ключами и моделями для каждого провайдера
  прямо из браузера, с проверкой подключения (Test Connection)
- **Без Playwright:** парсинг статического HTML через httpx + BeautifulSoup, без браузера
- **Коллектор исторических материалов** (`collectors/`): собирает фото/картины/чертежи
  по названию объекта (Wikimedia Commons, Polona.pl, Europeana, NAC и др.) и
  готовит три версии файлов (original / optimized 2048px / thumbnail 512px)
  для AR-приложения Geo-History Spots
- **Дорожная карта** и статус развития — в [ROADMAP.md](ROADMAP.md)

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
# ОБЯЗАТЕЛЬНО: сгенерируйте JWT_SECRET:
#   python3 -c "import secrets; print(secrets.token_urlsafe(32))"

# 5. Запустить
uvicorn main:app --port 8099 --host 127.0.0.1
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
| `ASSETS_ROOT` | `./assets` | Корень хранения файлов коллектора (`archive/ production/ thumbnails/`) |
| `EUROPEANA_API_KEY` | — | Ключ Europeana API (для источника `europeana`) |
| `JWT_SECRET` | — | **Обязательно!** Секретный ключ для JWT (минимум 32 символа) |

## API эндпоинты

### Публичные (без аутентификации)

| Метод | Путь | Описание |
|---|---|---|
| `GET` | `/` | SPA фронтенд |
| `POST` | `/api/refresh` | Запустить только парсинг (без анализа) |
| `POST` | `/api/analyze?provider=&force=` | Запустить анализ |
| `GET` | `/api/jobs?category=&verdict=&analyzed=` | Список заказов с фильтрацией |
| `GET` | `/api/stats` | Статистика + статус задач + доступность провайдеров |
| `GET` | `/api/status` | Статус фоновых задач (парсинг / анализ) |
| `GET` | `/api/settings` | Текущие настройки (key-value) |
| `POST` | `/api/settings` | Обновить настройки (`{"provider": "deepseek"}`) |
| `GET` | `/api/log` | Полный лог последнего запуска |
| `POST` | `/api/collect` | Запустить сбор исторических материалов (`{"object_name": "...", "sources": [...], "limit": N}`) |
| `GET` | `/api/collect/status/{task_id}` | Статус фоновой задачи сбора |
| `GET` | `/api/objects` | Список всех исторических объектов |
| `GET` | `/api/objects/{object_id}/assets` | Ассеты объекта (`?source=&year=`) |
| `GET` | `/api/assets?object_id=` | Список собранных ассетов объекта (совместимость) |
| `GET` | `/api/assets/download/{asset_id}` | Скачать версию файла (`?version=thumbnail\|optimized\|original`) |
| `GET` | `/api/assets/random` | Случайные ассеты (`?object_id=&limit=10`) |

### Аутентификация

| Метод | Путь | Описание |
|---|---|---|
| `POST` | `/api/register` | Регистрация нового пользователя (email + password) |
| `POST` | `/api/login` | Вход, возвращает JWT-токен |
| `GET` | `/api/me` | Данные текущего пользователя (требует токен) |
| `POST` | `/api/logout` | Выход (клиент удаляет токен) |

### Защищённые (требуют JWT в заголовке `Authorization: Bearer <token>`)

| Метод | Путь | Описание |
|---|---|---|
| `GET` | `/api/user/settings` | Настройки LLM пользователя (с маскировкой ключей) |
| `PUT` | `/api/user/settings` | Обновить настройки LLM пользователя |
| `POST` | `/api/test-connection` | Проверить подключение к провайдеру |

## Использование

### 1. Парсинг

Нажми **«Запустить парсинг»** — парсеры пройдут по всем 14 площадкам, соберут новые заказы
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

### 4. Настройки LLM (требуется регистрация)

Перейдите на вкладку **«Настройки»**. Если вы не авторизованы — зарегистрируйтесь
или войдите. После входа вы сможете:

- Управлять API-ключами для DeepSeek и Gemini
- Выбирать модель для каждого провайдера
- Настраивать модель и хост для Ollama
- Проверять подключение к каждому провайдеру кнопкой **Test**
- Сохранять настройки кнопкой **«Сохранить настройки»**

Настройки применяются сразу — анализатор использует новые ключи и модели
при следующем запуске анализа.

### 5. Просмотр

- Карточки сгруппированы по категориям
- Каждая показывает: вердикт, заголовок-ссылку, бюджет, сложность (точки),
  оценку времени, источник и причину вердикта от LLM
- Фильтры в тулбаре: по вердикту, по статусу анализа, по категории

## Архитектура

```
freelance-radar/
├── main.py              # FastAPI приложение + роуты
├── auth.py              # JWT-функции и хеширование паролей
├── database.py          # SQLite (aiosqlite), upsert, настройки, миграции
├── models.py            # Job, Category, Verdict, CollectRequest — модели данных
├── analyzer.py          # BaseAnalyzer + реализации: Ollama, DeepSeek, Gemini
├── collectors/          # Сбор исторических материалов (не зависит от scrapers/)
│   ├── __init__.py      # COLLECTOR_REGISTRY — реестр источников
│   ├── base_collector.py# BaseCollector (наследует scrapers.base.BaseScraper)
│   ├── wikimedia.py     # Wikimedia Commons (MediaWiki API)
│   ├── polona.py        # Polona.pl (поиск + страницы объектов)
│   ├── europeana.py     # Europeana.eu (REST API, EUROPEANA_API_KEY)
│   ├── look_and_learn.py# Look and Learn (поисковая выдача)
│   ├── nac.py           # Narodowe Archiwum Cyfrowe
│   ├── um_warszawa.py   # Исторический портал Варшавы (экспериментальный)
│   ├── optimizer.py     # MediaOptimizer: original/optimized/thumbnail (Pillow)
│   ├── manager.py       # CollectorManager: запуск, БД, оптимизация в assets/
│   └── models.py        # Pydantic-модели ответов API
├── assets/              # archive/ production/ thumbnails по объектам
├── test_collector.py    # Тест коллектора (CLI: --query, --limit, --sources)
├── scrapers/
│   ├── __init__.py      # Реестр всех скраперов (ALL_SCRAPERS, 14 площадок)
│   ├── base.py          # BaseScraper, детектор категорий, парсинг бюджета
│   ├── oferia.py        # Oferia.pl
│   ├── useme.py         # Useme.com
│   ├── workconnect.py   # WorkConnect.app
│   ├── zleca.py         # Zleca.pl
│   ├── upwork.py        # Upwork.com (listing + RSS fallback)
│   ├── toptal.py        # Toptal.com (JSON-LD + HTML links)
│   ├── freelancehunt.py # Freelancehunt.com
│   ├── fixly.py         # Fixly.pl
│   ├── freelancepl.py   # Freelance.pl
│   ├── outwork.py       # Outwork.pl
│   ├── freelancer.py    # Freelancer.com
│   ├── fiverr.py        # Fiverr.com
│   ├── gigster.py       # Gigster.com
│   └── freelancermap.py # Freelancermap.com
├── services/
│   ├── __init__.py
│   └── state.py         # AppState — датакласс состояния (парсинг/анализ/лог)
├── templates/
│   └── index.html       # SPA фронтенд (только HTML, ~270 строк)
├── static/
│   ├── app.js           # Клиентская логика (заказы, аутентификация, настройки)
│   └── styles.css       # Кавайная тема (~1678 строк, рекомендуется дефрагментация)
├── start.sh             # Скрипт запуска (создаёт venv, запускает uvicorn)
├── radar.db             # SQLite БД (создаётся автоматически)
├── requirements.txt     # Зависимости Python (только нужные: httpx, fastapi и др.)
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
                                                     (Settings tab)
```

### Безопасность

- Пароли хешируются bcrypt
- JWT-токены с алгоритмом HS256 (срок жизни настраивается в `auth.py`, `JWT_EXPIRE_DAYS`)
- API-ключи хранятся в БД в открытом виде (для локального использования;
  рекомендуется не передавать БД третьим лицам)
- Все эндпоинты настроек и тестирования защищены JWT-аутентификацией
- Первый зарегистрированный пользователь получает права администратора

## Коллектор исторических материалов

Модуль `collectors/` собирает исторические визуальные материалы (фотографии,
картины, литографии, чертежи, карты) по названию объекта из открытых источников
и готовит их для мобильного AR-приложения Geo-History Spots. Работает независимо
от парсинга заказов (`scrapers/`), но переиспользует `BaseScraper`, `httpx`,
`BeautifulSoup` и `database.py`.

### Источники

| Источник | Ключ | Метод | Статус |
|---|---|---|---|
| Wikimedia Commons | `wikimedia` | MediaWiki API (категории + поиск) | ✅ работает |
| Polona.pl | `polona` | HTML (поиск с фильтром category:photographs) | ⚠️ частично — SPA, SSR не всегда отдаёт результаты |
| Europeana.eu | `europeana` | Официальный REST API (нужен ключ) | ✅ работает (при наличии `EUROPEANA_API_KEY`) |
| Look and Learn | `lookandlearn` | HTML (поисковая выдача) | ⚠️ защищён Cloudflare — часто возвращает пусто |
| NAC (nac.gov.pl) | `nac` | HTML (поиск) | ⚠️ обычно защищён Incapsula — запросы отклоняются |
| Исторический портал Варшавы | `um_warszawa` | HTML (портал исторических карт) | 🧪 экспериментальный (JS-приложение) |

### Оптимизация медиа-файлов

Каждый скачанный файл проходит через `MediaOptimizer` (Pillow) и даёт **три версии**:

| Версия | Каталог | Размер | Формат |
|---|---|---|---|
| Оригинал | `assets/archive/<city>/<slug>/` | без изменений | как скачан (jpg/png/pdf/usdz/…) |
| Optimized (для AR) | `assets/production/<city>/<slug>/` | ≤ **2048 px** по большей стороне | JPEG, качество **85** |
| Thumbnail (превью в UI) | `assets/thumbnails/<city>/<slug>/` | ≤ **512 px** по большей стороне | JPEG, качество **75** |

Имя файла: `<год>_<id>_original.<ext>` / `_optimized.jpg` / `_thumb.jpg`.
Не-изображения (PDF, USDZ, MP4) сохраняются только в оригинале. Pillow-операции
выполняются через `asyncio.to_thread`, чтобы не блокировать событийный цикл.
При повторном сборе файлы не качаются заново (по `file_url` в БД).

### Получение API-ключей

- **Europeana**: бесплатно на https://pro.europeana.eu/page/get-api-key → вписать в
  `.env` как `EUROPEANA_API_KEY`. Без ключа источник пропускается с предупреждением.
- Остальные источники ключей не требуют.

### Переменные окружения

```env
# корень хранения: archive/ production/ thumbnails/
ASSETS_ROOT=./assets
EUROPEANA_API_KEY=your_key_here
LOC_API_KEY=your_key_here   # зарезервировано для loc.gov
```

### Запуск

```bash
source .venv/bin/activate

# CLI-тест (все источники, лимит 5)
python test_collector.py

# Только Wikimedia, свой запрос и лимит (город можно задать явно)
python test_collector.py --query "Warsaw Old Town" --sources wikimedia --limit 10 --city warsaw
```

Пример результата оптимизации (тест «Palac Kultury i Nauki», source `wikimedia`):

```text
assets/archive/warsaw/palac_kultury_i_nauki/2013_9_original.jpg   — 4909×3186, 4.8 MB
assets/production/warsaw/palac_kultury_i_nauki/2013_9_optimized.jpg — 2048×1329, 646 KB
assets/thumbnails/warsaw/palac_kultury_i_nauki/2013_9_thumb.jpg    — 512×332, 36 KB
```

### API

```bash
# Запустить сбор (фоново, возвращает task_id)
curl -X POST http://localhost:8099/api/collect \
  -H 'Content-Type: application/json' \
  -d '{"object_name": "Zamek Królewski", "sources": ["wikimedia", "polona", "europeana"], "limit": 50, "city": "Warsaw", "latitude": 52.2476, "longitude": 21.0141}'

# Статус задачи: {"status": "running|done|error", "collected": N, "downloaded": M, "errors": [...]}
curl http://localhost:8099/api/collect/status/<task_id>

# Список исторических объектов
curl http://localhost:8099/api/objects

# Ассеты объекта с фильтрами (источник/год)
curl "http://localhost:8099/api/objects/1/assets?source=wikimedia&year=1939"

# Скачать версию файла (?version=thumbnail|optimized|original, по умолчанию optimized)
curl -o photo.jpg "http://localhost:8099/api/assets/download/42?version=optimized"

# Случайные ассеты для превью на карте
curl "http://localhost:8099/api/assets/random?object_id=1&limit=10"
```

`GET /api/assets?object_id=1` (без `objects` в пути) сохранён для обратной
совместимости.

### Структура модуля

```
collectors/
├── __init__.py         # COLLECTOR_REGISTRY — реестр источников (ключ → класс)
├── base_collector.py   # BaseCollector (наследует scrapers.base.BaseScraper)
├── wikimedia.py        # WikimediaCollector
├── polona.py           # PolonaCollector
├── europeana.py        # EuropeanaCollector (REST API, EUROPEANA_API_KEY)
├── look_and_learn.py   # LookAndLearnCollector
├── nac.py              # NacCollector
├── um_warszawa.py      # UmWarszawaCollector (экспериментальный)
├── optimizer.py        # MediaOptimizer — три версии файла (Pillow)
├── manager.py          # CollectorManager — оркестрация сбора
└── models.py           # Pydantic-модели ответов API
```

Таблицы SQLite: `historical_objects` (объекты + `slug`, `city`, координаты),
`historical_assets` (ассеты + пути к трём версиям, размеры, статус `downloaded`/`error`).


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
| **Веб-фреймворк** | FastAPI + uvicorn (через httpx, без SDK провайдеров) |
| **База данных** | SQLite (aiosqlite) |
| **Аутентификация** | JWT (python-jose) + bcrypt |
| **Фронтенд** | HTML + CSS + Vanilla JS (без фреймворков) |
| **Парсинг** | httpx + BeautifulSoup4 + lxml |
| **LLM** | Ollama / DeepSeek API / Gemini API (все через httpx) |
| **Асинхронность** | asyncio, BackgroundTasks |

## Дорожная карта

См. [ROADMAP.md](ROADMAP.md) — Telegram-бот, новые площадки, деплой на Vercel, персонализация.

## Лицензия

MIT
