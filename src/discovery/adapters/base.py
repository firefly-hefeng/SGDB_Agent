"""Abstract base class for database adapters."""

from abc import ABC, abstractmethod

from src.discovery.models import DiscoveryResult, QueryIntent


class BaseAdapter(ABC):
    """Base class for all database adapters."""

    name: str = "base"

    @abstractmethod
    async def search(self, intent: QueryIntent, max_results: int = 20) -> DiscoveryResult:
        """Search the database with the given intent.

        Args:
            intent: Parsed query intent.
            max_results: Max number of results to return.

        Returns:
            DiscoveryResult containing matches from this database.
        """
        ...

    @property
    @abstractmethod
    def is_available(self) -> bool:
        """Whether this adapter is currently available."""
        ...

    async def aclose(self) -> None:
        """Release any resources (HTTP clients, etc)."""
        client = getattr(self, "client", None)
        if client is not None:
            try:
                await client.aclose()
            except Exception:
                pass
