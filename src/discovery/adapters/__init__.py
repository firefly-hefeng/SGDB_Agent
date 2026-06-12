"""Database adapters for API-Routing Agent."""

from src.discovery.adapters.base import BaseAdapter
from src.discovery.adapters.cellxgene import CellXGeneAdapter
from src.discovery.adapters.ebi import EbiAdapter
from src.discovery.adapters.geo import GeoAdapter
from src.discovery.adapters.hca import HcaAdapter
from src.discovery.adapters.scea import SceaAdapter
from src.discovery.adapters.sra import SraAdapter

ADAPTERS: dict[str, type[BaseAdapter]] = {
    "geo": GeoAdapter,
    "sra": SraAdapter,
    "ebi": EbiAdapter,
    "scea": SceaAdapter,
    "cellxgene": CellXGeneAdapter,
    "hca": HcaAdapter,
}

__all__ = [
    "BaseAdapter",
    "GeoAdapter",
    "SraAdapter",
    "EbiAdapter",
    "SceaAdapter",
    "CellXGeneAdapter",
    "HcaAdapter",
    "ADAPTERS",
]
