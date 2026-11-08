"""app/features/flags.py — TODO: implement (see docs/architecture.md)."""

"""Feature flag definitions for RADA Café Intelligence.

Feature flags allow the application to enable or disable capabilities
without changing the business logic.

This module is intentionally independent from FastAPI, the database,
environment variables and the reconciliation engine.

The application layer is responsible for loading flag values and
passing them to the components that need them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping


@dataclass(frozen=True, slots=True)
class FeatureFlags:
    """Immutable collection of explicitly configured feature flags.

    Example:
        flags = FeatureFlags(
            values={
                "pos_import": True,
                "notifications": False,
            }
        )

        if flags.is_enabled("pos_import"):
            ...
    """

    values: Mapping[str, bool] = field(default_factory=dict)

    def __post_init__(self) -> None:
        validated: dict[str, bool] = {}

        for name, enabled in self.values.items():
            if not isinstance(name, str) or not name.strip():
                raise ValueError("Feature flag names cannot be empty")

            if not isinstance(enabled, bool):
                raise TypeError(
                    f"Feature flag {name!r} must have a boolean value"
                )

            validated[name.strip()] = enabled

        object.__setattr__(
            self,
            "values",
            MappingProxyType(validated),
        )

    def is_enabled(self, name: str) -> bool:
        """Return the configured state of a feature.

        Raises KeyError when the requested flag was not configured.
        This prevents misspelled or undefined flags from being silently
        treated as disabled.
        """
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Feature flag name cannot be empty")

        try:
            return self.values[name.strip()]
        except KeyError:
            raise KeyError(
                f"Feature flag {name!r} is not configured"
            ) from None

    def has_flag(self, name: str) -> bool:
        """Check whether a flag is explicitly configured."""
        return name in self.values
