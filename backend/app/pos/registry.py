"""app/pos/registry.py — TODO: implement (see docs/architecture.md)."""
"""Registry for POS provider adapters."""

from __future__ import annotations

from collections.abc import Callable
from threading import RLock

from app.pos.base import POSAdapter


class POSRegistryError(Exception):
    """Base exception for POS registry errors."""


class AdapterAlreadyRegisteredError(POSRegistryError):
    """Raised when an adapter name is already registered."""


class AdapterNotFoundError(POSRegistryError):
    """Raised when a requested adapter does not exist."""


AdapterFactory = Callable[[str], POSAdapter]


class POSAdapterRegistry:
    """Thread-safe registry of POS adapter factories.

    A factory receives a site_id and returns a configured POSAdapter.
    Provider credentials and configuration should be loaded by the
    factory from the application's secure configuration layer.
    """

    def __init__(self) -> None:
        self._factories: dict[str, AdapterFactory] = {}
        self._lock = RLock()

    @staticmethod
    def _normalize_name(name: str) -> str:
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Adapter name cannot be empty")

        return name.strip().lower()

    def register(
        self,
        name: str,
        factory: AdapterFactory,
        *,
        replace: bool = False,
    ) -> None:
        """Register a POS adapter factory."""

        normalized_name = self._normalize_name(name)

        if not callable(factory):
            raise TypeError("factory must be callable")

        with self._lock:
            if (
                normalized_name in self._factories
                and not replace
            ):
                raise AdapterAlreadyRegisteredError(
                    f"POS adapter {normalized_name!r} is already registered"
                )

            self._factories[normalized_name] = factory

    def unregister(self, name: str) -> None:
        """Remove a registered adapter."""

        normalized_name = self._normalize_name(name)

        with self._lock:
            if normalized_name not in self._factories:
                raise AdapterNotFoundError(
                    f"POS adapter {normalized_name!r} is not registered"
                )

            del self._factories[normalized_name]

    def create(
        self,
        name: str,
        site_id: str,
    ) -> POSAdapter:
        """Create an adapter instance for one site."""

        normalized_name = self._normalize_name(name)

        if not isinstance(site_id, str) or not site_id.strip():
            raise ValueError("site_id cannot be empty")

        with self._lock:
            factory = self._factories.get(normalized_name)

        if factory is None:
            raise AdapterNotFoundError(
                f"POS adapter {normalized_name!r} is not registered"
            )

        adapter = factory(site_id.strip())

        if not isinstance(adapter, POSAdapter):
            raise TypeError(
                f"Factory {normalized_name!r} must return a POSAdapter"
            )

        if adapter.site_id != site_id.strip():
            raise ValueError(
                "Adapter factory returned an adapter for another site"
            )

        return adapter

    def names(self) -> tuple[str, ...]:
        """Return registered adapter names in deterministic order."""

        with self._lock:
            return tuple(sorted(self._factories))

    def is_registered(self, name: str) -> bool:
        """Check whether an adapter name is registered."""

        normalized_name = self._normalize_name(name)

        with self._lock:
            return normalized_name in self._factories


# Application-level registry.
pos_registry = POSAdapterRegistry()


def register_adapter(
    name: str,
    factory: AdapterFactory,
    *,
    replace: bool = False,
) -> None:
    """Register an adapter in the application-level registry."""

    pos_registry.register(name, factory, replace=replace)


def get_adapter(
    name: str,
    site_id: str,
) -> POSAdapter:
    """Create an adapter from the application-level registry."""

    return pos_registry.create(name, site_id)


def available_adapters() -> tuple[str, ...]:
    """List the available POS integrations."""

    return pos_registry.names()
