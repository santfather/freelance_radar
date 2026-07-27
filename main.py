"""Freelance Radar — FastAPI app.

Run: uvicorn main:app --reload --port 8099
Then open: http://localhost:8099
"""

import asyncio
import os
import logging
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, BackgroundTasks, Query
from fastapi.responses import HTMLResponse, JSONResponse

load_dotenv()

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("freelance-radar")

from analyzer import (
    get_analyzer,
    check_ollama_available,
    check_deepseek_available,
    check_gemini_available,
    PROVIDER_NAMES,
)
from database import (
    init_db,
    upsert_jobs,
    update_verdict,
    get_all_jobs,
    get_unanalyzed_jobs,
    get_unanalyzed_count,
    get_stats,
    get_setting,
    set_setting,
    get_all_settings,
    reset_all_analysis,
)
from scrapers import ALL_SCRAPERS

# ── Global state ──────────────────────────────────────────────────────────────
_is_scraping = False
_is_analyzing = False
_scrape_log: list[str] = []
_analyze_log: list[str] = []
_analyze_progress = 0
_analyze_total = 0
_scrape_running = False
_analyze_running = False
_analyze_current_provider = ""


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(title="Freelance Radar", lifespan=lifespan)


# ── Background tasks ──────────────────────────────────────────────────────────

async def _run_scrape():
    """Только парсинг (без анализа)."""
    global _is_scraping, _scrape_log, _scrape_running
    if _scrape_running:
        return
    _scrape_running = True
    _is_scraping = True
    _scrape_log = ["▶ Парсинг запущен..."]
    try:
        all_jobs = []
        for ScraperClass in ALL_SCRAPERS:
            scraper = ScraperClass()
            jobs = await scraper.scrape()
            all_jobs.extend(jobs)
            _scrape_log.append(f"✓ {scraper.source_name}: {len(jobs)} заказов")

        await upsert_jobs(all_jobs)
        _scrape_log.append(f"💾 Сохранено {len(all_jobs)} заказов в БД")

        pending = await get_unanalyzed_count()
        _scrape_log.append(f"📊 Ожидают анализа: {pending}")

        _scrape_log.append("✅ Парсинг завершён!")
        logger.info(f"Scraping done: {len(all_jobs)} jobs, {pending} unanalyzed")
    except Exception as e:
        _scrape_log.append(f"❌ Ошибка парсинга: {e}")
        logger.error(f"Scraping error: {e}")
    finally:
        _scrape_running = False
        _is_scraping = False


async def _run_analysis(provider: str):
    """Анализ всех непроанализированных заказов через указанного провайдера."""
    global _is_analyzing, _analyze_log, _analyze_progress, _analyze_total, _analyze_running, _analyze_current_provider
    if _analyze_running:
        return
    _analyze_running = True
    _is_analyzing = True
    _analyze_current_provider = provider
    _analyze_log = [f"▶ Анализ запущен (провайдер: {PROVIDER_NAMES.get(provider, provider)})..."]
    _analyze_progress = 0
    _analyze_total = 0

    try:
        analyzer = get_analyzer(provider)
        unanalyzed = await get_unanalyzed_jobs()
        _analyze_total = len(unanalyzed)
        _analyze_log.append(f"📊 Найдено {_analyze_total} заказов для анализа")

        if not unanalyzed:
            _analyze_log.append("✅ Нет заказов для анализа")
            return

        # Обработка пачками по 10 параллельно
        BATCH_SIZE = 10
        for batch_start in range(0, len(unanalyzed), BATCH_SIZE):
            batch = unanalyzed[batch_start:batch_start + BATCH_SIZE]
            tasks = []
            for job in batch:
                title_preview = job.title[:50]
                _analyze_log.append(f"  [{_analyze_progress + 1}/{_analyze_total}] Анализ: {title_preview}")
                tasks.append(_analyze_one_job(analyzer, job))

            results = await asyncio.gather(*tasks, return_exceptions=True)

            for job, result in zip(batch, results):
                if isinstance(result, Exception):
                    _analyze_log.append(f"  ❌ Ошибка: {result}")
                    logger.error(f"Analysis error for job {job.id}: {result}")
                else:
                    await update_verdict(job)
                    _analyze_log.append(f"  → {job.verdict.value}")
                _analyze_progress += 1

        _analyze_log.append(f"✅ Проанализировано {_analyze_total} заказов")
        logger.info(f"Analysis done: {_analyze_total} jobs via {provider}")
    except ValueError as e:
        _analyze_log.append(f"❌ Неизвестный провайдер: {e}")
        logger.error(f"Analysis provider error: {e}")
    except Exception as e:
        _analyze_log.append(f"❌ Ошибка анализа: {e}")
        logger.error(f"Analysis error: {e}")
    finally:
        _analyze_running = False
        _is_analyzing = False
        _analyze_current_provider = ""


async def _analyze_one_job(analyzer, job):
    """Проанализировать один заказ через выбранный анализатор."""
    result = await analyzer.analyze(
        title=job.title,
        category=job.category.value,
        budget=job.budget_raw or "not specified",
        description=job.description[:600] if job.description else "no description",
    )
    job.verdict = (
        job.verdict.__class__(result["verdict"])
        if result.get("verdict") in ("TAKE", "SKIP")
        else job.verdict.__class__("UNKNOWN")
    )
    job.verdict_reason = result.get("reason", "")
    job.complexity = result.get("complexity", 0)
    job.estimated_hours = result.get("estimated_hours", 0)
    job.analyzed = True
    return job


# ── API routes ────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index():
    with open("templates/index.html", "r", encoding="utf-8") as f:
        return f.read()


@app.post("/api/refresh")
async def refresh(background_tasks: BackgroundTasks):
    """Только парсинг (без анализа)."""
    global _scrape_running
    if _scrape_running:
        return JSONResponse({"status": "already_running"})
    background_tasks.add_task(_run_scrape)
    return JSONResponse({"status": "started"})


@app.post("/api/analyze")
async def analyze(
    background_tasks: BackgroundTasks,
    provider: str = Query(default=""),
    force: bool = Query(default=False),
):
    """Запустить анализ заказов.

    Параметр provider опционален — если не указан, берётся из сохранённой настройки.
    Параметр force=true — сбрасывает старые вердикты и переанализирует все заказы заново.
    """
    global _analyze_running
    if _analyze_running:
        return JSONResponse({"status": "already_running"})

    if not provider:
        provider = await get_setting("llm_provider", "ollama")

    if force:
        await reset_all_analysis()

    background_tasks.add_task(_run_analysis, provider)
    mode = "reanalysis" if force else "analysis"
    return JSONResponse({"status": f"{mode}_started", "provider": provider})


@app.get("/api/jobs")
async def jobs(
    category: str = Query(default="all"),
    verdict: str = Query(default="all"),
    analyzed: str = Query(default="all"),
    sort: str = Query(default="desc"),
):
    rows = await get_all_jobs(category=category, verdict=verdict, analyzed=analyzed, sort=sort)
    return JSONResponse(rows)


@app.get("/api/stats")
async def stats():
    data = await get_stats()
    unanalyzed = await get_unanalyzed_count()
    data["unanalyzed"] = unanalyzed
    data["scraping"] = _scrape_running
    data["analyzing"] = _analyze_running
    data["analyze_progress"] = _analyze_progress
    data["analyze_total"] = _analyze_total
    data["analyze_provider"] = _analyze_current_provider

    # Показываем лог в зависимости от того, что сейчас работает
    if _scrape_running:
        data["log"] = _scrape_log[-10:]
    elif _analyze_running:
        data["log"] = _analyze_log[-10:]
    else:
        # Показываем последний лог (приоритет анализу, потом парсингу)
        data["log"] = _analyze_log[-10:] if _analyze_log else _scrape_log[-10:]

    # Проверка доступности провайдера
    provider = await get_setting("llm_provider", "ollama")
    data["provider"] = provider
    data["provider_ok"] = False
    data["provider_msg"] = ""

    # Проверка доступности Ollama (для статуса)
    ollama_ok, ollama_msg = await check_ollama_available()
    data["ollama_ok"] = ollama_ok
    data["ollama_msg"] = ollama_msg

    available_providers = {}
    for p in ["ollama", "deepseek", "gemini"]:
        if p == "ollama":
            ok, msg = ollama_ok, ollama_msg
        elif p == "deepseek":
            ok, msg = await check_deepseek_available()
        else:
            ok, msg = await check_gemini_available()
        available_providers[p] = {"ok": ok, "msg": msg}
    data["available_providers"] = available_providers

    return JSONResponse(data)


@app.get("/api/log")
async def log():
    return JSONResponse({
        "scrape_log": _scrape_log,
        "analyze_log": _analyze_log,
        "scraping": _scrape_running,
        "analyzing": _analyze_running,
        "analyze_progress": _analyze_progress,
        "analyze_total": _analyze_total,
    })


@app.get("/api/status")
async def status():
    """Статус фоновых задач."""
    return JSONResponse({
        "scraping": _scrape_running,
        "analyzing": _analyze_running,
        "analyze_progress": _analyze_progress,
        "analyze_total": _analyze_total,
        "analyze_provider": _analyze_current_provider,
    })


@app.get("/api/settings")
async def settings_get():
    """Получить все настройки."""
    db_settings = await get_all_settings()
    provider = db_settings.get("llm_provider", os.getenv("LLM_PROVIDER", "ollama"))
    return JSONResponse({
        "provider": provider,
        "available_providers": {k: v for k, v in PROVIDER_NAMES.items()},
        **db_settings,
    })


@app.post("/api/settings")
async def settings_post(data: dict):
    """Обновить настройки."""
    if "provider" in data:
        provider = data["provider"].lower()
        if provider not in ("ollama", "deepseek", "gemini"):
            return JSONResponse(
                {"status": "error", "message": f"Unknown provider '{provider}'"},
                status_code=400,
            )
        await set_setting("llm_provider", provider)
    # Можно добавить другие настройки
    return JSONResponse({"status": "ok"})
