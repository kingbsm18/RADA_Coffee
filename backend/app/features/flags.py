"""Tiny feature-flag helper driven by FEATURE_FLAGS=name1,name2."""

from __future__ import annotations

from app.config import settings


def enabled_flags() -> frozenset[str]:
    return frozenset(
        flag.strip() for flag in settings.feature_flags.split(",") if flag.strip()
    )


def is_enabled(name: str) -> bool:
    return name in enabled_flags()
