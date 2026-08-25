from dataclasses import dataclass, field


@dataclass
class CollectTaskState:
    """Состояние фоновой задачи сбора исторических материалов."""
    id: str
    object_name: str
    sources: list[str]
    limit: int
    mode: str = "general"  # general / photogrammetry
    status: str = "pending"  # pending / running / done / error
    object_id: int | None = None
    collected: int = 0
    downloaded: int = 0
    errors: list[str] = field(default_factory=list)
    log: list[str] = field(default_factory=list)
    created_at: float = 0


@dataclass
class AppState:
    scraping: bool = False
    analyzing: bool = False
    scrape_log: list[str] = field(default_factory=list)
    analyze_log: list[str] = field(default_factory=list)
    analyze_progress: int = 0
    analyze_total: int = 0
    analyze_provider: str = ""
    stats_cache: dict | None = None
    stats_cache_time: float = 0
    STATS_CACHE_TTL: float = 5.0  # секунд
    collect_tasks: dict[str, CollectTaskState] = field(default_factory=dict)
