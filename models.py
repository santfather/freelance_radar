from dataclasses import dataclass, field
from typing import Optional
from enum import Enum
from pydantic import BaseModel


MAX_DESC_LENGTH = 600  # макс. длина описания при извлечении из HTML / передаче в LLM


class Category(str, Enum):
    WEB_APP = "Web App"
    MOBILE_APP = "Mobile App"
    CMS = "CMS"
    OTHER_IT = "Other IT"


class Verdict(str, Enum):
    TAKE = "TAKE"
    SKIP = "SKIP"
    UNKNOWN = "UNKNOWN"


@dataclass
class Job:
    id: str                          # hash of title+source
    title: str
    description: str
    url: str
    source: str                      # useme / oferia / zleca / workconnect
    category: Category
    budget_raw: str = ""             # original text e.g. "500-1000 PLN"
    budget_min: Optional[int] = None
    budget_max: Optional[int] = None
    posted_at: str = ""              # raw date string from site
    # LLM analysis fields (filled after Ollama pass)
    verdict: Verdict = Verdict.UNKNOWN
    verdict_reason: str = ""
    complexity: int = 0              # 1-5
    estimated_hours: int = 0
    analyzed: bool = False

    @classmethod
    def from_db_row(cls, row: dict) -> "Job":
        """Создать Job из строки БД (словаря). Устраняет дублирование маппинга."""
        return cls(
            id=row["id"], title=row["title"], description=row["description"],
            url=row["url"], source=row["source"],
            category=Category(row["category"]) if row.get("category") in (c.value for c in Category) else Category.OTHER_IT,
            budget_raw=row.get("budget_raw") or "",
            budget_min=row.get("budget_min"), budget_max=row.get("budget_max"),
            posted_at=row.get("posted_at") or "",
            verdict=Verdict(row["verdict"]) if row.get("verdict") in (v.value for v in Verdict) else Verdict.UNKNOWN,
            verdict_reason=row.get("verdict_reason") or "",
            complexity=row.get("complexity") or 0,
            estimated_hours=row.get("estimated_hours") or 0,
            analyzed=bool(row.get("analyzed", 0)),
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "url": self.url,
            "source": self.source,
            "category": self.category.value,
            "budget_raw": self.budget_raw,
            "budget_min": self.budget_min,
            "budget_max": self.budget_max,
            "posted_at": self.posted_at,
            "verdict": self.verdict.value,
            "verdict_reason": self.verdict_reason,
            "complexity": self.complexity,
            "estimated_hours": self.estimated_hours,
            "analyzed": self.analyzed,
        }


# ── Pydantic models for API ─────────────────────────────────────────────────

class SettingsUpdate(BaseModel):
    provider: str | None = None


class UserRegister(BaseModel):
    email: str
    password: str


class UserLogin(BaseModel):
    email: str
    password: str


class SettingsUpdateFull(BaseModel):
    deepseek_api_key: str | None = None
    deepseek_model: str | None = None
    gemini_api_key: str | None = None
    gemini_model: str | None = None
    ollama_model: str | None = None
    ollama_host: str | None = None


class TestConnectionRequest(BaseModel):
    provider: str
    api_key: str | None = None
    model: str | None = None
    host: str | None = None  # для Ollama — отдельный хост вместо api_key


class CollectRequest(BaseModel):
    """Запрос на сбор исторических материалов для объекта."""
    object_name: str
    sources: list[str] | str = "all"  # список ключей источников или "all"
    limit: int = 20
    era: str = ""
    city: str = ""
    latitude: float | None = None
    longitude: float | None = None
    description: str = ""
    mode: str = "general"  # "general" | "photogrammetry"
    year_from: int | None = None  # нижняя граница периода (например, 1500)
    year_to: int | None = None    # верхняя граница периода (например, 1800)
    century: int | None = None    # век: 18 → год_from=1701, year_to=1800
