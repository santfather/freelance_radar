"""SQLite cache for scraped jobs."""

import json
import os
import aiosqlite
from models import Job, Category, Verdict

DB_PATH = os.getenv("DB_PATH", "radar.db")


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
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


async def get_all_jobs(category: str = None, verdict: str = None) -> list[dict]:
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
        sql = "SELECT * FROM jobs"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY scraped_at DESC LIMIT 500"
        async with db.execute(sql, params) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]


async def get_unanalyzed_jobs() -> list[Job]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM jobs WHERE analyzed=0") as cur:
            rows = await cur.fetchall()
            jobs = []
            for r in rows:
                r = dict(r)
                jobs.append(Job(
                    id=r["id"], title=r["title"], description=r["description"],
                    url=r["url"], source=r["source"],
                    category=Category(r["category"]),
                    budget_raw=r["budget_raw"] or "",
                    budget_min=r["budget_min"], budget_max=r["budget_max"],
                    posted_at=r["posted_at"] or "",
                    verdict=Verdict(r["verdict"]),
                    verdict_reason=r["verdict_reason"] or "",
                    analyzed=bool(r["analyzed"]),
                ))
            return jobs


async def get_stats() -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM jobs") as c:
            total = (await c.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM jobs WHERE analyzed=1") as c:
            analyzed = (await c.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM jobs WHERE verdict='TAKE'") as c:
            take = (await c.fetchone())[0]
        return {"total": total, "analyzed": analyzed, "take": take}
