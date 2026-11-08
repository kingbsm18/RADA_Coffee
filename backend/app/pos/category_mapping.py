"""app/pos/category_mapping.py — TODO: implement (see docs/architecture.md)."""
"""POS category mapping utilities.

Convert provider-specific POS categories and product names into
the canonical RADA AI categories used by computer vision reconciliation.

Mappings are explicit and deterministic. Unknown values are never
silently assigned to a category.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping


# Canonical categories currently used by RADA AI.
SUPPORTED_CATEGORIES = frozenset({
    "coffee",
    "soft_drink",
})


class CategoryMappingError(ValueError):
    """Base exception for category mapping errors."""


class UnknownCategoryError(CategoryMappingError):
    """Raised when no category mapping can be found."""


class InvalidCategoryError(CategoryMappingError):
    """Raised when a mapping targets an unsupported category."""


def normalize_text(value: str) -> str:
    """Normalize text for deterministic category matching.

    Examples:
        "Boissons Chaudes" -> "boissons chaudes"
        "CAFÉ" -> "cafe"
        "  Soft-Drinks  " -> "soft drinks"
    """
    if not isinstance(value, str):
        raise TypeError("Category or product name must be a string")

    value = value.strip().lower()

    # Remove accents.
    value = unicodedata.normalize("NFKD", value)
    value = "".join(
        char
        for char in value
        if not unicodedata.combining(char)
    )

    # Replace punctuation and separators with spaces.
    value = re.sub(r"[^a-z0-9]+", " ", value)

    # Collapse repeated whitespace.
    return " ".join(value.split())


@dataclass(frozen=True, slots=True)
class CategoryMapping:
    """One explicit mapping from a POS label to a RADA category."""

    source: str
    target: str

    def __post_init__(self) -> None:
        normalized_source = normalize_text(self.source)
        normalized_target = normalize_text(self.target).replace(" ", "_")

        if not normalized_source:
            raise ValueError("Mapping source cannot be empty")

        if normalized_target not in SUPPORTED_CATEGORIES:
            raise InvalidCategoryError(
                f"Unsupported RADA category: {self.target!r}"
            )

        object.__setattr__(self, "source", normalized_source)
        object.__setattr__(self, "target", normalized_target)


class CategoryMapper:
    """Resolve POS categories and product names to RADA categories.

    Resolution priority:
        1. Explicit POS category mapping.
        2. Explicit product-name mapping.
        3. UnknownCategoryError.

    No fuzzy matching or automatic guessing is performed.
    """

    def __init__(
        self,
        category_mappings: Mapping[str, str] | None = None,
        product_mappings: Mapping[str, str] | None = None,
    ) -> None:
        self._category_mappings = self._build_mapping(
            category_mappings or {}
        )

        self._product_mappings = self._build_mapping(
            product_mappings or {}
        )

    @staticmethod
    def _build_mapping(
        mappings: Mapping[str, str],
    ) -> Mapping[str, str]:
        """Validate and normalize a mapping dictionary."""
        normalized: dict[str, str] = {}

        for source, target in mappings.items():
            mapping = CategoryMapping(
                source=source,
                target=target,
            )

            if mapping.source in normalized:
                raise ValueError(
                    f"Duplicate normalized mapping: {source!r}"
                )

            normalized[mapping.source] = mapping.target

        return MappingProxyType(normalized)

    @property
    def category_mappings(self) -> Mapping[str, str]:
        """Return an immutable view of POS category mappings."""
        return self._category_mappings

    @property
    def product_mappings(self) -> Mapping[str, str]:
        """Return an immutable view of product-name mappings."""
        return self._product_mappings

    def map_category(self, pos_category: str | None) -> str | None:
        """Map an original POS category.

        Returns None when the POS category is missing.
        Raises UnknownCategoryError when a non-empty category
        has no explicit mapping.
        """
        if pos_category is None:
            return None

        normalized = normalize_text(pos_category)

        if not normalized:
            return None

        # Canonical categories can be passed directly.
        canonical = normalized.replace(" ", "_")

        if canonical in SUPPORTED_CATEGORIES:
            return canonical

        result = self._category_mappings.get(normalized)

        if result is None:
            raise UnknownCategoryError(
                f"No mapping configured for POS category "
                f"{pos_category!r}"
            )

        return result

    def map_product(self, product_name: str) -> str:
        """Map a product name using explicit product mappings."""
        normalized = normalize_text(product_name)

        if not normalized:
            raise ValueError("product_name cannot be empty")

        # A product name is not automatically a category.
        result = self._product_mappings.get(normalized)

        if result is None:
            raise UnknownCategoryError(
                f"No mapping configured for product "
                f"{product_name!r}"
            )

        return result

    def resolve(
        self,
        pos_category: str | None,
        product_name: str,
    ) -> str:
        """Resolve the canonical category for a POS sale.

        The POS category has priority when it is available.
        Product-name mapping is used only when the POS category
        is missing or empty.

        An unknown non-empty POS category raises an error rather
        than silently falling back to product-name guessing.
        """
        if pos_category is not None and normalize_text(pos_category):
            result = self.map_category(pos_category)

            if result is None:
                raise UnknownCategoryError(
                    f"Could not resolve POS category {pos_category!r}"
                )

            return result

        return self.map_product(product_name)


# Default mappings for common café POS labels.
#
# These are initial examples. They must be reviewed and adapted
# to the actual product catalog of each RADA AI customer.
DEFAULT_CATEGORY_MAPPINGS: dict[str, str] = {
    # Coffee and hot beverages
    "cafe": "coffee",
    "cafes": "coffee",
    "boissons chaudes": "coffee",
    "hot drinks": "coffee",
    "coffee": "coffee",
    "espresso": "coffee",
    "cappuccino": "coffee",

    # Soft drinks
    "boissons gazeuses": "soft_drink",
    "boissons froides": "soft_drink",
    "soft drinks": "soft_drink",
    "soft drink": "soft_drink",
    "sodas": "soft_drink",
    "soda": "soft_drink",
    "jus": "soft_drink",
    "juice": "soft_drink",
    "eau": "soft_drink",
    "water": "soft_drink",
}


DEFAULT_PRODUCT_MAPPINGS: dict[str, str] = {
    # Coffee products
    "espresso": "coffee",
    "cafe": "coffee",
    "cafe noir": "coffee",
    "cappuccino": "coffee",
    "latte": "coffee",
    "americano": "coffee",
    "cafe au lait": "coffee",
    "nespresso": "coffee",

    # Soft drinks
    "coca cola": "soft_drink",
    "coca cola zero": "soft_drink",
    "pepsi": "soft_drink",
    "sprite": "soft_drink",
    "fanta": "soft_drink",
    "schweppes": "soft_drink",
    "eau minerale": "soft_drink",
    "eau gazeuse": "soft_drink",
    "jus orange": "soft_drink",
    "jus de pomme": "soft_drink",
}


def create_default_mapper() -> CategoryMapper:
    """Create a mapper using the initial café mappings."""
    return CategoryMapper(
        category_mappings=DEFAULT_CATEGORY_MAPPINGS,
        product_mappings=DEFAULT_PRODUCT_MAPPINGS,
    )
