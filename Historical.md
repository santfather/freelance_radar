# Historical.md — Аудит модуля исторических данных (`collectors/`)

> **Проект:** `agent-workspace/freelance-radar`
> **Дата аудита:** 2026-08-04
> **Объект аудита:** модуль `collectors/` — сбор исторических визуальных материалов (фотографии, картины, литографии, чертежи, карты) для AR-приложения Geo-History Spots
> **Язык:** русский

---

## 1. Общее описание

Модуль `collectors/` собирает исторические материалы из открытых источников по названию
объекта (например, «Zamek Królewski»), сохраняет метаданные в SQLite (`radar.db`) и готовит
три версии каждого файла для мобильного AR-приложения:

| Версия | Каталог | Параметры |
|---|---|---|
| Оригинал | `assets/archive/<city>/<slug>/` | файл как скачан |
| Optimized (для AR) | `assets/production/<city>/<slug>/` | JPEG, ≤2048 px, качество 85 |
| Thumbnail (превью UI) | `assets/thumbnails/<city>/<slug>/` | JPEG, ≤512 px, качество 75 |

Не-изображения (PDF, USDZ, MP4) сохраняются только в оригинале. Имя файла:
`<год>_<id>_original.<ext>` / `_optimized.jpg` / `_thumb.jpg`.

**Текущее состояние (на момент аудита):**
- 19 исторических объектов в БД (все — Варшава)
- 810 ассетов в БД, из них 804 скачано (downloaded=1), 6 с ошибками
- ~487 МБ файлов в `assets/`
- Все 810 ассетов собраны из источника `wikimedia` (подробнее в §6)

---

## 2. Критерии сбора данных

### 2.1 Входные параметры запроса (`POST /api/collect`, `CollectRequest`)

| Параметр | Тип | По умолчанию | Назначение |
|---|---|---|---|
| `object_name` | str | — (обязательный) | Название объекта; используется как поисковый запрос `query` и для генерации `slug` |
| `sources` | list[str] \| "all" | `"all"` | Ключи источников из `COLLECTOR_REGISTRY`; `"all"` — все 6 |
| `limit` | int | 20 | Максимум файлов на источник (менеджер ограничивает 1–200) |
| `city` | str | "" | Город; если не задан — определяется из `object_name` по алиасам |
| `latitude` / `longitude` | float? | None | Координаты объекта для AR-привязки |
| `era` | str | "" | Исторический период (например, «XIV-XX w.») |
| `description` | str | "" | Описание объекта |

### 2.2 Логика сбора (CollectorManager.run)

1. `upsert_historical_object` — объект создаётся по `name` (UNIQUE) или обновляется
   (`slug`, координаты, `city`, `era`, `description`).
2. Для каждого ключа из `sources` берётся класс из `COLLECTOR_REGISTRY` и вызывается
   `collector.scrape()` — коллекторы запускаются **последовательно** (не параллельно).
3. Результаты всех источников объединяются, дедуплицируются по `file_url`
   (или `source_url`, если `file_url` пуст).
4. Для каждого ассета: `upsert_asset` (уникальность `(object_id, file_url)`) →
   `MediaOptimizer.process()` (скачивание + три версии) → `update_asset_paths`.
5. Повторный сбор **не качает заново**: если `downloaded=1` и оригинал существует на
   диске — файл пропускается.

### 2.3 Унифицированный словарь ассета

Каждый коллектор возвращает список словарей:

```python
{
    "title": "Замок Королевский, вид с востока",
    "source_url": "https://polona.pl/item/...",
    "file_url": "https://...direct_link...",
    "thumbnail_url": "https://...thumb...",
    "year": "1939",
    "description": "Фотография замка после бомбардировки",
    "source": "polona",
    "file_type": "jpg"
}
```

### 2.4 Извлечение года

- **Wikimedia**: из таблицы метаданных файла (`table.fileinfotpl`, строка Date/Data/Czas),
  при отсутствии — первое вхождение года на странице.
- **Polona / NAC / LookAndLearn**: первый год `\b(1[5-9]\d{2}|20[0-2]\d)\b` в тексте
  страницы или в заголовке.
- **Europeana**: поле `year` из API.
- По данным БД год извлечён у **всех 810 ассетов** (0 пустых).

---

## 3. Источники данных (реестр `COLLECTOR_REGISTRY`)

| Ключ | Класс | Метод сбора | Требует ключ | Статус работы |
|---|---|---|---|---|
| `wikimedia` | `WikimediaCollector` | MediaWiki API (категория `Category:<query>` + фолбэк на полнотекстовый поиск файлов, namespace 6); страница файла парсится HTML, из неё — ссылка на оригинал (`div.fullImageLink a`), миниатюра, описание, год | нет | ✅ работает |
| `polona` | `PolonaCollector` | HTML: поиск `polona.pl/search/?query=<q>&filters=category:photographs` (или graphics); страницы объектов `/preview/<id>`, прямая ссылка (`img.main-image`, `og:image`, `/api/download/`) | нет | ⚠️ не работает на практике (SPA, SSR не отдаёт результаты) |
| `europeana` | `EuropeanaCollector` | REST API Record v2 `api.europeana.eu/record/v2/search.json` (`wskey`, `profile=rich`, `qf=LANGUAGE:pl`); пагинация `start`/`nextCursor`; поля `edmIsShownBy`/`edmObject`, `edmPreview`, `title`, `dcDescription`, `year` | ✅ `EUROPEANA_API_KEY` | ⚠️ не работает без ключа (в `.env` ключ отсутствует) |
| `lookandlearn` | `LookAndLearnCollector` | HTML: поиск `lookandlearn.com/search/<q>/`; ссылки `/history-images/`, полное изображение (`og:image` и др.) | нет | ⚠️ не работает на практике (Cloudflare) |
| `nac` | `NacCollector` | HTML: поиск `nac.gov.pl/pl/szukaj/?q=<q>`; кнопка «Pobierz»/`a[download]` | нет | ⚠️ не работает на практике (Incapsula) |
| `um_warszawa` | `UmWarszawaCollector` | HTML: портал `mapa.um.warszawa.pl/portal-historyczny/` + поиск по `um.warszawa.pl`; все картинки страницы | нет | 🧪 экспериментальный (JS-приложение, парсинг ограничен) |

### Детали по каждому источнику

#### 3.1 Wikimedia Commons (`wikimedia`)
- **Поиск:** категория `Category:<query>` через `action=query&list=categorymembers`
  (`cmtype=file`, до 500); если найдено меньше `limit` — дополнение полнотекстовым
  поиском `action=query&list=search` (`srnamespace=6`).
- **Страница файла:** HTML `commons.wikimedia.org/wiki/<title>`, извлекаются:
  `div.fullImageLink a` → оригинал, `link[rel=image_src]` как фолбэк,
  `div.fullImageLink img` → миниатюра, `#fileinfotpl_desc`/`.description` → описание.
- **Год:** строка Date/Data в `table.fileinfotpl`.
- **Скачивание (важно):** из-за политики Wikimedia (лимиты 429 на оригиналы) оптимизатор
  для `wikimedia.org` **не качает оригинал**, а берёт миниатюру со страницы файла,
  увеличенную до 2000 px (`upscale_thumb_url`), с фолбэком на исходную 960px-миниатюру.
  Ретраи на 429/5xx: 4 попытки с backoff 5/10/20/40 c.
- **Практический результат:** единственный источник, который реально отдал данные — все
  810 ассетов в БД.

#### 3.2 Polona.pl (`polona`)
- Поиск с фильтром `category:photographs` или `category:graphics`.
- Проверка «пустой SPA-оболочки»: если на странице нет карточек (`a.title-link`,
  `.object-card` и т.п.), коллектор логирует предупреждение и возвращает `[]`.
- **Практический результат:** 0 ассетов (современная Polona рендерит результаты
  клиентским JS, SSR не отдаёт список).

#### 3.3 Europeana.eu (`europeana`)
- Официальный REST API; ключ из `EUROPEANA_API_KEY` (в `.env` сейчас **отсутствует** —
  без него коллектор сразу возвращает `[]` с предупреждением).
- Языковой фильтр `qf=LANGUAGE:pl` (или `language`, переданный в конструктор).
- Пагинация: `start` (страницы) + `nextCursor` из ответа.
- **Практический результат:** 0 ассетов (нет ключа).

#### 3.4 Look and Learn (`lookandlearn`)
- Поисковая выдача `lookandlearn.com/search/<q>/`; ссылки с маркером `/history-images/`.
- Детект Cloudflare («security verification», «just a moment») — возвращает `[]`.
- **Практический результат:** 0 ассетов (сайт закрыт Cloudflare).

#### 3.5 NAC (`nac`)
- Поиск `nac.gov.pl/pl/szukaj/?q=<q>`; кнопка «Pobierz»/`a[download]`, фолбэк на
  `a[href$='.jpg']` и т.п.
- Детект Incapsula/бот-защиты — возвращает `[]`.
- **Практический результат:** 0 ассетов.

#### 3.6 Исторический портал Варшавы (`um_warszawa`)
- `mapa.um.warszawa.pl/portal-historyczny/` — собираются все `<img>` со страницы
  (кроме `data:image` и pixel-заглушек), плюс фолбэк на поиск по `um.warszawa.pl`.
- `year` всегда пустой, `description` — фиксированная строка.
- **Практический результат:** 0 ассетов (источник экспериментальный).

---

## 4. Пайплайн оптимизации (MediaOptimizer)

1. **Определение URL для скачивания:** для Wikimedia — upscaled-миниатюра 2000px
   (фолбэк 960px), для остальных — `file_url`.
2. **Скачивание:** `httpx.AsyncClient` (timeout 60 c, connect 15 c, follow_redirects),
   ретраи на 429/500/502/503/504 — 4 попытки с backoff.
3. **Определение «изображение или нет»:** по `file_type` (расширение из URL) или
   `content-type` ответа.
4. **Оригинал:** запись в `archive/<city>/<slug>/<year>_<id>_original.<ext>`.
5. **Для изображений** (в `asyncio.to_thread`, чтобы не блокировать цикл):
   - `optimized` — `ImageOps.exif_transpose` → RGB → resize до ≤2048 px (LANCZOS)
     → JPEG q85 (progressive, optimize);
   - `thumbnail` — тот же пайплайн, ≤512 px, JPEG q75.
6. `Image.MAX_IMAGE_PIXELS = None` — снят лимит Pillow на размер («decompression bomb»),
   чтобы обрабатывать огромные исторические панорамы.
7. **Не-изображения:** только оригинал, без оптимизации.

### Консистентность версий (по БД, downloaded=1: 804 записи)

| Версия | Кол-во с путём | Примечание |
|---|---|---|
| `original_path` | 804 | у всех скачанных |
| `optimized_path` | 797 | у 7 записей нет — вероятно svg/png, которые не перекодировались |
| `thumbnail_path` | 804 | у всех скачанных |
| `width/height/file_size_optimized` | 797 | метаданные оптимизированной версии |

---

## 5. Модель данных (SQLite)

### `historical_objects`

```sql
CREATE TABLE historical_objects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    slug TEXT,
    latitude REAL,
    longitude REAL,
    description TEXT,
    city TEXT,
    era TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);
```

### `historical_assets`

```sql
CREATE TABLE historical_assets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    object_id INTEGER NOT NULL,
    title TEXT,
    source_url TEXT,
    file_url TEXT,
    local_path TEXT,
    file_type TEXT,
    thumbnail_url TEXT,
    description TEXT,
    year TEXT,
    source TEXT,
    downloaded INTEGER DEFAULT 0,
    original_path TEXT,
    optimized_path TEXT,
    thumbnail_path TEXT,
    width_optimized INTEGER,
    height_optimized INTEGER,
    file_size_optimized INTEGER,
    error TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (object_id) REFERENCES historical_objects(id)
);
```

### Индексы

- `UNIQUE (object_id, file_url)` — дедупликация ассетов в БД
- `(object_id)`, `(downloaded)`, `(source)`, `(year)` — по ТЗ

---

## 6. Количественный анализ фактических данных (БД `radar.db`)

| Показатель | Значение |
|---|---|
| Объектов в БД | 19 |
| Ассетов всего | 810 |
| Скачано (`downloaded=1`) | 804 |
| Ошибок (`error` не пуст) | 6 |
| Ассетов по источникам | wikimedia: 810 (100%) |
| Ассетов с пустым годом | 0 |
| Форматы: jpg | 796 |
| Форматы: png | 8 |
| Форматы: svg | 4 |
| Форматы: jpeg | 2 |
| Заполненность `era` у объектов | 0 из 19 (все пустые) |
| Города объектов | все Warsaw |
| Размер `assets/` | ~487 МБ |

### Характерные ошибки (6 записей)

Все 6 ошибок — `HTTP 429 Too Many Requests` от `upload.wikimedia.org` (лимиты
Wikimedia на массовое скачивание), например:

```
download: Client error '429 Too many requests ... use thumbnail images in sizes listed
on https://w.wiki/GHai' for url 'https://upload.wikimedia.org/wikipedia/commons/1/1b/...JPG?...'
```

Ошибки записаны в поле `error`, `downloaded=0` — при повторном сборе будут перекачаны.

---

## 7. Аудит качества кода и архитектуры

### ✅ Что сделано хорошо

1. **Абстракция:** `BaseCollector` наследует `BaseScraper`, переиспользует `_get`
   (таймауты, ротация User-Agent, случайные паузы 1–3 с) и добавляет `_fetch_soup`/`_fetch_json`.
2. **Единый формат результата** всех коллекторов (§2.3) — легко расширять.
3. **Graceful degradation:** каждый недоступный источник логирует предупреждение и
   возвращает `[]`, не роняя весь сбор. Проверки: SPA-оболочка Polona, Incapsula NAC,
   Cloudflare LookAndLearn, отсутствие ключа Europeana.
4. **Идемпотентность:** уникальный индекс `(object_id, file_url)` + проверка
   `downloaded` и существования файла при повторном сборе.
5. **Обработка 429 Wikimedia:** ретраи с backoff, upscale-миниатюры вместо оригиналов,
   фолбэк URL — учитывает официальную политику Commons.
6. **Неблокирующий цикл:** Pillow-операции в `asyncio.to_thread`.
7. **API:** 6 эндпоинтов — `POST /api/collect`, `GET /api/collect/status/{id}`,
   `GET /api/objects`, `GET /api/objects/{id}/assets` (фильтры `source`/`year`),
   `GET /api/assets/download/{id}` (`?version=`), `GET /api/assets/random`.

### ⚠️ Замечания / риски

| # | Проблема | Серьёзность |
|---|---|---|
| H-01 | **Реально работает только 1 из 6 источников** (wikimedia). Polona (SPA), LookAndLearn (Cloudflare), NAC (Incapsula), um_warszawa (JS-портал) отдают 0; Europeana — 0 без ключа. | 🔴 Высокая |
| H-02 | **`EUROPEANA_API_KEY` отсутствует в `.env`** — единственный официальный REST API в модуле не задействован. | 🔴 Высокая |
| H-03 | **Коллекторы не используют `language`** (кроме Europeana): Polona/LookAndLearn/NAC игнорируют параметр из ТЗ. | 🟡 Средняя |
| H-04 | **Пагинация реализована только в Wikimedia и Europeana**; Polona/NAC/LookAndLearn/um_warszawa берут только первую страницу результатов. | 🟡 Средняя |
| H-05 | **`era` пуст у всех 19 объектов** — параметр принимается, но не заполняется ни в одном тестовом сборе. | 🟡 Средняя |
| H-06 | **7 ассетов без `optimized_path`** при `downloaded=1` (svg/png) — статус «скачано» при отсутствии полной тройки версий, нет отдельного флага «оптимизировано». | 🟡 Средняя |
| H-07 | **Нет проверки robots.txt / rate-limit на уровне менеджера** (пауза фиксированная 3 с между скачиваниями, есть только встроенные ретраи). | 🟢 Низкая |
| H-08 | **`description` может быть пустым** у части ассетов (например, um_warszawa ставит фиксированную строку, Europeana — только при наличии `dcDescription`). | 🟢 Низкая |
| H-09 | **Выбор года регуляркой** `\b(1[5-9]\d{2}|20[0-2]\d)\b` может захватить посторонние числа из текста страницы (нет приоритета метаданных в Polona/NAC/LookAndLearn). | 🟢 Низкая |
| H-10 | **Менеджер создаёт коллекторы без `language`** (`cls(query=..., limit=...)`) — язык всегда по умолчанию `pl`. | 🟢 Низкая |

### 🔵 Рекомендации по улучшению

1. Вписать `EUROPEANA_API_KEY` и проверить источник Europeana (см. §3.3).
2. Для Polona/LookAndLearn/NAC — изучить актуальную разметку и, при необходимости,
   перейти на API/JSON-эндпоинты этих сервисов (например, szukajwarchiwach.gov.pl для NAC).
3. Передавать `language` в конструктор коллекторов из менеджера.
4. Добавить пагинацию (страницы) в HTML-коллекторы.
5. Автозаполнение `era` (например, из диапазона лет собранных ассетов объекта).
6. Добавить флаг `optimized` (0/1) отдельно от `downloaded`, либо дообрабатывать svg/png.
7. Проверить `robots.txt` источников перед масштабным сбором.

---

## 8. API-эндпоинты модуля (сводка)

| Метод | Путь | Описание |
|---|---|---|
| POST | `/api/collect` | Запустить сбор: `{object_name, sources, limit, city, latitude, longitude, era, description}` → `task_id` |
| GET | `/api/collect/status/{task_id}` | Статус фоновой задачи (`pending/running/done/error`, `collected`, `downloaded`, `errors`, `log`) |
| GET | `/api/objects` | Список всех исторических объектов (`?limit=&offset=`) |
| GET | `/api/objects/{object_id}/assets` | Ассеты объекта; фильтры `?source=&year=` |
| GET | `/api/assets?object_id=` | Ассеты объекта (совместимость со старым API) |
| GET | `/api/assets/download/{asset_id}` | Скачать файл; `?version=thumbnail|optimized|original` (по умолчанию optimized) |
| GET | `/api/assets/random` | Случайные скачанные ассеты `?object_id=&limit=10` |

---

## 9. Вывод

Модуль архитектурно чистый: единый интерфейс коллекторов, унифицированный формат
данных, graceful-degradation, идемпотентность, оптимизация в три версии и полный набор
API-эндпоинтов. Критический недостаток — **на практике данные поставляет только
Wikimedia Commons** (810/810), остальные источники либо закрыты антибот-защитой,
либо требуют API-ключа. Для наполнения AR-приложения контентом по Варшаве этого
достаточно, но расширение покрытия (другие города, другие типы материалов) требует
включения Europeana и пересмотра HTML-коллекторов.
