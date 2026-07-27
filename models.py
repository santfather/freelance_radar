from dataclasses import dataclass, field
from typing import Optional
from enum import Enum
from pydantic import BaseModel


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
