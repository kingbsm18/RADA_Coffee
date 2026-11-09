"""The simulator scenarios must tell the truth: their `expect` values are checked with the real engine."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from jsonschema import Draft202012Validator
from simulator import fake_detector

from app.engine.credits import build_credits
from app.engine.reconcile import reconcile
from app.engine.types import CategoryWindows, Detection, SaleRecord, SiteSettings
from app.models.site_settings import DEFAULT_CONFIDENCE_THRESHOLD, DEFAULT_WINDOWS_MINUTES
from app.pos.adapters.csv_import import CsvImportAdapter
from app.schemas.events import VisualEventIn

ROOT = Path(__file__).resolve().parents[2]
CONFIG = fake_detector.load(ROOT / "simulator" / "scenarios.yaml")
START = datetime(2026, 11, 5, 8, 0, tzinfo=timezone.utc)
SCHEMA = Draft202012Validator(
    __import__("json").loads((ROOT / "contracts" / "visual_event.v1.schema.json").read_text())
)
SETTINGS = SiteSettings(
    "cafe-01",
    DEFAULT_CONFIDENCE_THRESHOLD,
    {
        name: CategoryWindows(timedelta(minutes=w["lookback"]), timedelta(minutes=w["grace"]))
        for name, w in DEFAULT_WINDOWS_MINUTES.items()
    },
)
CATEGORY_BY_POS = {v["pos_category"]: k for k, v in CONFIG["categories"].items()}


@pytest.mark.parametrize("name", sorted(CONFIG["scenarios"]))
def test_scenario_expectations_match_the_engine(name: str) -> None:
    built = fake_detector.build(CONFIG, name, start=START)
    parsed = CsvImportAdapter().parse(
        fake_detector.sales_csv(built.sales).encode(), site_id="cafe-01", tz=ZoneInfo("Africa/Casablanca")
    )
    assert not parsed.errors
    credits = build_credits(
        SaleRecord(
            s.site_id, s.external_id, s.timestamp, CATEGORY_BY_POS[s.pos_category], s.quantity,
            Decimal(s.unit_price), s.status,
        )
        for s in parsed.sales
    )
    detections = [
        Detection(e["event_id"], e["site_id"], datetime.fromisoformat(e["timestamp"]), e["category"],
                  e["count"], e["confidence"])
        for e in built.events
    ]
    result = reconcile(detections, credits, [], SETTINGS, now=START + timedelta(hours=3))
    assert {o.event_id: o.state for o in result.outcomes} == built.expectations


@pytest.mark.parametrize("name", sorted(CONFIG["scenarios"]))
def test_events_are_valid_contract_payloads_and_deterministic(name: str) -> None:
    first = fake_detector.build(CONFIG, name, start=START)
    assert first == fake_detector.build(CONFIG, name, start=START)
    assert first != fake_detector.build(CONFIG, name, start=START, run_id="2")
    for event in first.events:
        assert SCHEMA.is_valid(event)
        VisualEventIn.model_validate(event)


def test_replay_cli_lists_and_dry_runs(capsys) -> None:
    from simulator import replay

    assert replay.main(["--list"]) == 0
    assert "missing_sale" in capsys.readouterr().out
    assert replay.main(["--scenario", "missing_sale", "--dry-run", "--start", "2026-11-05T08:00:00+00:00"]) == 0
    assert "3 events" in capsys.readouterr().out
