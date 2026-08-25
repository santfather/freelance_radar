"""Freelance Radar — FastAPI app.

Run: uvicorn main:app --reload --port 8099
Then open: http://localhost:8099
"""

import asyncio
import os
import time
import uuid
import logging
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, BackgroundTasks, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

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
    DeepSeekAnalyzer,
    GeminiAnalyzer,
    OllamaAnalyzer,
)
from database import (
    init_db,
    upsert_jobs,
    update_verdict,
    get_all_jobs,
    get_jobs_count,
    get_unanalyzed_jobs,
    get_unanalyzed_count,
    get_stats,
    get_setting,
    set_setting,
    get_all_settings,
    reset_all_analysis,
    create_user,
    get_user_by_email,
    get_user_by_id,
    get_user_settings,
    update_user_settings,
    get_historical_object,
    get_historical_object_by_name,
    list_historical_objects,
    get_assets_by_object,
    get_asset,
    get_random_assets,
)
from scrapers import ALL_SCRAPERS
from collectors import COLLECTOR_REGISTRY
from collectors.manager import CollectorManager
from models import SettingsUpdate, UserRegister, UserLogin, SettingsUpdateFull, TestConnectionRequest, CollectRequest, MAX_DESC_LENGTH
from services.state import AppState, CollectTaskState
from auth import hash_password, verify_password, create_access_token, decode_token

# ── Безопасность ─────────────────────────────────────────────────────────────

security = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> dict:
    """Извлекает и проверяет JWT-токен, возвращает данные пользователя."""
    if credentials is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    token = credentials.credentials
    try:
        payload = decode_token(token)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid token")
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token")
    user = await get_user_by_id(int(user_id))
    if user is None:
        raise HTTPException(status_code=401, detail="User not found")
    return user


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

BATCH_SIZE = 10  # параллельных LLM-запросов; превышение может вызвать rate limiting


# ── Background tasks ──────────────────────────────────────────────────────────

async def _run_scrape(state: AppState):
    if state.scraping:
        return
    state.stats_cache = None
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


# Обрабатываем пачками по BATCH_SIZE — asyncio.gather отправляет запросы
# параллельно, что ускоряет анализ. return_exceptions=True не даёт одному
# сбою обрушить всю пачку.
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
    state.stats_cache = None
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
        description=job.description[:MAX_DESC_LENGTH] if job.description else "no description",
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


# ── Background task: сбор исторических материалов ───────────────────────────

async def _run_collect(
    state: AppState,
    task_id: str,
    object_name: str,
    sources: list[str],
    limit: int,
    era: str,
    city: str,
    latitude: float | None,
    longitude: float | None,
    description: str,
    mode: str = "general",
    year_from: int | None = None,
    year_to: int | None = None,
    century: int | None = None,
):
    task = state.collect_tasks.get(task_id)
    if not task:
        return
    task.status = "running"
    try:
        manager = CollectorManager(
            object_name=object_name,
            sources=sources,
            limit=limit,
            era=era,
            city=city,
            latitude=latitude,
            longitude=longitude,
            description=description,
            mode=mode,
            year_from=year_from,
            year_to=year_to,
            century=century,
        )
        result = await manager.run()
        task.status = "done"
        task.object_id = result["object_id"]
        task.collected = result["collected"]
        task.downloaded = result["downloaded"]
        task.errors = result["errors"]
        task.log = result["log"]
    except Exception as e:
        task.status = "error"
        task.errors.append(str(e))
        task.log.append(f"❌ Ошибка сбора: {e}")
        logger.error("Collect task %s error: %s", task_id, e)


# ── API routes: Public ───────────────────────────────────────────────────────

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
    limit: int = Query(default=10, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    cat_arg = category if category != "all" else None
    verdict_arg = verdict if verdict != "all" else None
    analyzed_arg = None if analyzed == "all" else (analyzed == "1")
    rows = await get_all_jobs(category=cat_arg, verdict=verdict_arg, analyzed=analyzed_arg, sort=sort, limit=limit, offset=offset)
    total = await get_jobs_count(category=cat_arg, verdict=verdict_arg, analyzed=analyzed_arg)
    return JSONResponse({"jobs": rows, "total": total})


@app.get("/api/stats")
async def stats(state: AppState = Depends(get_state)):
    now = time.time()
    if state.stats_cache and (now - state.stats_cache_time) < state.STATS_CACHE_TTL:
        data = state.stats_cache.copy()
    else:
        data = await get_stats()
        state.stats_cache = data
        state.stats_cache_time = now
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


# ── API routes: Collector (исторические материалы) ──────────────────────────

@app.post("/api/collect")
async def collect(
    data: CollectRequest,
    background_tasks: BackgroundTasks,
    state: AppState = Depends(get_state),
):
    """Запустить сбор исторических материалов по названию объекта.

    Тело запроса: {"object_name": "Zamek Królewski",
                   "sources": ["wikimedia", "polona"], "limit": 50,
                   "city": "Warsaw", "latitude": 52.2476, "longitude": 21.0141,
                   "year_from": 1500, "year_to": 1800}.
    `sources` может быть списком ключей коллекторов или строкой "all".
    Период задаётся через `year_from`/`year_to` или одним `century`
    (например, 18 → 1701–1800).
    Возвращает task_id для отслеживания через /api/collect/status/{task_id}.
    """
    task_id = uuid.uuid4().hex[:12]
    sources = _normalize_sources(data.sources)
    task = CollectTaskState(
        id=task_id,
        object_name=data.object_name.strip(),
        sources=sources,
        limit=data.limit,
        mode=data.mode,
        created_at=time.time(),
    )
    state.collect_tasks[task_id] = task
    background_tasks.add_task(
        _run_collect,
        state, task_id,
        data.object_name.strip(), sources, data.limit,
        data.era, data.city, data.latitude, data.longitude, data.description,
        data.mode, data.year_from, data.year_to, data.century,
    )
    return JSONResponse({"task_id": task_id, "status": "started", "sources": sources})


def _normalize_sources(sources) -> list[str]:
    """Привести sources к списку ключей коллекторов (поддержка 'all')."""
    if isinstance(sources, str):
        if sources.strip().lower() == "all":
            return list(COLLECTOR_REGISTRY.keys())
        return [s.strip().lower() for s in sources.split(",") if s.strip()]
    return [s.lower() for s in sources]


@app.get("/api/collect/status/{task_id}")
async def collect_status(task_id: str, state: AppState = Depends(get_state)):
    """Статус задачи сбора: собранные/скачанные файлы, ошибки, лог."""
    task = state.collect_tasks.get(task_id)
    if not task:
        return JSONResponse({"error": "task not found"}, status_code=404)
    return JSONResponse({
        "task_id": task.id,
        "status": task.status,
        "object_name": task.object_name,
        "sources": task.sources,
        "limit": task.limit,
        "object_id": task.object_id,
        "collected": task.collected,
        "downloaded": task.downloaded,
        "errors": task.errors,
        "log": task.log,
        "created_at": task.created_at,
    })


@app.get("/api/assets")
async def assets(
    object_id: int = Query(default=None),
    object_name: str = Query(default=None),
):
    """Список сохранённых ассетов для объекта (для AR-приложения).

    Параметр `object_id` или `object_name` — обязательно.
    """
    if object_id is None and object_name:
        obj = await get_historical_object_by_name(object_name.strip())
        if obj:
            object_id = obj["id"]
    if object_id is None:
        return JSONResponse(
            {"error": "object_id or object_name required"}, status_code=400
        )
    obj = await get_historical_object(object_id)
    rows = await get_assets_by_object(object_id)
    return JSONResponse({"object": obj, "assets": rows})


@app.get("/api/objects")
async def objects(
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
):
    """Список всех исторических объектов в БД."""
    rows = await list_historical_objects(limit=limit, offset=offset)
    return JSONResponse({"objects": rows, "total": len(rows)})


@app.get("/api/objects/{object_id}/assets")
async def object_assets(
    object_id: int,
    source: str = Query(default=None),
    year: str = Query(default=None),
):
    """Ассеты объекта. Фильтры: ?source=wikimedia&year=1939."""
    obj = await get_historical_object(object_id)
    if not obj:
        return JSONResponse({"error": "object not found"}, status_code=404)
    rows = await get_assets_by_object(
        object_id, source=source or None, year=year or None
    )
    return JSONResponse({"object": obj, "assets": rows})


@app.get("/api/assets/download/{asset_id}")
async def asset_download(
    asset_id: int,
    version: str = Query(default="optimized", pattern="^(thumbnail|optimized|original)$"),
):
    """Скачать файл ассета. ?version=thumbnail|optimized|original."""
    asset = await get_asset(asset_id)
    if not asset:
        return JSONResponse({"error": "asset not found"}, status_code=404)

    path = _resolve_asset_version(asset, version)
    if not path or not os.path.exists(path):
        return JSONResponse(
            {"error": f"version '{version}' not available for asset {asset_id}"},
            status_code=404,
        )

    media_type = "image/jpeg"
    if version == "original" or not path.lower().endswith(".jpg"):
        media_type = _guess_media_type(path)
    return FileResponse(
        path, media_type=media_type,
        filename=os.path.basename(path),
    )


@app.get("/api/assets/random")
async def assets_random(
    object_id: int = Query(default=None),
    limit: int = Query(default=10, ge=1, le=100),
):
    """Случайные скачанные ассеты (для превью на карте AR-приложения)."""
    rows = await get_random_assets(object_id=object_id, limit=limit)
    return JSONResponse({"assets": rows})


def _resolve_asset_version(asset: dict, version: str) -> str:
    """Путь к нужной версии файла (с фолбэком на старые записи)."""
    mapping = {
        "thumbnail": "thumbnail_path",
        "optimized": "optimized_path",
        "original": "original_path",
    }
    path = asset.get(mapping[version]) or ""
    # Для старых записей (до оптимизатора) оригинал лежит в local_path
    if not path and version == "original":
        path = asset.get("local_path") or ""
    return path


def _guess_media_type(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    return {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".gif": "image/gif",
        ".webp": "image/webp",
        ".pdf": "application/pdf",
        ".usdz": "model/vnd.usdz+zip",
        ".mp4": "video/mp4",
    }.get(ext, "application/octet-stream")


@app.get("/api/settings")
async def settings_get():
    """Получить все настройки (публичная key-value часть)."""
    db_settings = await get_all_settings()
    provider = db_settings.get("llm_provider", os.getenv("LLM_PROVIDER", "ollama"))
    return JSONResponse({
        "provider": provider,
        "available_providers": {k: v for k, v in PROVIDER_NAMES.items()},
        **db_settings,
    })


@app.post("/api/settings")
async def settings_post(data: SettingsUpdate):
    """Обновить настройки (публичная часть — только выбор провайдера)."""
    if data.provider:
        provider = data.provider.lower()
        if provider not in ("ollama", "deepseek", "gemini"):
            return JSONResponse(
                {"status": "error", "message": f"Unknown provider '{provider}'"},
                status_code=400,
            )
        await set_setting("llm_provider", provider)
    return JSONResponse({"status": "ok"})


# ── API routes: Auth ─────────────────────────────────────────────────────────

@app.post("/api/register")
async def register(data: UserRegister):
    """Регистрация нового пользователя."""
    email = data.email.strip().lower()
    password = data.password

    if len(password) < 6:
        return JSONResponse(
            {"status": "error", "message": "Пароль должен быть минимум 6 символов"},
            status_code=400,
        )

    existing = await get_user_by_email(email)
    if existing:
        return JSONResponse(
            {"status": "error", "message": "Email уже зарегистрирован"},
            status_code=409,
        )

    pwd_hash = hash_password(password)
    user_id = await create_user(email, pwd_hash)

    # Сразу выдаём токен
    token = create_access_token({"sub": str(user_id)})
    return JSONResponse({
        "status": "ok",
        "access_token": token,
        "token_type": "bearer",
        "user": {"id": user_id, "email": email},
    })


@app.post("/api/login")
async def login(data: UserLogin):
    """Вход — проверка пароля, выдача JWT."""
    email = data.email.strip().lower()
    user = await get_user_by_email(email)
    if not user:
        return JSONResponse(
            {"status": "error", "message": "Неверный email или пароль"},
            status_code=401,
        )

    if not verify_password(data.password, user["password_hash"]):
        return JSONResponse(
            {"status": "error", "message": "Неверный email или пароль"},
            status_code=401,
        )

    token = create_access_token({"sub": str(user["id"])})
    return JSONResponse({
        "status": "ok",
        "access_token": token,
        "token_type": "bearer",
        "user": {"id": user["id"], "email": user["email"], "is_admin": bool(user["is_admin"])},
    })


@app.get("/api/me")
async def me(current_user: dict = Depends(get_current_user)):
    """Данные текущего пользователя."""
    return JSONResponse({
        "id": current_user["id"],
        "email": current_user["email"],
        "is_admin": bool(current_user["is_admin"]),
    })


@app.post("/api/logout")
async def logout():
    """Выход — на бэкенде ничего не делаем (клиент удаляет токен)."""
    return JSONResponse({"ok": True})


# ── API routes: Protected Settings ──────────────────────────────────────────

def _mask_key(key: str) -> str:
    """Замаскировать API-ключ: показать первые 4 и последние 4 символа."""
    if not key or len(key) < 8:
        return ""
    return key[:4] + "****" + key[-4:]


@app.get("/api/user/settings")
async def user_settings_get(current_user: dict = Depends(get_current_user)):
    """Получить настройки LLM текущего пользователя (с маскировкой ключей)."""
    settings = await get_user_settings(current_user["id"])
    # Маскируем ключи
    masked = dict(settings)
    if masked.get("deepseek_api_key"):
        masked["deepseek_api_key"] = _mask_key(masked["deepseek_api_key"])
    if masked.get("gemini_api_key"):
        masked["gemini_api_key"] = _mask_key(masked["gemini_api_key"])
    return JSONResponse(masked)


@app.put("/api/user/settings")
async def user_settings_update(
    data: SettingsUpdateFull,
    current_user: dict = Depends(get_current_user),
):
    """Обновить настройки LLM текущего пользователя."""
    update_data = {}
    for key in ("deepseek_api_key", "deepseek_model", "gemini_api_key",
                 "gemini_model", "ollama_model", "ollama_host"):
        value = getattr(data, key, None)
        if value is not None:
            update_data[key] = value

    await update_user_settings(current_user["id"], update_data)
    return JSONResponse({"status": "ok"})


@app.post("/api/test-connection")
async def test_connection(
    data: TestConnectionRequest,
    current_user: dict = Depends(get_current_user),
):
    """Проверить подключение к провайдеру."""
    provider = data.provider.lower()
    if provider not in ("ollama", "deepseek", "gemini"):
        return JSONResponse(
            {"success": False, "message": f"Неизвестный провайдер: {provider}"},
        )

    # Загружаем настройки, если каких-то полей не хватает
    settings = await get_user_settings(current_user["id"])

    if provider == "ollama":
        host = data.host or data.api_key or settings.get("ollama_host", "http://localhost:11434")
        model = data.model or settings.get("ollama_model", "qwen2.5:14b")
        ok, msg = await check_ollama_available(model=model, host=host)
        return JSONResponse({"success": ok, "message": msg})

    elif provider == "deepseek":
        key = data.api_key or settings.get("deepseek_api_key", "")
        model = data.model or settings.get("deepseek_model", "deepseek-chat")
        if not key:
            return JSONResponse({"success": False, "message": "API key не указан"})
        try:
            analyzer = DeepSeekAnalyzer(api_key=key, model=model)
            result = await analyzer.analyze("Test", "Web App", "100", "Hello, this is a test.")
            success = result["verdict"] != "UNKNOWN" or "error" not in result.get("reason", "").lower()
            return JSONResponse({
                "success": success,
                "message": "DeepSeek API OK" if success else f"Ошибка: {result.get('reason', 'Unknown')}",
            })
        except Exception as e:
            return JSONResponse({"success": False, "message": f"DeepSeek error: {e}"})

    elif provider == "gemini":
        key = data.api_key or settings.get("gemini_api_key", "")
        model = data.model or settings.get("gemini_model", "gemini-1.5-flash")
        if not key:
            return JSONResponse({"success": False, "message": "API key не указан"})
        try:
            analyzer = GeminiAnalyzer(api_key=key, model=model)
            result = await analyzer.analyze("Test", "Web App", "100", "Hello, this is a test.")
            success = result["verdict"] != "UNKNOWN" or "error" not in result.get("reason", "").lower()
            return JSONResponse({
                "success": success,
                "message": "Gemini API OK" if success else f"Ошибка: {result.get('reason', 'Unknown')}",
            })
        except Exception as e:
            return JSONResponse({"success": False, "message": f"Gemini error: {e}"})
