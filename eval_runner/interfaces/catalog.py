"""
eval_runner.interfaces.catalog
Public Extension Family: CatalogStore Contract
"""

from abc import ABC, abstractmethod
from typing import Any


class CatalogStore(ABC):
    """
    Abstraction for scenario discovery, catalog management, and scenario resolution.
    OSS Reference: LocalFileCatalogStore
    Control Plane / Enterprise: RemoteCatalogStore / PostgresCatalogStore
    """

    @abstractmethod
    def list_scenarios(self, category: str | None = None) -> list[dict[str, Any]]:
        """Lists available scenario metadata in the catalog."""
        raise NotImplementedError

    @abstractmethod
    def get_scenario(self, scenario_id: str) -> dict[str, Any] | None:
        """Retrieves parsed scenario definition by identifier."""
        raise NotImplementedError

    @abstractmethod
    def save_scenario(self, scenario_id: str, scenario_data: dict[str, Any]) -> str:
        """Persists or updates a scenario in the catalog."""
        raise NotImplementedError

    @abstractmethod
    def delete_scenario(self, scenario_id: str) -> bool:
        """Removes a scenario from the catalog."""
        raise NotImplementedError
