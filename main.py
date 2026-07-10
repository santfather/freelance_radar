"""Freelance Radar — FastAPI app.

Run: uvicorn main:app --reload --port 8099
Then open: http://localhost:8099
"""

import asyncio
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, BackgroundTasks, Query
from fastapi.responses import HTMLResponse, JSONResponse

load_dotenv()

from analyzer import analyze_job, check_ollama_available
from database import init_db, upsert_jobs, update_verdict, get_all_jobs, get_unanalyzed_jobs, get_stats
from scrapers import ALL_SCRAPERS

# ── Global state ──────────────────────────────────────────────────────────────
_is_scraping = False
_is_analyzing = False
_scrape_log: list[str] = []


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(title="Freelance Radar", lifespan=lifespan)


# ── Background tasks ──────────────────────────────────────────────────────────

async def _run_scrape():
    global _is_scraping, _scrape_log
    _is_scraping = True
    _scrape_log = ["▶ Scraping started..."]
    try:
        all_jobs = []
        for ScraperClass in ALL_SCRAPERS:
            scraper = ScraperClass()
            jobs = await scraper.scrape()
            all_jobs.extend(jobs)
            _scrape_log.append(f"✓ {scraper.source_name}: {len(jobs)} jobs")

        await upsert_jobs(all_jobs)
        _scrape_log.append(f"💾 Saved {len(all_jobs)} jobs to DB")

        # Auto-analyze after scraping
        _scrape_log.append("🧠 Starting Ollama analysis...")
        unanalyzed = await get_unanalyzed_jobs()
        ok, msg = await check_ollama_available()
        if not ok:
            _scrape_log.append(f"⚠ Ollama not available: {msg}")
        else:
            for job in unanalyzed:
                job = await analyze_job(job)
                await update_verdict(job)
            _scrape_log.append(f"✓ Analyzed {len(unanalyzed)} jobs")

        _scrape_log.append("✅ Done!")
    except Exception as e:
        _scrape_log.append(f"❌ Error: {e}")
    finally:
        _is_scraping = False


# ── API routes ────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index():
    with open("templates/index.html", "r", encoding="utf-8") as f:
        return f.read()


@app.post("/api/refresh")
async def refresh(background_tasks: BackgroundTasks):
    global _is_scraping
    if _is_scraping:
        return JSONResponse({"status": "already_running"})
    background_tasks.add_task(_run_scrape)
    return JSONResponse({"status": "started"})


@app.get("/api/jobs")
async def jobs(
    category: str = Query(default="all"),
    verdict: str = Query(default="all"),
):
    rows = await get_all_jobs(category=category, verdict=verdict)
    return JSONResponse(rows)


@app.get("/api/stats")
async def stats():
    data = await get_stats()
    data["scraping"] = _is_scraping
    data["log"] = _scrape_log[-10:]  # last 10 log lines
    ollama_ok, ollama_msg = await check_ollama_available()
    data["ollama_ok"] = ollama_ok
    data["ollama_msg"] = ollama_msg
    return JSONResponse(data)


@app.get("/api/log")
async def log():
    return JSONResponse({"log": _scrape_log, "running": _is_scraping})
