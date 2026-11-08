"""Deterministic scheduling utilities for RADA Café Intelligence.

This module handles service-window scheduling and time-based execution.
It contains no database or external infrastructure dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable


@dataclass(frozen=True)
class ScheduledTask:
    """A task scheduled for execution."""

    task_id: str
    site_id: str
    scheduled_at: datetime
    task_type: str

    def __post_init__(self) -> None:
        if not self.task_id.strip():
            raise ValueError("task_id cannot be empty")

        if not self.site_id.strip():
            raise ValueError("site_id cannot be empty")

        if not self.task_type.strip():
            raise ValueError("task_type cannot be empty")

        if self.scheduled_at.tzinfo is None:
            raise ValueError("scheduled_at must be timezone-aware")


def normalize_datetime(value: datetime) -> datetime:
    """Normalize a timezone-aware datetime to UTC."""
    if value.tzinfo is None:
        raise ValueError("datetime must be timezone-aware")

    return value.astimezone(timezone.utc)


def is_due(
    scheduled_at: datetime,
    current_time: datetime,
) -> bool:
    """Return True when a scheduled task is due."""
    scheduled = normalize_datetime(scheduled_at)
    current = normalize_datetime(current_time)

    return scheduled <= current


def get_due_tasks(
    tasks: Iterable[ScheduledTask],
    current_time: datetime,
) -> list[ScheduledTask]:
    """Return tasks that are due, ordered by execution time."""
    current = normalize_datetime(current_time)

    due_tasks = [
        task
        for task in tasks
        if normalize_datetime(task.scheduled_at) <= current
    ]

    return sorted(
        due_tasks,
        key=lambda task: (
            normalize_datetime(task.scheduled_at),
            task.site_id,
            task.task_id,
        ),
    )


def calculate_next_run(
    last_run: datetime,
    interval_minutes: int,
) -> datetime:
    """Calculate the next execution time."""
    if interval_minutes <= 0:
        raise ValueError("interval_minutes must be greater than zero")

    normalized_last_run = normalize_datetime(last_run)

    return normalized_last_run + timedelta(minutes=interval_minutes)
