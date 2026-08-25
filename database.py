"""SQLite cache for scraped jobs and settings."""

import json
import os
from typing import Optional

import aiosqlite
from models import Job

DB_PATH = os.getenv("DB_PATH", "radar.db")

# Транслитерация для slug'ов (для старых объектов, добавленных до колонки slug)
_SLUG_TRANSLIT = str.maketrans({
    "ą": "a", "ć": "c", "ę": "e", "ł": "l", "ń": "n",
    "ó": "o", "ś": "s", "ź": "z", "ż": "z",
    "ü": "u", "ö": "o", "ä": "a", "ß": "ss", "é": "e",
})


def _slugify(text: str) -> str:
    import re as _re

    text = (text or "").lower().translate(_SLUG_TRANSLIT)
    text = _re.sub(r"[^a-z0-9]+", "_", text)
    return text.strip("_")


async def _ensure_columns(db, table: str, columns: dict[str, str]):
    """Добавить недостающие колонки в существующую таблицу (SQLite ALTER)."""
    async with db.execute(f"PRAGMA table_info({table})") as cur:
        existing = {row[1] for row in await cur.fetchall()}
    for name, ddl in columns.items():
        if name not in existing:
            await db.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")


async def _backfill_object_slugs(db):
    """Проставить slug для объектов, у которых он пустой."""
    async with db.execute(
        "SELECT id, name FROM historical_objects WHERE slug IS NULL OR slug = ''"
    ) as cur:
        rows = await cur.fetchall()
    for obj_id, name in rows:
        slug = _slugify(name)
        await db.execute(
            "UPDATE historical_objects SET slug=? WHERE id=?", (slug, obj_id)
        )


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        # Jobs table
        await db.execute("""
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                title TEXT,
                description TEXT,
                url TEXT,
                source TEXT,
                category TEXT,
                budget_raw TEXT,
                budget_min INTEGER,
                budget_max INTEGER,
                posted_at TEXT,
                verdict TEXT DEFAULT 'UNKNOWN',
                verdict_reason TEXT DEFAULT '',
                complexity INTEGER DEFAULT 0,
                estimated_hours INTEGER DEFAULT 0,
                analyzed INTEGER DEFAULT 0,
                scraped_at TEXT DEFAULT (datetime('now'))
            )
        """)
        # Settings table (key-value)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)
        # Users table
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                is_admin INTEGER DEFAULT 0,
                created_at TEXT DEFAULT (datetime('now'))
            )
        """)
        # User settings table (LLM credentials per user)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS user_settings (
                user_id INTEGER PRIMARY KEY,
                deepseek_api_key TEXT DEFAULT '',
                deepseek_model TEXT DEFAULT 'deepseek-chat',
                gemini_api_key TEXT DEFAULT '',
                gemini_model TEXT DEFAULT 'gemini-2.5-flash',
                ollama_model TEXT DEFAULT 'qwen2.5:14b',
                ollama_host TEXT DEFAULT 'http://localhost:11434',
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        """)
        # Historical media (collectors module)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS historical_objects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                slug TEXT,
                latitude REAL,
                longitude REAL,
                description TEXT,
                city TEXT,
                era TEXT,
                created_at TEXT DEFAULT (datetime('now'))
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS historical_assets (
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
                original_width INTEGER,
                original_height INTEGER,
                tags TEXT,
                photogrammetry_ready INTEGER DEFAULT 0,
                material_type TEXT DEFAULT 'unknown',
                created_at TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (object_id) REFERENCES historical_objects(id)
            )
        """)
        # Миграции для уже существующих БД — добавить недостающие колонки
        # (SQLite не разрешает функции/CURRENT_TIMESTAMP в default для ADD COLUMN,
        # поэтому created_at добавляется без default и заполняется отдельно)
        await _ensure_columns(db, "historical_objects", {
            "slug": "TEXT",
            "city": "TEXT",
            "created_at": "TEXT",
        })
        await _ensure_columns(db, "historical_assets", {
            "original_path": "TEXT",
            "optimized_path": "TEXT",
            "thumbnail_path": "TEXT",
            "width_optimized": "INTEGER",
            "height_optimized": "INTEGER",
            "file_size_optimized": "INTEGER",
            "error": "TEXT",
            "created_at": "TEXT",
            "original_width": "INTEGER",
            "original_height": "INTEGER",
            "tags": "TEXT",
            "photogrammetry_ready": "INTEGER DEFAULT 0",
            "material_type": "TEXT DEFAULT 'unknown'",
        })
        # Backfill слагов и дат создания для объектов, добавленных до миграции
        await _backfill_object_slugs(db)
        await db.execute(
            "UPDATE historical_objects SET created_at=datetime('now') "
            "WHERE created_at IS NULL"
        )
        await db.execute(
            "UPDATE historical_assets SET created_at=datetime('now') "
            "WHERE created_at IS NULL"
        )
        # Performance indexes
        await db.execute("CREATE INDEX IF NOT EXISTS idx_jobs_analyzed ON jobs(analyzed)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_jobs_verdict ON jobs(verdict)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_jobs_category ON jobs(category)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_jobs_scraped_at ON jobs(scraped_at)")
        await db.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_historical_assets_obj_url "
            "ON historical_assets(object_id, file_url)"
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_historical_assets_object_id "
            "ON historical_assets(object_id)"
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_historical_assets_downloaded "
            "ON historical_assets(downloaded)"
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_historical_assets_source "
            "ON historical_assets(source)"
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_historical_assets_year "
            "ON historical_assets(year)"
        )
        await db.commit()


async def upsert_jobs(jobs: list[Job]):
    async with aiosqlite.connect(DB_PATH) as db:
        for job in jobs:
            await db.execute("""
                INSERT INTO jobs (id, title, description, url, source, category,
                    budget_raw, budget_min, budget_max, posted_at,
                    verdict, verdict_reason, complexity, estimated_hours, analyzed)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    title=excluded.title,
                    description=excluded.description,
                    budget_raw=excluded.budget_raw,
                    budget_min=excluded.budget_min,
                    budget_max=excluded.budget_max,
                    posted_at=excluded.posted_at,
                    scraped_at=datetime('now')
            """, (
                job.id, job.title, job.description, job.url, job.source,
                job.category.value, job.budget_raw, job.budget_min, job.budget_max,
                job.posted_at, job.verdict.value, job.verdict_reason,
                job.complexity, job.estimated_hours, int(job.analyzed),
            ))
        await db.commit()


async def update_verdict(job: Job):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            UPDATE jobs SET verdict=?, verdict_reason=?, complexity=?,
                estimated_hours=?, analyzed=1
            WHERE id=?
        """, (job.verdict.value, job.verdict_reason, job.complexity,
               job.estimated_hours, job.id))
        await db.commit()


async def get_all_jobs(
    category: Optional[str] = None,
    verdict: Optional[str] = None,
    analyzed: Optional[bool] = None,
    sort: str = "desc",
    limit: int = 500,
    offset: int = 0,
) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        where = []
        params = []
        if category:
            where.append("category = ?")
            params.append(category)
        if verdict:
            where.append("verdict = ?")
            params.append(verdict.upper())
        if analyzed is not None:
            where.append("analyzed = ?")
            params.append(1 if analyzed else 0)
        sql = "SELECT * FROM jobs"
        if where:
            sql += " WHERE " + " AND ".join(where)
        if sort != "asc":
            sql += " ORDER BY scraped_at DESC"
        else:
            sql += " ORDER BY scraped_at ASC"
        sql += " LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        async with db.execute(sql, params) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]


async def get_jobs_count(
    category: Optional[str] = None,
    verdict: Optional[str] = None,
    analyzed: Optional[bool] = None,
) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        where = []
        params = []
        if category:
            where.append("category = ?")
            params.append(category)
        if verdict:
            where.append("verdict = ?")
            params.append(verdict.upper())
        if analyzed is not None:
            where.append("analyzed = ?")
            params.append(1 if analyzed else 0)
        sql = "SELECT COUNT(*) FROM jobs"
        if where:
            sql += " WHERE " + " AND ".join(where)
        async with db.execute(sql, params) as c:
            return (await c.fetchone())[0]


async def get_unanalyzed_jobs() -> list[Job]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM jobs WHERE analyzed=0 LIMIT 100") as cur:
            rows = await cur.fetchall()
            return [Job.from_db_row(dict(r)) for r in rows]


async def get_unanalyzed_count() -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM jobs WHERE analyzed=0") as c:
            return (await c.fetchone())[0]


async def get_stats() -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("""
            SELECT
                COUNT(*) AS total,
                IFNULL(SUM(CASE WHEN analyzed=1 THEN 1 ELSE 0 END), 0) AS analyzed,
                IFNULL(SUM(CASE WHEN verdict='TAKE' THEN 1 ELSE 0 END), 0) AS take
            FROM jobs
        """) as c:
            row = await c.fetchone()
            return {"total": row[0], "analyzed": row[1], "take": row[2]}


async def reset_all_analysis():
    """Сбросить статус анализа для всех заказов — очистить вердикты и выставить analyzed=0."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            UPDATE jobs SET
                analyzed=0,
                verdict='UNKNOWN',
                verdict_reason='',
                complexity=0,
                estimated_hours=0
        """)
        await db.commit()


async def get_setting(key: str, default: str = "") -> str:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT value FROM settings WHERE key=?", (key,)) as c:
            row = await c.fetchone()
            return row[0] if row else default


async def set_setting(key: str, value: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
        await db.commit()


async def get_all_settings() -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT key, value FROM settings") as c:
            rows = await c.fetchall()
            return dict(rows)


# ── Users ───────────────────────────────────────────────────────────────────

async def create_user(email: str, password_hash: str) -> int:
    """Создать пользователя. Возвращает его id. Первый пользователь — admin."""
    async with aiosqlite.connect(DB_PATH) as db:
        # Check if this is the first user
        async with db.execute("SELECT COUNT(*) FROM users") as c:
            count = (await c.fetchone())[0]
        is_admin = 1 if count == 0 else 0

        cursor = await db.execute(
            "INSERT INTO users (email, password_hash, is_admin) VALUES (?, ?, ?)",
            (email, password_hash, is_admin),
        )
        user_id = cursor.lastrowid

        # Auto-create user_settings row
        await db.execute(
            "INSERT INTO user_settings (user_id) VALUES (?)",
            (user_id,),
        )
        await db.commit()
        return user_id


async def get_user_by_email(email: str) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM users WHERE email=?", (email,)) as c:
            row = await c.fetchone()
            return dict(row) if row else None


async def get_user_by_id(user_id: int) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM users WHERE id=?", (user_id,)) as c:
            row = await c.fetchone()
            return dict(row) if row else None


# ── User Settings (LLM credentials per user) ────────────────────────────────

async def get_user_settings(user_id: int) -> dict:
    """Получить настройки LLM для пользователя. Если нет — вернуть умолчания."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM user_settings WHERE user_id=?", (user_id,)
        ) as c:
            row = await c.fetchone()
            if row:
                return dict(row)
        # Defaults
        return {
            "user_id": user_id,
            "deepseek_api_key": "",
            "deepseek_model": "deepseek-chat",
            "gemini_api_key": "",
            "gemini_model": "gemini-2.5-flash",
            "ollama_model": "qwen2.5:14b",
            "ollama_host": "http://localhost:11434",
        }


async def update_user_settings(user_id: int, settings: dict):
    """Обновить настройки LLM для пользователя."""
    async with aiosqlite.connect(DB_PATH) as db:
        # Ensure row exists
        async with db.execute(
            "SELECT 1 FROM user_settings WHERE user_id=?", (user_id,)
        ) as c:
            exists = await c.fetchone()

        if not exists:
            await db.execute(
                "INSERT INTO user_settings (user_id) VALUES (?)", (user_id,)
            )

        fields = []
        values = []
        for key in ("deepseek_api_key", "deepseek_model", "gemini_api_key",
                     "gemini_model", "ollama_model", "ollama_host"):
            if key in settings:
                fields.append(f"{key}=?")
                values.append(settings[key])

        if fields:
            values.append(user_id)
            await db.execute(
                f"UPDATE user_settings SET {', '.join(fields)} WHERE user_id=?",
                values,
            )
        await db.commit()


# ── Historical objects & assets (collectors) ────────────────────────────────

async def upsert_historical_object(
    name: str,
    latitude: Optional[float] = None,
    longitude: Optional[float] = None,
    description: str = "",
    era: str = "",
    city: str = "",
    slug: str = "",
) -> int:
    """Создать или обновить исторический объект. Возвращает его id."""
    city = city or ""
    slug = slug or _slugify(name)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO historical_objects
                (name, slug, latitude, longitude, description, city, era, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))
            ON CONFLICT(name) DO UPDATE SET
                slug=excluded.slug,
                latitude=excluded.latitude,
                longitude=excluded.longitude,
                description=excluded.description,
                city=excluded.city,
                era=excluded.era
        """, (name, slug, latitude, longitude, description, city, era))
        await db.commit()
        async with db.execute(
            "SELECT id FROM historical_objects WHERE name=?", (name,)
        ) as c:
            row = await c.fetchone()
            return int(row[0]) if row else 0


async def get_historical_object(object_id: int) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM historical_objects WHERE id=?", (object_id,)
        ) as c:
            row = await c.fetchone()
            return dict(row) if row else None


async def get_historical_object_by_name(name: str) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM historical_objects WHERE name=?", (name,)
        ) as c:
            row = await c.fetchone()
            return dict(row) if row else None


async def list_historical_objects(limit: int = 200, offset: int = 0) -> list[dict]:
    """Список всех исторических объектов в БД."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM historical_objects ORDER BY id DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ) as c:
            rows = await c.fetchall()
            return [dict(r) for r in rows]


async def upsert_asset(object_id: int, asset: dict) -> int:
    """Сохранить ассет для объекта. Уникальность — по (object_id, file_url).

    При повторном сборе обновляются только метаданные; local_path и
    downloaded сохраняются, чтобы не качать файл заново.
    """
    tags = asset.get("tags") or []
    tags_json = json.dumps(tags[:20], ensure_ascii=False) if tags else ""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO historical_assets
                (object_id, title, source_url, file_url, file_type,
                 thumbnail_url, description, year, source, local_path,
                 downloaded, tags, material_type, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
            ON CONFLICT(object_id, file_url) DO UPDATE SET
                title=excluded.title,
                source_url=excluded.source_url,
                file_type=excluded.file_type,
                thumbnail_url=excluded.thumbnail_url,
                description=excluded.description,
                year=excluded.year,
                source=excluded.source,
                tags=excluded.tags,
                material_type=excluded.material_type
        """, (
            object_id,
            asset.get("title", ""),
            asset.get("source_url", ""),
            asset.get("file_url", ""),
            asset.get("file_type", ""),
            asset.get("thumbnail_url", ""),
            asset.get("description", ""),
            asset.get("year", ""),
            asset.get("source", ""),
            asset.get("local_path") or "",
            int(asset.get("downloaded", 0)),
            tags_json,
            asset.get("material_type") or "unknown",
        ))
        await db.commit()
        async with db.execute(
            "SELECT id, local_path, downloaded FROM historical_assets "
            "WHERE object_id=? AND file_url=?",
            (object_id, asset.get("file_url", "")),
        ) as c:
            row = await c.fetchone()
            return int(row[0]) if row else 0


async def mark_asset_downloaded(asset_id: int, local_path: str, error: str = ""):
    """Отметить, что файл ассета успешно скачан (и очистить ошибку)."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE historical_assets SET local_path=?, downloaded=1, error=? WHERE id=?",
            (local_path, error, asset_id),
        )
        await db.commit()


async def mark_asset_error(asset_id: int, error: str):
    """Зафиксировать ошибку обработки ассета."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE historical_assets SET downloaded=0, error=? WHERE id=?",
            (error, asset_id),
        )
        await db.commit()


async def update_asset_paths(asset_id: int, processed: dict):
    """Сохранить пути к трём версиям файла и метаданные оптимизации."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            UPDATE historical_assets SET
                original_path=?,
                optimized_path=?,
                thumbnail_path=?,
                width_optimized=?,
                height_optimized=?,
                file_size_optimized=?,
                original_width=?,
                original_height=?,
                photogrammetry_ready=?,
                downloaded=?,
                error=?
            WHERE id=?
        """, (
            processed.get("original_path") or "",
            processed.get("optimized_path") or "",
            processed.get("thumbnail_path") or "",
            processed.get("width_optimized"),
            processed.get("height_optimized"),
            processed.get("file_size_optimized"),
            processed.get("original_width"),
            processed.get("original_height"),
            int(processed.get("photogrammetry_ready", 0)),
            int(processed.get("downloaded", 0)),
            processed.get("error") or "",
            asset_id,
        ))
        await db.commit()


async def update_object_era(object_id: int, era: str):
    """Автозаполнение era (исторический период) объекта диапазоном годов."""
    if not era:
        return
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE historical_objects SET era=? WHERE id=? AND (era IS NULL OR era='')",
            (era, object_id),
        )
        await db.commit()


async def backfill_era() -> int:
    """Заполнить era (диапазон веков римскими цифрами) по годам ассетов.

    Для каждого объекта по всем ассетам с известными годами вычисляется
    диапазон веков через `collectors.utils.century_era` (например,
    «XVI–XVIII вв.» или «XIX в.») и обновляется поле era. Объекты без
    ассетов с годами не трогаются. Возвращает число обновлённых объектов.

    Запускается после массового сбора (в конце collect_massive.py), чтобы
    охватить и старые объекты, собранные до появления этого поля.
    """
    # Ленивый импорт: collectors.utils не зависит от database, но такой порядок
    # гарантирует отсутствие цикла при инициализации пакета collectors.
    from collectors.utils import century_era, coerce_year

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT id FROM historical_objects ORDER BY id"
        ) as c:
            objects = await c.fetchall()

        updated = 0
        for obj in objects:
            obj_id = obj["id"]
            async with db.execute(
                "SELECT year FROM historical_assets "
                "WHERE object_id=? AND year IS NOT NULL AND year != ''",
                (obj_id,),
            ) as c:
                rows = await c.fetchall()
            years = [y for r in rows if (y := coerce_year(r["year"])) is not None]
            era = century_era(years)
            if not era:
                continue
            await db.execute(
                "UPDATE historical_objects SET era=? WHERE id=?",
                (era, obj_id),
            )
            updated += 1
        await db.commit()
        return updated


async def backfill_material_types() -> int:
    """Переопределить material_type всех ассетов по правилам детекции.

    Применяет `collectors.utils.detect_material_type` (ключевые слова в
    title/description с дефолтом по источнику) ко всем ассетам в БД —
    в том числе к собранным до появления поля. Возвращает число обновлённых
    записей. Запускается после массового сбора в collect_massive.py.
    """
    from collectors.utils import detect_material_type

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT id, source, title, description, material_type "
            "FROM historical_assets ORDER BY id"
        ) as c:
            assets = await c.fetchall()

        updated = 0
        for asset in assets:
            new_type = detect_material_type(
                asset["source"],
                asset["title"],
                asset["description"],
            )
            if new_type == asset["material_type"]:
                continue
            await db.execute(
                "UPDATE historical_assets SET material_type=? WHERE id=?",
                (new_type, asset["id"]),
            )
            updated += 1
        await db.commit()
        return updated


async def get_asset(asset_id: int) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM historical_assets WHERE id=?", (asset_id,)
        ) as c:
            row = await c.fetchone()
            return dict(row) if row else None


async def get_assets_by_object(
    object_id: int,
    source: Optional[str] = None,
    year: Optional[str] = None,
) -> list[dict]:
    """Ассеты объекта с опциональными фильтрами по источнику и году."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        sql = "SELECT * FROM historical_assets WHERE object_id=?"
        params: list = [object_id]
        if source:
            sql += " AND source=?"
            params.append(source)
        if year:
            sql += " AND year=?"
            params.append(year)
        sql += " ORDER BY id"
        async with db.execute(sql, params) as c:
            rows = await c.fetchall()
            return [dict(r) for r in rows]


async def get_random_assets(
    object_id: Optional[int] = None, limit: int = 10
) -> list[dict]:
    """Случайные скачанные ассеты (для превью на карте AR-приложения)."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        limit = max(1, min(int(limit), 100))
        if object_id:
            sql = ("SELECT * FROM historical_assets WHERE object_id=? "
                   "AND downloaded=1 ORDER BY RANDOM() LIMIT ?")
            params: list = [object_id, limit]
        else:
            sql = ("SELECT * FROM historical_assets WHERE downloaded=1 "
                   "ORDER BY RANDOM() LIMIT ?")
            params = [limit]
        async with db.execute(sql, params) as c:
            rows = await c.fetchall()
            return [dict(r) for r in rows]


async def get_collect_stats(object_id: int) -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT COUNT(*) AS total, "
            "IFNULL(SUM(CASE WHEN downloaded=1 THEN 1 ELSE 0 END), 0) AS downloaded "
            "FROM historical_assets WHERE object_id=?",
            (object_id,),
        ) as c:
            row = await c.fetchone()
            return {"total": row[0], "downloaded": row[1]}
