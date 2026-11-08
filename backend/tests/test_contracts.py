"""The pydantic models and contracts/*.json must describe the same payloads."""

import json
import uuid
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from app.config import assert_tz_database_current
from app.engine.types import MAX_SALE_QUANTITY
from app.schemas.events import PosSaleIn, VisualEventIn

CONTRACTS = Path(__file__).resolve().parents[2] / "contracts"


def validator(name: str) -> Draft202012Validator:
    schema = json.loads((CONTRACTS / name).read_text())
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


EVENT = {
    "schema": "visual_event.v1", "event_id": str(uuid.uuid4()), "site_id": "cafe-01", "camera_id": "cam-1",
    "timestamp": "2026-11-05T10:42:13.250+01:00", "category": "coffee", "count": 1, "confidence": 0.91,
    "snapshot_ref": "snap/2026-11-05/104213_cam1.jpg", "model_version": "v0.1",
}
SALE = {
    "site_id": "cafe-01", "external_id": "T-1", "timestamp": "2026-11-05T10:40:00Z", "product_name": "Café",
    "pos_category": "Boissons chaudes", "quantity": 2, "unit_price": "25.00", "status": "paid", "raw": {"a": "b"},
}


def accepted_by_both(name: str, payload: dict, model) -> bool:
    schema_ok = validator(name).is_valid(payload)
    try:
        model.model_validate(payload)
        model_ok = True
    except ValidationError:
        model_ok = False
    assert schema_ok == model_ok, f"contract and model disagree on {payload}"
    return schema_ok


def test_example_payload_from_the_project_context_is_valid_everywhere() -> None:
    assert accepted_by_both("visual_event.v1.schema.json", EVENT, VisualEventIn)
    assert accepted_by_both("pos_sale.v1.schema.json", SALE, PosSaleIn)


@pytest.mark.parametrize(
    "change",
    [
        {"count": 0}, {"count": MAX_SALE_QUANTITY + 1}, {"confidence": 1.01}, {"confidence": -0.01},
        {"event_id": "nope"}, {"schema": "visual_event.v2"}, {"extra": 1}, {"category": ""},
    ],
)
def test_visual_event_edge_cases_agree(change) -> None:
    assert not accepted_by_both("visual_event.v1.schema.json", {**EVENT, **change}, VisualEventIn)


@pytest.mark.parametrize("missing", ["event_id", "site_id", "camera_id", "timestamp", "category", "count", "confidence", "model_version", "schema"])
def test_visual_event_required_fields_agree(missing) -> None:
    assert not accepted_by_both("visual_event.v1.schema.json", {k: v for k, v in EVENT.items() if k != missing}, VisualEventIn)


def test_snapshot_ref_may_be_null() -> None:
    assert accepted_by_both("visual_event.v1.schema.json", {**EVENT, "snapshot_ref": None}, VisualEventIn)


@pytest.mark.parametrize(
    "change",
    [
        {"quantity": 0}, {"quantity": MAX_SALE_QUANTITY + 1}, {"status": "void"}, {"status": "pending"},
        {"unit_price": "-1.00"}, {"unit_price": "25.123"}, {"unit_price": "abc"}, {"extra": 1}, {"product_name": ""},
    ],
)
def test_pos_sale_edge_cases_agree(change) -> None:
    assert not accepted_by_both("pos_sale.v1.schema.json", {**SALE, **change}, PosSaleIn)


@pytest.mark.parametrize("price", ["0", "0.5", "25", "25.00", "9999999999.99"])
def test_valid_prices_agree(price) -> None:
    assert accepted_by_both("pos_sale.v1.schema.json", {**SALE, "unit_price": price}, PosSaleIn)


def test_models_serialize_back_to_valid_contract_payloads() -> None:
    event = VisualEventIn.model_validate(EVENT).model_dump(mode="json", by_alias=True)
    assert validator("visual_event.v1.schema.json").is_valid(event)
    sale = PosSaleIn.model_validate(SALE).model_dump(mode="json")
    assert sale["unit_price"] == "25.00" and validator("pos_sale.v1.schema.json").is_valid(sale)  # Decimal -> string


def test_quantity_bounds_match_the_engine_constant() -> None:
    event_schema = json.loads((CONTRACTS / "visual_event.v1.schema.json").read_text())
    sale_schema = json.loads((CONTRACTS / "pos_sale.v1.schema.json").read_text())
    assert event_schema["properties"]["count"]["maximum"] == MAX_SALE_QUANTITY
    assert sale_schema["properties"]["quantity"]["maximum"] == MAX_SALE_QUANTITY


def test_timezone_database_knows_morocco_is_utc0_since_september_2026() -> None:
    """Fails on a machine/image with an outdated tz database (it would shift all times by 1 h)."""
    assert_tz_database_current()
