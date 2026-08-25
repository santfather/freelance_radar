"""MediaOptimizer — скачивание и подготовка медиафайлов для мобильного AR.

Для каждого файла создаются три версии (относительно `output_dir`, который
обычно равен `assets/`). Файлы группируются по типу материала (из `asset_data`),
что упрощает ручную проверку и фильтрацию:

- `archive/<city>/<slug>/<тип>/<year>_<id>_original.<ext>`    — оригинал
- `production/<city>/<slug>/<тип>/<year>_<id>_optimized.jpg`  — JPEG q85, 2048 px
- `thumbnails/<city>/<slug>/<тип>/<year>_<id>_thumb.jpg`      — JPEG q75, 512 px

Подпапки типов: photos/paintings/prints/maps/drawings/unknown (см.
`material_type_dir` в collectors.utils).

Для не-изображений (PDF, USDZ, MP4 и пр.) оптимизация пропускается —
сохраняется только оригинал. CPU-интенсивные операции Pillow выполняются
через `asyncio.to_thread`, чтобы не блокировать событийный цикл.
"""

import asyncio
import logging
import os
import random
import re

import aiofiles
import httpx
from PIL import Image, ImageOps

from collectors.utils import material_type_dir

# Исторические сканы бывают огромными (например, панорамы 15000×15000 px).
# Отключаем защиту Pillow от decompression bomb, чтобы такие файлы можно было
# открыть и ужать до целевого размера.
Image.MAX_IMAGE_PIXELS = None

logger = logging.getLogger("freelance-radar.collector.optimizer")

# Расширения, которые Pillow умеет открывать и перекодировать.
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tif", ".tiff", ".webp"}

OPTIMIZED_MAX_SIDE = 2048
THUMBNAIL_MAX_SIDE = 512
OPTIMIZED_QUALITY = 85
THUMBNAIL_QUALITY = 75

# Wikimedia перекодирует миниатюры только по стандартным размерам
# ($wgThumbnailSteps: 20, 40, 60, 120, 250, 330, 500, 960, 1280, 1920, 3840);
# 2000/2048px возвращают HTTP 400 «Use thumbnail sizes listed on w.wiki/GHai».
# Берём 1920px — стандартный размер, ближайший к оптимизированному 2048px.
DOWNLOAD_TIMEOUT = 60  # секунд, большой таймаут на скачивание оригиналов
DOWNLOAD_WIKIMEDIA_THUMB_PX = 1920

# Вежливая пауза перед каждым скачиванием файла: без неё Wikimedia отвечает
# 429 (слишком частые запросы), и суммарно теряем больше времени на ретраи
# (5+10+20+40с), чем на паузу.
DOWNLOAD_POLITE_DELAY = (1.5, 3.0)

# Ретраи при 429/5xx от Wikimedia: 429 означает "слишком много запросов",
# после короткой паузы тот же файл обычно скачивается успешно.
DOWNLOAD_RETRIES = 4
DOWNLOAD_RETRY_BACKOFF = (5, 10, 20, 40)  # паузы между попытками, секунды

_RETRY_STATUSES = {429, 500, 502, 503, 504}

_THUMB_PX_RE = re.compile(r"^(\d+)px-(.+)$")


def upscale_thumb_url(url: str, px: int = DOWNLOAD_WIKIMEDIA_THUMB_PX) -> str:
    """Переписать URL миниатюры Wikimedia на больший размер.

    '.../thumb/a/ae/File.jpg/960px-File.jpg?_=...' → '.../1920px-File.jpg?_=...'

    Размер должен быть из стандартного списка Wikimedia ($wgThumbnailSteps);
    2000/2048 в него не входят и возвращают HTTP 400. Если паттерн не
    распознан — вернуть URL как есть (не трогаем).
    """
    if not url or "/thumb/" not in url:
        return url
    head, _, tail = url.partition("?")
    segments = head.split("/")
    base = segments[-1] if segments else ""
    match = _THUMB_PX_RE.match(base)
    if not match:
        return url
    segments[-1] = f"{px}px-{match.group(2)}"
    result = "/".join(segments)
    return f"{result}?{tail}" if tail else result

DOWNLOAD_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "image/*,*/*;q=0.8",
}


def ext_from_url(url: str) -> str:
    """Расширение файла из URL (без query-строки и якоря)."""
    path = url.split("?")[0].split("#")[0]
    ext = os.path.splitext(path)[1].lower().lstrip(".")
    return ext if ext else ""


def is_image_file_type(file_type: str) -> bool:
    """Является ли расширение/тип файла изображением для Pillow."""
    ft = (file_type or "").lower().lstrip(".")
    return f".{ft}" in IMAGE_EXTS


_TRANSLIT = str.maketrans({
    "ą": "a", "ć": "c", "ę": "e", "ł": "l", "ń": "n",
    "ó": "o", "ś": "s", "ź": "z", "ż": "z",
    "ü": "u", "ö": "o", "ä": "a", "ß": "ss", "é": "e",
})


def slugify(text: str) -> str:
    """Транслитерация и нормализация строки до безопасного слага."""
    text = text.lower().translate(_TRANSLIT)
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return text.strip("_") or "unknown"


def _resize_save(src_path: str, dst_path: str, max_side: int, quality: int) -> tuple[int, int, int]:
    """Открыть изображение, ужать по большей стороне и сохранить как JPEG.

    Возвращает (width, height, file_size). Синхронная функция — вызывается
    через `asyncio.to_thread`, чтобы не блокировать событийный цикл.
    """
    with Image.open(src_path) as im:
        im = ImageOps.exif_transpose(im)
        im = im.convert("RGB")
        if max(im.size) > max_side:
            scale = max_side / max(im.size)
            new_size = (
                max(1, round(im.width * scale)),
                max(1, round(im.height * scale)),
            )
            im = im.resize(new_size, Image.Resampling.LANCZOS)
        im.save(dst_path, "JPEG", quality=quality, optimize=True, progressive=True)
        return im.width, im.height, os.path.getsize(dst_path)


class MediaOptimizer:
    """Скачивает оригинал и готовит thumbnail/optimized версии."""

    @staticmethod
    async def process(
        file_url: str,
        asset_data: dict,
        output_dir: str,
        asset_id: int,
        skip_optimization: bool = False,
        prefer_original: bool = False,
    ) -> dict:
        """Скачать файл и создать версии.

        Параметры:
            file_url — прямая ссылка на файл;
            asset_data — метаданные ассета (`source`, `year`, `file_type`,
                `city`, `slug`);
            output_dir — корень хранения (например, `assets/`);
            asset_id — id ассета в БД (используется в имени файла);
            skip_optimization — режим photogrammetry: сохранить только оригинал
                и миниатюру, без оптимизированной 2048px-версии;
            prefer_original — фотограмметрия: качать исходный файл, а не
                миниатюру-заменитель (для Wikimedia всё равно fallback на
                увеличенную миниатюру при лимитах).

        Возвращает словарь с относительными путями к версиям и метаданными
        оптимизации; при неудаче — словарь с ключом `error`.
        """
        year = (asset_data.get("year") or "unknown").replace("/", "-")
        city = slugify(asset_data.get("city") or "unknown")
        slug = slugify(asset_data.get("slug") or "unknown")
        material_type = material_type_dir(asset_data.get("material_type"))
        file_type = asset_data.get("file_type") or ext_from_url(file_url)
        if not file_type:
            file_type = "jpg"

        result: dict = {
            "original_path": "",
            "optimized_path": "",
            "thumbnail_path": "",
            "width_optimized": None,
            "height_optimized": None,
            "file_size_optimized": None,
            "original_width": None,
            "original_height": None,
            "photogrammetry_ready": 0,
            "downloaded": 0,
            "error": "",
        }

        # Wikimedia при массовом скачивании оригиналов отвечает 429 и просит
        # использовать thumbnail-версии. В режиме photogrammetry (`prefer_original`)
        # пробуем исходный файл, при сбое — увеличенную до 2000 px миниатюру.
        thumb_url = (asset_data.get("thumbnail_url") or "").strip()
        if "wikimedia.org" in thumb_url:
            if prefer_original:
                primary_url = file_url
                fallback_url = upscale_thumb_url(thumb_url) or thumb_url
                file_type = "jpg"  # фолбэк-миниатюра Wikimedia — JPEG
            else:
                primary_url = upscale_thumb_url(thumb_url)
                fallback_url = thumb_url
                file_type = "jpg"  # миниатюры Wikimedia — JPEG
        else:
            primary_url = file_url
            fallback_url = ""

        try:
            content, content_type = await MediaOptimizer._download(
                primary_url, fallback_url
            )
        except Exception as e:
            logger.warning("Download failed %s: %s", file_url, e)
            result["error"] = f"download: {e}"
            return result

        is_image = is_image_file_type(file_type) or (
            (content_type or "").startswith("image/")
        )
        if not is_image:
            logger.info(
                "[optimizer] %s — не изображение (%s), сохраняю только оригинал",
                file_url, content_type or file_type,
            )

        try:
            result = await MediaOptimizer._store(
                content, file_type, is_image, output_dir, city, slug, year,
                asset_id, result, skip_optimization=skip_optimization,
                material_type=material_type,
            )
        except Exception as e:
            logger.exception("[optimizer] обработка %s завершилась с ошибкой", file_url)
            result["error"] = f"process: {e}"

        return result

    # ── Шаги пайплайна ──────────────────────────────────────────────────────

    @staticmethod
    async def _download(file_url: str, fallback_url: str = "") -> tuple[bytes, str]:
        """Скачать файл с ретраями на 429/5xx.

        Перед запросом выдерживается короткая пауза, чтобы не упереться
        в лимиты Wikimedia (иначе 429 и ретраи с backoff съедают время).

        Если оригинал после всех попыток не скачан и задан fallback_url
        (миниатюра) — попробовать его: Wikimedia при лимитах просит
        использовать thumbnail-версии.
        """
        timeout = httpx.Timeout(DOWNLOAD_TIMEOUT, connect=15.0)
        await asyncio.sleep(random.uniform(*DOWNLOAD_POLITE_DELAY))
        try:
            async with httpx.AsyncClient(
                timeout=timeout, follow_redirects=True, headers=DOWNLOAD_HEADERS
            ) as client:
                return await MediaOptimizer._download_retrying(client, file_url)
        except Exception as exc:
            if fallback_url and fallback_url.startswith("http") and fallback_url != file_url:
                logger.warning(
                    "[optimizer] %s не скачан (%s) — fallback на миниатюру %s",
                    file_url, exc, fallback_url,
                )
                async with httpx.AsyncClient(
                    timeout=timeout, follow_redirects=True, headers=DOWNLOAD_HEADERS
                ) as client:
                    content, _ = await MediaOptimizer._download_retrying(client, fallback_url)
                return content, "image/jpeg"
            raise

    @staticmethod
    async def _download_retrying(client, url: str) -> tuple[bytes, str]:
        """GET url с ретраями. Возвращает (content, content_type) или исключение."""
        last_wait = DOWNLOAD_RETRY_BACKOFF[0]
        for attempt in range(DOWNLOAD_RETRIES):
            try:
                resp = await client.get(url)
                if resp.status_code in _RETRY_STATUSES:
                    if attempt == DOWNLOAD_RETRIES - 1:
                        resp.raise_for_status()
                    logger.warning(
                        "[optimizer] %s — HTTP %d, попытка %d/%d, жду %ds",
                        url, resp.status_code, attempt + 1,
                        DOWNLOAD_RETRIES, last_wait,
                    )
                    await asyncio.sleep(last_wait)
                    last_wait = DOWNLOAD_RETRY_BACKOFF[
                        min(attempt + 1, len(DOWNLOAD_RETRY_BACKOFF) - 1)
                    ]
                    continue
                resp.raise_for_status()  # остальные 4xx/5xx — не ретраим
                return resp.content, resp.headers.get("content-type", "")
            except (httpx.TransportError, httpx.TimeoutException) as exc:
                if attempt == DOWNLOAD_RETRIES - 1:
                    raise
                logger.warning(
                    "[optimizer] %s — сеть: %s, попытка %d/%d, жду %ds",
                    url, exc, attempt + 1, DOWNLOAD_RETRIES, last_wait,
                )
                await asyncio.sleep(last_wait)
                last_wait = DOWNLOAD_RETRY_BACKOFF[
                    min(attempt + 1, len(DOWNLOAD_RETRY_BACKOFF) - 1)
                ]
        raise httpx.TransportError(f"не удалось скачать {url}")

    @staticmethod
    async def _store(
        content: bytes,
        file_type: str,
        is_image: bool,
        output_dir: str,
        city: str,
        slug: str,
        year: str,
        asset_id: int,
        result: dict,
        skip_optimization: bool = False,
        material_type: str = "unknown",
    ) -> dict:
        # 1. Оригинал — пишем в archive/<city>/<slug>/<тип материала>/
        original_rel = os.path.join(
            output_dir, "archive", city, slug, material_type,
            f"{year}_{asset_id}_original.{file_type}",
        )
        await MediaOptimizer._write(content, original_rel)
        result["original_path"] = original_rel

        if not is_image:
            result["downloaded"] = 1
            return result

        # 2. Размеры оригинала — нужны для фотограмметрии (фильтр ≥ 2000 px)
        ow, oh = await asyncio.to_thread(MediaOptimizer._original_size, original_rel)
        result["original_width"] = ow
        result["original_height"] = oh
        result["photogrammetry_ready"] = 1 if max(ow, oh) >= 2000 else 0

        thumb_rel = os.path.join(
            output_dir, "thumbnails", city, slug, material_type,
            f"{year}_{asset_id}_thumb.jpg",
        )
        os.makedirs(os.path.dirname(thumb_rel), exist_ok=True)
        await asyncio.to_thread(
            _resize_save, original_rel, thumb_rel, THUMBNAIL_MAX_SIDE, THUMBNAIL_QUALITY
        )
        result["thumbnail_path"] = thumb_rel

        if skip_optimization:
            # photogrammetry: оригинал + миниатюра, без 2048px-версии
            result["downloaded"] = 1
            return result

        # 3. Оптимизированная версия (2048 px) — Pillow в отдельном потоке
        optimized_rel = os.path.join(
            output_dir, "production", city, slug, material_type,
            f"{year}_{asset_id}_optimized.jpg",
        )
        os.makedirs(os.path.dirname(optimized_rel), exist_ok=True)
        w, h, size = await asyncio.to_thread(
            _resize_save, original_rel, optimized_rel, OPTIMIZED_MAX_SIDE, OPTIMIZED_QUALITY
        )
        result.update({
            "optimized_path": optimized_rel,
            "width_optimized": w,
            "height_optimized": h,
            "file_size_optimized": size,
            "downloaded": 1,
        })
        return result

    @staticmethod
    def _original_size(path: str) -> tuple[int, int]:
        """Размеры оригинала в пикселях. Синхронная — вызывается в потоке."""
        with Image.open(path) as im:
            return im.width, im.height

    @staticmethod
    async def create_thumbnail(src_path: str, dst_path: str) -> tuple[int, int, int]:
        """Создать миниатюру (JPEG, макс. 512 px, качество 75) из исходного файла.

        Используется для догенерации миниатюр у ассетов, обработанных до
        появления thumbnails, либо у legacy-загрузок. Создаёт недостающие
        папки. Возвращает (width, height, file_size) или поднимает исключение.
        """
        os.makedirs(os.path.dirname(dst_path), exist_ok=True)
        return await asyncio.to_thread(
            _resize_save, src_path, dst_path, THUMBNAIL_MAX_SIDE, THUMBNAIL_QUALITY
        )

    @staticmethod
    async def _write(content: bytes, rel_path: str):
        os.makedirs(os.path.dirname(rel_path), exist_ok=True)
        async with aiofiles.open(rel_path, "wb") as f:
            await f.write(content)
