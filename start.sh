#!/bin/bash
# Freelance Radar — утренний запуск
# Использование: ./start.sh
# Или добавь в cron: 0 8 * * 1-5 /path/to/freelance-radar/start.sh

set -e
cd "$(dirname "$0")"

# Создать venv если нет
if [ ! -d ".venv" ]; then
  echo "📦 Создаю виртуальное окружение..."
  python3 -m venv .venv
  source .venv/bin/activate
  pip install -q -r requirements.txt
else
  source .venv/bin/activate
fi

# Создать .env из примера если нет
if [ ! -f ".env" ]; then
  cp .env.example .env
  echo "⚙️  Создан .env файл. Отредактируй при необходимости."
fi

echo "🚀 Запускаю Freelance Radar на http://localhost:8099"
echo "   Нажми Ctrl+C для остановки"
echo ""

uvicorn main:app --port 8099 --host 0.0.0.0
