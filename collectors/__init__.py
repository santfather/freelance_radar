"""Реестр коллекторов исторических медиа.

Каждый коллектор наследует BaseCollector, принимает `query`, `limit`
(и опционально `language`, `year_from`/`year_to`) и возвращает список
словарей с полями title/file_url/thumbnail_url/description/year/source/
file_type/tags.

`COLLECTOR_REGISTRY` — единый реестр для автоматического обнаружения
источников: ключ — имя источника из запроса (`/api/collect`), значение —
класс коллектора.

Статус источников (на момент 2026-08-04):
- wikimedia, polona, gallica, metmuseum, muzeum_warszawy, spoleczne_archiwum —
  работают (метmuseum и gallica — открытые API без ключа);
- europeana, rijksmuseum, prometheus — требуют бесплатный ключ из `.env`;
- nac, szukajwarchiwach, britishmuseum — закрыты антибот-защитой или
  недоступны, коллекторы реализованы по контракту API и завершаются
  с пояснением в errors.
"""

from collectors.base_collector import BaseCollector
# British Museum закрыт SPARQL-таймаутами (на 2026-08-04) — временно исключён
# из реестра, чтобы не тратить время на неработающий источник.
# from collectors.britishmuseum import BritishMuseumCollector
from collectors.europeana import EuropeanaCollector
from collectors.gallica import GallicaCollector
from collectors.look_and_learn import LookAndLearnCollector
from collectors.manager import CollectorManager
from collectors.metmuseum import MetMuseumCollector
from collectors.muzeum_warszawy import MuzeumWarszawyCollector
from collectors.nac import NacCollector
from collectors.polona import PolonaCollector
from collectors.prometheus import PrometheusCollector
from collectors.rijksmuseum import RijksmuseumCollector
from collectors.spoleczne_archiwum import SpoleczneArchiwumCollector
from collectors.szukajwarchiwach import SzukajWArchiwachCollector
from collectors.um_warszawa import UmWarszawaCollector
from collectors.wikimedia import WikimediaCollector

# Реестр для автоматического обнаружения источников
COLLECTOR_REGISTRY: dict[str, type[BaseCollector]] = {
    "wikimedia": WikimediaCollector,
    "polona": PolonaCollector,
    "europeana": EuropeanaCollector,
    "gallica": GallicaCollector,
    "rijksmuseum": RijksmuseumCollector,
    "metmuseum": MetMuseumCollector,
    # "britishmuseum": BritishMuseumCollector,  # закрыт SPARQL-таймаутами
    "prometheus": PrometheusCollector,
    "lookandlearn": LookAndLearnCollector,
    "nac": NacCollector,
    "um_warszawa": UmWarszawaCollector,
    "szukajwarchiwach": SzukajWArchiwachCollector,
    "muzeum_warszawy": MuzeumWarszawyCollector,
    "spoleczne_archiwum": SpoleczneArchiwumCollector,
}

ALL_COLLECTORS = list(COLLECTOR_REGISTRY.values())

__all__ = [
    "BaseCollector",
    "WikimediaCollector",
    "PolonaCollector",
    "EuropeanaCollector",
    "GallicaCollector",
    "RijksmuseumCollector",
    "MetMuseumCollector",
    # "BritishMuseumCollector",  # закрыт SPARQL-таймаутами
    "PrometheusCollector",
    "LookAndLearnCollector",
    "NacCollector",
    "UmWarszawaCollector",
    "SzukajWArchiwachCollector",
    "MuzeumWarszawyCollector",
    "SpoleczneArchiwumCollector",
    "CollectorManager",
    "COLLECTOR_REGISTRY",
    "ALL_COLLECTORS",
]
