"""Коллектор NAC — Narodowe Archiwum Cyfrowe (WordPress REST API).

Эндпоинты:
- `/wp-json/wp/v2/media` — поиск медиафайлов (`search`, `per_page`, `page`);
- `/wp-json/wp/v2/posts` — поиск постов с изображениями.

Извлечение: `title.rendered` → название, `guid.rendered` /
`media_details.sizes.full.source_url` → файл, `description.rendered` → описание.
Пагинация — заголовок `X-WP-TotalPages`.

⚠️ Статус источника (проверено 2026-08-04): сайт `nac.gov.pl` закрыт
антибот-защитой Incapsula — прямые запросы к `/wp-json/` возвращают HTTP 403
с HTML-заглушкой Incapsula даже с браузерным User-Agent. Поэтому коллектор
всегда запускается, но при детекте антибота корректно завершается с пустым
результатом и пояснением в `errors`. Как только NAC откроет API (или появится
доступ через доверенный прокси/сессию) — коллектор заработает без изменений.

Метаданные NAC (уникальные снимки разрушений и восстановления Варшавы)
частично продублированы в Wikimedia Commons, откуда их уже собирает
`wikimedia.py`.
"""

import logging

from collectors.base_collector import BaseCollector
from collectors.utils import extract_year, is_bot_block, limit_text

logger = logging.getLogger("freelance-radar.collector.nac")

WP_BASE = "https://nac.gov.pl/wp-json/wp/v2"
PER_PAGE = 100


class NacCollector(BaseCollector):
    source_name = "nac"
    base_url = "https://nac.gov.pl"

    async def scrape(self) -> list[dict]:
        assets: list[dict] = []

        # 1) Медиатеки: основной источник архивных фотографий
        assets.extend(await self._search_media())
        if len(assets) < self.limit:
            assets.extend(await self._search_posts())

        return assets[: self.limit]

    async def _search_media(self) -> list[dict]:
        assets: list[dict] = []
        page = 1
        while len(assets) < self.limit and page <= 20:
            url = f"{WP_BASE}/media"
            resp = await self._get(
                url,
                params={
                    "search": self.query,
                    "per_page": min(PER_PAGE, self.limit),
                    "page": page,
                },
                headers={"Accept": "application/json"},
            )
            if resp is None:
                logger.warning(
                    "[nac] HTTP-ошибка/блокировка на странице %d медиатеки", page
                )
                break
            if is_bot_block(resp.text[:2000]):
                logger.warning(
                    "[nac] антибот-защита (Incapsula/nginx) блокирует /wp-json/wp/v2/media. "
                    "Источник недоступен напрямую — см. комментарий в nac.py."
                )
                break

            items = resp.json()
            if not isinstance(items, list) or not items:
                break
            for item in items:
                asset = self._parse_media(item)
                if asset and self._accepts(asset):
                    assets.append(asset)
                    if len(assets) >= self.limit:
                        break

            total_pages = resp.headers.get("X-WP-TotalPages")
            try:
                if int(total_pages or 0) <= page:
                    break
            except ValueError:
                break
            page += 1

        return assets

    async def _search_posts(self) -> list[dict]:
        """Поиск постов с прикреплённой обложкой (featured_media)."""
        assets: list[dict] = []
        page = 1
        while len(assets) < self.limit and page <= 10:
            url = f"{WP_BASE}/posts"
            resp = await self._get(
                url,
                params={
                    "search": self.query,
                    "per_page": 50,
                    "page": page,
                    "_fields": "id,title,guid,featured_media,date",
                },
                headers={"Accept": "application/json"},
            )
            if resp is None or is_bot_block(resp.text[:2000]):
                break
            try:
                posts = resp.json()
            except Exception:
                break
            if not isinstance(posts, list) or not posts:
                break
            for post in posts:
                if len(assets) >= self.limit:
                    break
                media_id = post.get("featured_media")
                if not media_id:
                    continue
                media = await self._fetch_media_item(media_id)
                if not media:
                    continue
                asset = self._parse_media(media)
                if not asset:
                    continue
                if not self._accepts(asset):
                    continue
                if post.get("title", {}).get("rendered"):
                    asset["title"] = limit_text(post["title"]["rendered"], 300)
                asset["source_url"] = post.get("guid", {}).get("rendered", "")
                assets.append(asset)

            total_pages = resp.headers.get("X-WP-TotalPages")
            try:
                if int(total_pages or 0) <= page:
                    break
            except ValueError:
                break
            page += 1

        return assets

    async def _fetch_media_item(self, media_id: int) -> dict | None:
        url = f"{WP_BASE}/media/{media_id}"
        resp = await self._get(url, headers={"Accept": "application/json"})
        if resp is None or is_bot_block(resp.text[:2000]):
            return None
        try:
            data = resp.json()
        except Exception:
            return None
        return data if isinstance(data, dict) else None

    def _parse_media(self, item: dict) -> dict | None:
        sizes = (item.get("media_details") or {}).get("sizes") or {}
        full = sizes.get("full") or {}
        file_url = (
            full.get("source_url")
            or item.get("source_url")
            or (item.get("guid") or {}).get("rendered")
        )
        if not file_url:
            logger.debug("[nac] медиа без ссылки на файл — пропуск")
            return None

        title = limit_text((item.get("title") or {}).get("rendered") or "", 300)
        description = limit_text(
            (item.get("description") or {}).get("rendered") or "", 400
        )
        caption = limit_text((item.get("caption") or {}).get("rendered") or "", 200)
        if caption and caption not in description:
            description = caption if not description else f"{description} — {caption}"

        # Год: метаданные даты публикации/съёмки → описание → regex по названию
        year = extract_year(
            (item.get("date") or "")[:4],
            (item.get("modified") or "")[:4],
            description,
            title,
        )

        return {
            "title": title,
            "source_url": (item.get("link") or "")
                          or (item.get("guid") or {}).get("rendered", ""),
            "file_url": file_url,
            "thumbnail_url": (
                (sizes.get("medium") or {}).get("source_url")
                or full.get("source_url")
                or ""
            ),
            "description": description,
            "year": year,
            "source": self.source_name,
            "file_type": self._file_type(file_url),
            "tags": [],
        }

    @staticmethod
    def _file_type(url: str) -> str:
        path = url.split("?")[0]
        ext = path.rsplit(".", 1)[-1].lower() if "." in path.rsplit("/", 1)[-1] else ""
        return ext if ext in {"jpg", "jpeg", "png", "gif", "tif", "tiff", "webp"} else "jpg"
