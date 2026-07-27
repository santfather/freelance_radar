"""SQLite cache for scraped jobs and settings."""

import os
import aiosqlite
from models import Job, Category, Verdict

DB_PATH = os.getenv("DB_PATH", "radar.db")


def _safe_category(name: str) -> Category:
    """Convert string to Category, handling unknown names."""
    try:
        return Category(name)
    except ValueError:
        return Category.OTHER_IT



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
                gemini_model TEXT DEFAULT 'gemini-1.5-flash',
                ollama_model TEXT DEFAULT 'qwen2.5:14b',
                ollama_host TEXT DEFAULT 'http://localhost:11434',
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        """)
        # Performance indexes
        await db.execute("CREATE INDEX IF NOT EXISTS idx_jobs_analyzed ON jobs(analyzed)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_jobs_verdict ON jobs(verdict)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_jobs_category ON jobs(category)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_jobs_scraped_at ON jobs(scraped_at)")
        await db.commit()


# ── Jobs ─────────────────────────────────────────────────────────────────────

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
    category: str = None,
    verdict: str = None,
    analyzed: str = None,
    sort: str = "desc",
) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        where = []
        params = []
        if category and category != "all":
            where.append("category = ?")
            params.append(category)
        if verdict and verdict != "all":
            where.append("verdict = ?")
            params.append(verdict.upper())
        if analyzed is not None and analyzed != "all":
            where.append("analyzed = ?")
            params.append(1 if analyzed == "1" else 0)
        order = "DESC" if sort != "asc" else "ASC"
        sql = "SELECT * FROM jobs"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += f" ORDER BY scraped_at {order} LIMIT 500"
        async with db.execute(sql, params) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]


async def get_unanalyzed_jobs() -> list[Job]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM jobs WHERE analyzed=0 LIMIT 100") as cur:
            rows = await cur.fetchall()
            jobs = []
            for r in rows:
                r = dict(r)
                jobs.append(Job(
                    id=r["id"], title=r["title"], description=r["description"],
                    url=r["url"], source=r["source"],
                    category=_safe_category(r["category"]),
                    budget_raw=r["budget_raw"] or "",
                    budget_min=r["budget_min"], budget_max=r["budget_max"],
                    posted_at=r["posted_at"] or "",
                    verdict=Verdict(r["verdict"]),
                    verdict_reason=r["verdict_reason"] or "",
                    analyzed=bool(r["analyzed"]),
                ))
            return jobs


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


# ── Settings (key-value) ────────────────────────────────────────────────────

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
            "gemini_model": "gemini-1.5-flash",
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
