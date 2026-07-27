from dataclasses import dataclass, field


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
