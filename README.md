# Freelance Radar 🎯

Парсер и AI-аналитик заказов с польских фриланс-бирж. Собирает заказы с нескольких площадок, анализирует их через локальную LLM (Ollama) и показывает, какие заказы стоит брать.

## Возможности

- **Парсинг 4 площадок:** Oferia, Useme, WorkConnect, Zleca
- **LLM-анализ:** каждый заказ проверяется через Ollama — вердикт TAKE/SKIP + причина + оценка сложности
- **Веб-интерфейс:** SPA с тёмной темой, фильтрацией по категориям и вердикту
- **Без Плейрайта:** парсинг статического HTML через httpx + BeautifulSoup

## Быстрый старт

```bash
# 1. Клонировать и перейти в директорию
cd freelance-radar

# 2. Быстрый запуск (создаёт venv, устанавливает зависимости)
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
# отредактировать .env при необходимости

# 5. Запустить
uvicorn main:app --port 8099 --host 0.0.0.0
```

Открой `http://localhost:8099` в браузере.

## Требования

- Python 3.11+
- [Ollama](https://ollama.com) с любой моделью (рекомендуется `qwen2.5:14b` или `mistral`):
  ```bash
  ollama pull qwen2.5:14b
  ```

## Переменные окружения (`.env`)

| Переменная | По умолчанию | Описание |
|---|---|---|
| `OLLAMA_MODEL` | `qwen2.5:14b` | Модель Ollama для анализа заказов |
| `OLLAMA_HOST` | `http://localhost:11434` | Адрес Ollama API |
| `DB_PATH` | `radar.db` | Путь к SQLite базе |

## API эндпоинты

| Метод | Путь | Описание |
|---|---|---|
| `GET` | `/` | SPA фронтенд |
| `POST` | `/api/refresh` | Запустить парсинг + анализ в фоне |
| `GET` | `/api/jobs?category=&verdict=` | Список заказов с фильтрацией |
| `GET` | `/api/stats` | Статистика + статус Ollama |
| `GET` | `/api/log` | Лог последнего запуска |

## Архитектура

```
freelance-radar/
├── main.py              # FastAPI приложение + роуты
├── database.py          # SQLite (aiosqlite), upsert, фильтры
├── models.py            # Job, Category, Verdict — модели данных
├── analyzer.py          # Ollama-анализ (TAKE/SKIP/UNKNOWN)
├── scrapers/
│   ├── base.py          # BaseScraper, категории, парсинг бюджета
│   ├── oferia.py        # Oferia.pl (3 категории, session-based)
│   ├── useme.py         # Useme.com (3 категории)
│   ├── workconnect.py   # WorkConnect.app (3 категории)
│   └── zleca.py         # Zleca.pl (3 категории)
├── templates/
│   └── index.html       # SPA фронтенд
├── start.sh             # Скрипт запуска
├── requirements.txt     # Зависимости
└── .env.example         # Шаблон конфигурации
```

## Дорожная карта

См. [ROADMAP.md](ROADMAP.md) — Telegram-бот, новые площадки, деплой, персонализация.

## Лицензия

MIT
