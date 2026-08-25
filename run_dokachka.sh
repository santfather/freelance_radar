#!/bin/bash
# Запуск докачки в отдельном окне Terminal (независимо от Cursor).
cd "$(dirname "$0")"
export PATH="/usr/bin:/bin:/usr/sbin:/sbin"
exec caffeinate -i -s .venv/bin/python -u collect_massive.py --limit 50 >> /tmp/collect_massive.log 2>&1
