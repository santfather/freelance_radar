"""Freelance Radar — FastAPI app.

Run: uvicorn main:app --reload --port 8099
Then open: http://localhost:8099
"""

import asyncio
import os
import logging
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, BackgroundTasks, Depends, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

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
from models import SettingsUpdate
from services.state import AppState


# ── Зависимость состояния ─────────────────────────────────────────────────────

async def get_state(request: Request) -> AppState:
    return request.app.state.app_state


# ── Lifespan ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.app_state = AppState()
    await init_db()
    yield


app = FastAPI(title="Freelance Radar", lifespan=lifespan)

BATCH_SIZE = 10


# ── Background tasks ──────────────────────────────────────────────────────────

async def _run_scrape(state: AppState):
    """Только парсинг (без анализа)."""
    if state.scraping:
        return
    state.scraping = True
    state.scrape_log = ["▶ Парсинг запущен..."]
    try:
        all_jobs = []
        for ScraperClass in ALL_SCRAPERS:
            scraper = ScraperClass()
            jobs = await scraper.scrape()
            all_jobs.extend(jobs)
            state.scrape_log.append(f"✓ {scraper.source_name}: {len(jobs)} заказов")

        await upsert_jobs(all_jobs)
        state.scrape_log.append(f"💾 Сохранено {len(all_jobs)} заказов в БД")

        pending = await get_unanalyzed_count()
        state.scrape_log.append(f"📊 Ожидают анализа: {pending}")

        state.scrape_log.append("✅ Парсинг завершён!")
        logger.info(f"Scraping done: {len(all_jobs)} jobs, {pending} unanalyzed")
    except Exception as e:
        state.scrape_log.append(f"❌ Ошибка парсинга: {e}")
        logger.error(f"Scraping error: {e}")
    finally:
        state.scraping = False


def _init_analysis(state: AppState, provider: str):
    state.analyze_log = [f"▶ Анализ запущен (провайдер: {PROVIDER_NAMES.get(provider, provider)})..."]
    state.analyze_progress = 0
    state.analyze_total = 0
    state.analyze_provider = provider


def _finalize_analysis(state: AppState):
    state.analyzing = False
    state.analyze_provider = ""
    state.analyze_log.append(f"✅ Проанализировано {state.analyze_total} заказов")


async def _process_batch(analyzer, batch, state: AppState):
    tasks = [_analyze_one_job(analyzer, job) for job in batch]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    for job, result in zip(batch, results):
        if isinstance(result, Exception):
            state.analyze_log.append(f"  ❌ Ошибка: {result}")
            logger.error(f"Analysis error for job {job.id}: {result}")
        else:
            await update_verdict(job)
            state.analyze_log.append(f"  → {job.verdict.value}")
        state.analyze_progress += 1


async def _process_all_batches(analyzer, state: AppState):
    unanalyzed = await get_unanalyzed_jobs()
    state.analyze_total = len(unanalyzed)
    state.analyze_log.append(f"📊 Найдено {state.analyze_total} заказов для анализа")

    if not unanalyzed:
        state.analyze_log.append("✅ Нет заказов для анализа")
        return

    for batch_start in range(0, len(unanalyzed), BATCH_SIZE):
        batch = unanalyzed[batch_start:batch_start + BATCH_SIZE]
        await _process_batch(analyzer, batch, state)


async def _run_analysis(provider: str, state: AppState):
    """Анализ всех непроанализированных заказов через указанного провайдера."""
    if state.analyzing:
        return
    state.analyzing = True
    _init_analysis(state, provider)
    try:
        analyzer = get_analyzer(provider)
        await _process_all_batches(analyzer, state)
    except ValueError as e:
        state.analyze_log.append(f"❌ Неизвестный провайдер: {e}")
        logger.error(f"Analysis provider error: {e}")
    except Exception as e:
        state.analyze_log.append(f"❌ Ошибка анализа: {e}")
        logger.error(f"Analysis error: {e}")
    finally:
        _finalize_analysis(state)


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


@app.get("/static/{path:path}")
async def static_files(path: str):
    return FileResponse(f"static/{path}")


@app.post("/api/refresh")
async def refresh(
    background_tasks: BackgroundTasks,
    state: AppState = Depends(get_state),
):
    """Только парсинг (без анализа)."""
    if state.scraping:
        return JSONResponse({"status": "already_running"})
    background_tasks.add_task(_run_scrape, state)
    return JSONResponse({"status": "started"})


@app.post("/api/analyze")
async def analyze(
    background_tasks: BackgroundTasks,
    provider: str = Query(default=""),
    force: bool = Query(default=False),
    state: AppState = Depends(get_state),
):
    """Запустить анализ заказов.

    Параметр provider опционален — если не указан, берётся из сохранённой настройки.
    Параметр force=true — сбрасывает старые вердикты и переанализирует все заказы заново.
    """
    if state.analyzing:
        return JSONResponse({"status": "already_running"})

    if not provider:
        provider = await get_setting("llm_provider", "ollama")

    if force:
        await reset_all_analysis()

    background_tasks.add_task(_run_analysis, provider, state)
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
async def stats(state: AppState = Depends(get_state)):
    data = await get_stats()
    unanalyzed = await get_unanalyzed_count()
    data["unanalyzed"] = unanalyzed
    data["scraping"] = state.scraping
    data["analyzing"] = state.analyzing
    data["analyze_progress"] = state.analyze_progress
    data["analyze_total"] = state.analyze_total
    data["analyze_provider"] = state.analyze_provider

    # Показываем лог в зависимости от того, что сейчас работает
    if state.scraping:
        data["log"] = state.scrape_log[-10:]
    elif state.analyzing:
        data["log"] = state.analyze_log[-10:]
    else:
        # Показываем последний лог (приоритет анализу, потом парсингу)
        data["log"] = state.analyze_log[-10:] if state.analyze_log else state.scrape_log[-10:]

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
async def log(state: AppState = Depends(get_state)):
    return JSONResponse({
        "scrape_log": state.scrape_log,
        "analyze_log": state.analyze_log,
        "scraping": state.scraping,
        "analyzing": state.analyzing,
        "analyze_progress": state.analyze_progress,
        "analyze_total": state.analyze_total,
    })


@app.get("/api/status")
async def status(state: AppState = Depends(get_state)):
    """Статус фоновых задач."""
    return JSONResponse({
        "scraping": state.scraping,
        "analyzing": state.analyzing,
        "analyze_progress": state.analyze_progress,
        "analyze_total": state.analyze_total,
        "analyze_provider": state.analyze_provider,
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
async def settings_post(data: SettingsUpdate):
    """Обновить настройки."""
    if data.provider:
        provider = data.provider.lower()
        if provider not in ("ollama", "deepseek", "gemini"):
            return JSONResponse(
                {"status": "error", "message": f"Unknown provider '{provider}'"},
                status_code=400,
            )
        await set_setting("llm_provider", provider)
    return JSONResponse({"status": "ok"})
