"""Коллектор Społeczne Archiwum Warszawy (www.tubylotustalo.pl/spoleczne-archiwum).

7 000+ фотографий Варшавы, собранных жителями. Официального API нет —
парсим HTML-галереи аккуратно:

- список галерей: `/spoleczne-archiwum?start={N}` (шаг 20);
- отбираются только галереи, у которых слага названия совпадает с запросом;
- на странице галереи изображения доступны в размере `_1920x1200_1.jpg`
  (проверено 2026-08-04: скачивается без Referer; большие варианты и
  исходник отдают HTML вместо JPEG — их не трогаем).

⚠️ Разрешение ограничено ~1920 px — источник не подходит для фотограмметрии,
поэтому его ассеты помечаются как обычные, без флага photogrammetry_ready.
"""

import logging
import re

from collectors.base_collector import BaseCollector
from collectors.utils import extract_year, limit_text

logger = logging.getLogger("freelance-radar.collector.spoleczne_archiwum")

LIST_URL = "https://www.tubylotustalo.pl/spoleczne-archiwum"
IMG_BASE = "https://www.tubylotustalo.pl"
# Самый крупный доступный размер (проверен живым запросом).
BEST_SIZE = "_1920x1200_1.jpg"

_GALLERY_LINK_RE = re.compile(r"/spoleczne-archiwum/(\d+)-[^/?#]+")


class SpoleczneArchiwumCollector(BaseCollector):
    source_name = "spoleczne_archiwum"
    base_url = "https://www.tubylotustalo.pl"

    async def scrape(self) -> list[dict]:
        assets: list[dict] = []
        seen: set[str] = set()
        query_words = [
            w for w in re.sub(r"[^a-ząćęłńóśźż0-9]+", " ", self.query.lower()).split()
            if len(w) > 2
        ]

        start = 0
        while len(assets) < self.limit and start <= 300:
            soup = await self._fetch_soup(f"{LIST_URL}?start={start}")
            if soup is None:
                break

            links = []
            for a in soup.select('a[href*="/spoleczne-archiwum/"]'):
                href = a.get("href", "")
                if _GALLERY_LINK_RE.match(href) and href not in seen:
                    links.append(href)
            if not links:
                break

            for href in links:
                seen.add(href)
                if query_words and not any(w in href.lower() for w in query_words):
                    continue
                page_assets = await self._parse_gallery(href)
                for asset in page_assets:
                    if self._accepts(asset):
                        assets.append(asset)
                if assets:
                    logger.info(
                        "[spoleczne_archiwum] галерея %s: +%d ассетов",
                        href, len(page_assets),
                    )
                if len(assets) >= self.limit:
                    break

            start += 20

        return assets[: self.limit]

    async def _parse_gallery(self, href: str) -> list[dict]:
        soup = await self._fetch_soup(self._abs_url(href))
        if soup is None:
            return []

        title_tag = soup.find("title")
        title = limit_text(title_tag.get_text() if title_tag else "", 200)
        if not title or title.lower().startswith("społeczne"):
            title = href.rsplit("/", 1)[-1].split("-", 1)[-1].replace("-", " ") or title

        description = limit_text(self._first_paragraph(soup), 400)

        # Изображения лучшего доступного размера
        urls = []
        for img in soup.select("img[src]"):
            src = img.get("src", "")
            if "/images/min/artykuly/" not in src:
                continue
            best = src.replace("_400x0_1.jpg", BEST_SIZE)
            if not best.endswith(BEST_SIZE):
                continue
            if best not in urls:
                urls.append(best)

        year = extract_year(description, title)

        assets = []
        for num, url in enumerate(urls):
            assets.append({
                "title": title if len(urls) == 1 else f"{title} — фото {num + 1}",
                "source_url": self._abs_url(href),
                "file_url": f"{IMG_BASE}{url}",
                "thumbnail_url": f"{IMG_BASE}{url.replace(BEST_SIZE, '_400x0_1.jpg')}",
                "description": description,
                "year": year,
                "source": self.source_name,
                "file_type": "jpg",
                "tags": [f"foto_{num + 1}"] if len(urls) > 1 else [],
            })
        return assets

    @staticmethod
    def _first_paragraph(soup) -> str:
        for tag in soup.select("article p, .item-page p, .com_content p"):
            text = tag.get_text(" ", strip=True)
            if len(text) > 60:
                return text
        return ""
