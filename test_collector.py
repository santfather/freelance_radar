"""Тестовый скрипт для модуля collectors.

Запускает сбор по объекту «Zamek Królewski» (или другому) и проверяет,
что файлы появляются в assets/ (оригинал + optimized + thumbnail), а БД
заполняется.

Пример запуска:
    source .venv/bin/activate
    python test_collector.py                     # все источники, лимит 5
    python test_collector.py --sources wikimedia # только Wikimedia
    python test_collector.py --limit 3 --query "Warsaw Old Town"
    python test_collector.py --century 18 --limit 10   # только 1701–1800
"""

import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from collectors.manager import CollectorManager  # noqa: E402
from collectors import COLLECTOR_REGISTRY  # noqa: E402
from database import (  # noqa: E402
    get_assets_by_object,
    get_historical_object_by_name,
    init_db,
)


async def main() -> int:
    parser = argparse.ArgumentParser(description="Тест коллекторов исторических материалов")
    parser.add_argument("--query", default="Zamek Królewski", help="Название объекта")
    parser.add_argument("--limit", type=int, default=5, help="Максимум файлов на источник")
    parser.add_argument("--sources", default="all",
                        help="Источники через запятую или 'all' "
                             f"({', '.join(COLLECTOR_REGISTRY)})")
    parser.add_argument("--city", default="", help="Город (иначе определяется из запроса)")
    parser.add_argument("--year-from", type=int, default=None,
                        help="Нижняя граница периода (например, 1500)")
    parser.add_argument("--year-to", type=int, default=None,
                        help="Верхняя граница периода (например, 1800)")
    parser.add_argument("--century", type=int, default=None,
                        help="Век: 18 → 1701–1800 (перекрывает year_from/year_to, "
                             "если они не заданы)")
    args = parser.parse_args()

    await init_db()
    sources = args.sources.strip()
    if sources.lower() != "all":
        sources = [s.strip() for s in sources.split(",") if s.strip()]

    period = args.century or (args.year_from or args.year_to)
    print(f"▶ Сбор «{args.query}» | источники: {sources} | лимит: {args.limit}"
          + (f" | период: {args.year_from or '…'}–{args.year_to or '…'}"
             + (f" (век {args.century})" if args.century else "")
             if period else "") + "\n")
    manager = CollectorManager(
        args.query, sources=sources, limit=args.limit, city=args.city,
        year_from=args.year_from, year_to=args.year_to, century=args.century,
    )
    result = await manager.run()

    for line in result["log"]:
        print(" ", line)

    if result["errors"]:
        print("\n⚠ Ошибки:")
        for e in result["errors"]:
            print(f"  - {e}")

    obj = await get_historical_object_by_name(args.query)
    if not obj:
        print("\n❌ Объект не сохранён в БД")
        return 1

    assets = await get_assets_by_object(obj["id"])
    downloaded = [a for a in assets if a["downloaded"]]
    versions_ok = 0
    print(f"\n📊 Объект id={obj['id']} «{obj['name']}» (slug={obj.get('slug', '')})")
    print(f"   Ассетов в БД: {len(assets)} | скачано: {len(downloaded)}")
    for a in assets[:10]:
        paths = [a.get("original_path"), a.get("optimized_path"), a.get("thumbnail_path")]
        on_disk = [p for p in paths if p and os.path.exists(p)]
        if a["downloaded"] and on_disk:
            versions_ok += 1
        marker = "✓" if a["downloaded"] and on_disk else ("✗" if a["error"] else "•")
        print(f"   {marker} [{a['source']}] {a['year'] or '—'} {a['title'][:45]}")
        for p in paths:
            if p:
                print(f"      {p} ({'есть' if os.path.exists(p) else 'нет'})")

    if not assets or not downloaded:
        print("\n⚠ Ничего не собрано. Проверьте сеть и доступность источников "
              "(Wikimedia и Europeana обычно работают; Polona/NAC/LookAndLearn "
              "могут быть защищены от ботов).")
        return 1

    if versions_ok == 0:
        print("\n⚠ Ассеты в БД есть, но ни одного файла на диске не найдено.")
        return 1

    print("\n✅ Тест пройден: файлы на диске (оригинал/optimized/thumbnail) и БД заполнены.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
