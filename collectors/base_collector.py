"""Базовый класс коллекторов исторических медиа.

Наследует :class:`scrapers.base.BaseScraper`, переиспользуя его `_get`
(таймауты, заголовки, вежливые паузы) и добавляя:

- `load_dotenv()` при инициализации — коллекторы читают API-ключи из `.env`;
- проверку `robots.txt` (Disallow + Crawl-delay) с кэшированием на источник;
- ретраи с экспоненциальным backoff для HTTP-запросов (`_get` переопределён);
- обёртки `_fetch_soup` / `_fetch_json`.

Конкретные коллекторы реализуют `scrape()`, который возвращает список словарей
с полями: title, file_url, thumbnail_url, description, year, source,
source_url, file_type (и опционально width/height/tags).
"""

import asyncio
import logging
import random
import time
from abc import abstractmethod
from typing import Optional
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import httpx
from bs4 import BeautifulSoup
from dotenv import load_dotenv

from collectors.utils import coerce_year
from scrapers.base import BaseScraper, BASE_HEADERS, USER_AGENTS

logger = logging.getLogger("freelance-radar.collector")

# Ретраи HTTP-запросов коллекторов: статусы, на которые ретраим, и backoff-паузы
RETRY_STATUSES = {429, 500, 502, 503, 504}
RETRY_ATTEMPTS = 4
RETRY_BACKOFF = (2, 4, 8, 16)  # секунды между попытками

# Кэш robots.txt: netloc -> (timestamp, RobotFileParser)
_ROBOTS_CACHE: dict[str, tuple[float, RobotFileParser]] = {}
_ROBOTS_TTL = 3600  # 1 час


class BaseCollector(BaseScraper):
    """Абстрактный коллектор исторических визуальных материалов.

    Конструктор принимает `query` (название объекта), `limit` (максимум
    файлов) и опциональный фильтр по периоду `year_from`/`year_to` (годы
    1000–2099). Коллекторы, чьи API поддерживают серверную фильтрацию по
    дате, используют её напрямую; остальные отфильтровывают результаты
    по извлечённому из метаданных году через `_filter_by_period`.
    Конкретные коллекторы реализуют `scrape()`, который возвращает
    список словарей с полями:

    - title, file_url, thumbnail_url, description, year, source
    - source_url (страница источника), file_type (jpg/png/pdf/...)
    - width / height (разрешение оригинала, если известно)
    - tags (теги/ракурсы для группировки в режиме photogrammetry)
    """

    source_name: str = ""
    base_url: str = ""

    def __init__(self, query: str, limit: int = 20, language: str = "pl",
                 timeout: int = 30, delay: tuple = (1, 3),
                 year_from: int | None = None, year_to: int | None = None,
                 fallback_query: str = ""):
        # Ключи коллекторов лежат в .env; load_dotenv безопасен повторно.
        load_dotenv()
        super().__init__(timeout=timeout, delay=delay)
        self.query = query.strip()
        self.limit = max(1, int(limit))
        self.language = language or ""
        self.year_from = coerce_year(year_from)
        self.year_to = coerce_year(year_to)
        # Запасной запрос (например, по городу) для источников, которые ищут на
        # своём языке: используется, когда основной запрос не дал результатов.
        self.fallback_query = (fallback_query or "").strip()
        self._robots_loaded_at: dict[str, float] = {}
        self._robots_delay: dict[str, float] = {}

    # ── Фильтрация по историческому периоду ─────────────────────────────────

    @property
    def _period_active(self) -> bool:
        """Задан ли фильтр по году/веку."""
        return self.year_from is not None or self.year_to is not None

    def _year_in_period(self, year) -> bool:
        """Попадает ли извлечённый год ассета в заданный период.

        Если фильтр задан, а год определить не удалось — ассет пропускается
        (проходит фильтр): при широком периоде (например, 1000–2024) не
        хочется терять материалы без читаемой даты.
        """
        if not self._period_active:
            return True
        value = coerce_year(year)
        if value is None:
            return True
        if self.year_from is not None and value < self.year_from:
            return False
        if self.year_to is not None and value > self.year_to:
            return False
        return True

    def _accepts(self, asset: dict) -> bool:
        """Прошёл ли ассет фильтр по периоду (для использования в циклах)."""
        if not self._period_active:
            return True
        return self._year_in_period(asset.get("year"))

    def _filter_by_period(self, assets: list[dict]) -> list[dict]:
        """Постфильтрация списка ассетов по году (для источников без
        серверной фильтрации). Ассеты с неопределённым годом при активном
        фильтре пропускаются (не отбрасываются)."""
        if not self._period_active:
            return assets
        kept = [a for a in assets if self._year_in_period(a.get("year"))]
        dropped = len(assets) - len(kept)
        if dropped:
            logger.info(
                "[%s] отфильтровано по периоду %s–%s: %d из %d",
                self.source_name, self.year_from or "…", self.year_to or "…",
                dropped, len(assets),
            )
        return kept

    def _search_window(self, total: int) -> int:
        """Сколько кандидатов перебирать при постфильтрации по периоду.

        Без фильтра — ровно `limit`; с фильтром — с запасом, чтобы после
        отсева по году всё равно набрать нужное количество ассетов.
        """
        if not self._period_active:
            return min(total, self.limit)
        return min(total, self.limit * 4)

    # ── robots.txt ───────────────────────────────────────────────────────────

    async def _load_robots(self, netloc: str) -> RobotFileParser | None:
        """Загрузить и закэшировать robots.txt для хоста (1 час)."""
        now = time.time()
        cached = _ROBOTS_CACHE.get(netloc)
        if cached and now - cached[0] < _ROBOTS_TTL:
            return cached[1]

        robots_url = f"https://{netloc}/robots.txt"
        parser = RobotFileParser()
        try:
            resp = await super()._get(robots_url, params={})
            if resp is None:
                parser.allow_all = True
            else:
                lines = resp.text.splitlines()
                # Crawl-delay: берём минимальное значение из всех записей
                for line in lines:
                    low = line.lower().strip()
                    if low.startswith("crawl-delay"):
                        try:
                            secs = float(low.split(":", 1)[1].strip())
                            self._robots_delay[netloc] = min(
                                secs, self._robots_delay.get(netloc, secs)
                            )
                        except (ValueError, IndexError):
                            pass
                parser.parse(lines)
        except Exception as exc:  # robots недоступен — не блокируем сбор
            logger.debug("[%s] robots.txt недоступен для %s: %s",
                         self.source_name, netloc, exc)
            parser.allow_all = True

        _ROBOTS_CACHE[netloc] = (now, parser)
        return parser

    async def _can_fetch(self, url: str) -> bool:
        """Разрешён ли запрос по правилам robots.txt хоста."""
        netloc = urlparse(url).netloc
        path = urlparse(url).path
        if not netloc or not self.base_url:
            return True
        # robots проверяем только для страниц/API самого источника
        if netloc not in self.base_url and self.base_url not in url:
            return True
        # API-эндпоинты не проверяем по robots.txt — они предназначены для
        # программного доступа (MediaWiki /w/api.php, polona2.pl/api, WP-json).
        if "/api/" in path or "/wp-json/" in path or path.rstrip("/").endswith(
            (".json", ".api", "api.php")
        ):
            return True
        parser = await self._load_robots(netloc)
        if parser is None or getattr(parser, "allow_all", False):
            return True
        return parser.can_fetch("freelance-radar-collector", url)

    async def _get(self, url: str, cookies: dict = None,
                   headers: dict = None, **kwargs) -> Optional[httpx.Response]:
        """GET с проверкой robots.txt и ретраями на 429/5xx/сеть.

        Собственная реализация поверх httpx: `BaseScraper._get` глотает все
        ошибки HTTP, поэтому ретраи на 429/5xx в нём невозможны. `headers`
        сливаются с базовыми (для API-запросов передавайте
        `headers={"Accept": "application/json"}` — Polona отдаёт HTML, если
        Accept не отдаёт приоритет JSON).
        """
        if not await self._can_fetch(url):
            logger.warning("[%s] robots.txt запрещает %s — пропуск", self.source_name, url)
            return None

        hdrs = dict(BASE_HEADERS)
        hdrs["User-Agent"] = random.choice(USER_AGENTS)
        hdrs["Accept"] = (
            "text/html,application/xhtml+xml,application/xml;q=0.9,"
            "image/webp,*/*;q=0.8"
        )
        if headers:
            hdrs.update(headers)
        elif "/api/" in urlparse(url).path or urlparse(url).path.rstrip("/").endswith(
            (".json", ".api", "api.php")
        ):
            hdrs["Accept"] = "application/json,text/html;q=0.8,*/*;q=0.6"

        last_wait = RETRY_BACKOFF[0]
        for attempt in range(RETRY_ATTEMPTS):
            await asyncio.sleep(random.uniform(*self.delay))
            try:
                async with httpx.AsyncClient(
                    timeout=self.timeout,
                    follow_redirects=True,
                    cookies=cookies or {},
                    headers=hdrs,
                ) as client:
                    resp = await client.get(url, **kwargs)
                if resp.status_code in RETRY_STATUSES and attempt < RETRY_ATTEMPTS - 1:
                    logger.warning(
                        "[%s] %s — HTTP %d, попытка %d/%d, жду %ds",
                        self.source_name, url, resp.status_code,
                        attempt + 1, RETRY_ATTEMPTS, last_wait,
                    )
                    await asyncio.sleep(last_wait)
                    last_wait = RETRY_BACKOFF[
                        min(attempt + 1, len(RETRY_BACKOFF) - 1)
                    ]
                    continue
                resp.raise_for_status()
                return resp
            except (httpx.TransportError, httpx.TimeoutException) as exc:
                if attempt >= RETRY_ATTEMPTS - 1:
                    logger.warning("[%s] fetch error %s: %s", self.source_name, url, exc)
                    return None
                logger.warning(
                    "[%s] %s — сеть: %s, попытка %d/%d, жду %ds",
                    self.source_name, url, exc, attempt + 1, RETRY_ATTEMPTS, last_wait,
                )
                await asyncio.sleep(last_wait)
                last_wait = RETRY_BACKOFF[
                    min(attempt + 1, len(RETRY_BACKOFF) - 1)
                ]
            except httpx.HTTPStatusError as exc:
                logger.warning("[%s] fetch error %s: %s", self.source_name, url, exc)
                return None
        return None

    # ── Обёртки разбора ответов ─────────────────────────────────────────────

    async def _fetch_soup(self, url: str, **kwargs) -> Optional[BeautifulSoup]:
        """GET-запрос и разбор ответа как HTML."""
        resp = await self._get(url, **kwargs)
        if resp is None:
            return None
        try:
            return BeautifulSoup(resp.text, "lxml")
        except Exception:
            logger.warning("[%s] не удалось разобрать HTML: %s", self.source_name, url)
            return None

    async def _fetch_xml(self, url: str, **kwargs) -> Optional[BeautifulSoup]:
        """GET-запрос и разбор ответа как XML (для SRU/SPARQL и пр.)."""
        resp = await self._get(url, **kwargs)
        if resp is None:
            return None
        try:
            return BeautifulSoup(resp.text, "xml")
        except Exception:
            logger.warning("[%s] не удалось разобрать XML: %s", self.source_name, url)
            return None

    async def _fetch_json(self, url: str, **kwargs) -> Optional[dict]:
        """GET-запрос и разбор ответа как JSON-объекта (dict).

        `headers` из kwargs сливаются с базовым Accept: application/json
        (передаваемый коллектором Accept имеет приоритет).
        """
        headers = dict(kwargs.pop("headers", None) or {})
        headers.setdefault("Accept", "application/json")
        resp = await self._get(url, headers=headers, **kwargs)
        if resp is None:
            return None
        try:
            data = resp.json()
        except Exception:
            logger.warning("[%s] не-JSON ответ от %s", self.source_name, url)
            return None
        return data if isinstance(data, dict) else None

    async def _fetch_json_list(self, url: str, **kwargs) -> Optional[list]:
        """GET-запрос и разбор ответа как JSON-списка (для API, отдающих [..])."""
        headers = dict(kwargs.pop("headers", None) or {})
        headers.setdefault("Accept", "application/json")
        resp = await self._get(url, headers=headers, **kwargs)
        if resp is None:
            return None
        try:
            data = resp.json()
        except Exception:
            logger.warning("[%s] не-JSON ответ от %s", self.source_name, url)
            return None
        return data if isinstance(data, list) else None

    def _abs_url(self, url: str) -> str:
        """Преобразовать относительную ссылку в абсолютную."""
        if not url:
            return ""
        if url.startswith("//"):
            url = "https:" + url
        return urljoin(self.base_url or "", url)

    @abstractmethod
    async def scrape(self) -> list[dict]:
        """Собрать исторические материалы и вернуть список словарей."""
        ...
