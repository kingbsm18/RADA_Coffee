"""Registry of POS adapters by name."""

from __future__ import annotations

from collections.abc import Callable

from app.pos.adapters.csv_import import CsvImportAdapter
from app.pos.base import ApiPosAdapter, FilePosAdapter

AdapterFactory = Callable[[], FilePosAdapter | ApiPosAdapter]

_FACTORIES: dict[str, AdapterFactory] = {"csv": CsvImportAdapter}


def register_adapter(name: str, factory: AdapterFactory) -> None:
    if name in _FACTORIES:
        raise ValueError(f"POS adapter already registered: {name!r}")
    _FACTORIES[name] = factory


def get_adapter(name: str) -> FilePosAdapter | ApiPosAdapter:
    try:
        return _FACTORIES[name]()
    except KeyError:
        raise KeyError(f"unknown POS adapter: {name!r}") from None


def available_adapters() -> list[str]:
    return sorted(_FACTORIES)
