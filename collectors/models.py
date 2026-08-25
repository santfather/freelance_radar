"""Pydantic-модели для API коллектора исторических материалов.

Используются в новых эндпоинтах `main.py` для типизации ответов
(`/api/objects`, `/api/objects/{id}/assets`). Поле `version` определяет,
какую версию файла отдаёт `/api/assets/download/{asset_id}`.
"""

from enum import Enum
from typing import Optional

from pydantic import BaseModel


class HistoricalObjectOut(BaseModel):
    id: int
    name: str
    slug: str = ""
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    description: str = ""
    city: str = ""
    era: str = ""
    created_at: str = ""


class HistoricalAssetOut(BaseModel):
    id: int
    object_id: int
    title: str = ""
    source_url: str = ""
    source: str = ""
    year: str = ""
    description: str = ""
    file_type: str = ""
    original_path: str = ""
    optimized_path: str = ""
    thumbnail_path: str = ""
    material_type: str = "unknown"
    width_optimized: Optional[int] = None
    height_optimized: Optional[int] = None
    file_size_optimized: Optional[int] = None
    downloaded: int = 0
    error: str = ""
    created_at: str = ""


class AssetVersion(str, Enum):
    """Версии файла, доступные для скачивания."""

    THUMBNAIL = "thumbnail"
    OPTIMIZED = "optimized"
    ORIGINAL = "original"
