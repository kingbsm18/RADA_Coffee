from datetime import datetime, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from app.models.pos_sale import PosSale
from app.pos.adapters.csv_import import CsvImportAdapter
from app.pos.base import PosImportError
from app.pos.category_mapping import normalize_key, resolve_category
from app.pos.normalizer import RowRejected, parse_decimal, parse_timestamp, parse_unit_price
from app.pos.registry import available_adapters, get_adapter, register_adapter

CASA = ZoneInfo("Africa/Casablanca")
HEADER = "external_id,timestamp,product_name,pos_category,quantity,unit_price,status\n"


def parse(text: str | bytes, **kwargs):
    content = text.encode() if isinstance(text, str) else text
    return CsvImportAdapter(**kwargs).parse(content, site_id="cafe-01", tz=CASA)


def test_comma_and_semicolon_files_with_decimal_commas() -> None:
    comma = parse(HEADER + "1,2026-11-05T10:42:00+00:00,Café,Chaud,2,25.50,paid\n")
    semi = parse(
        "external_id;timestamp;product_name;pos_category;quantity;unit_price;status\n"
        "1;05/11/2026 10:42;Café;Chaud;2;25,50;paid\n"
    )
    assert comma.sales[0].unit_price == semi.sales[0].unit_price == Decimal("25.50")
    assert comma.sales[0].timestamp == semi.sales[0].timestamp


def test_naive_timestamps_use_the_site_timezone_morocco_switched_to_utc0() -> None:
    """Morocco returned to UTC+0 on 2026-09-20: same wall-clock time, different instant."""
    after = parse_timestamp("2026-11-05 10:42:00", CASA)
    before = parse_timestamp("2026-09-19 10:42:00", CASA)
    assert after.astimezone(timezone.utc) == datetime(2026, 11, 5, 10, 42, tzinfo=timezone.utc)
    assert before.astimezone(timezone.utc) == datetime(2026, 9, 19, 9, 42, tzinfo=timezone.utc)


def test_ambiguous_local_time_during_the_clock_change_takes_the_first_occurrence() -> None:
    # 2026-09-20 02:00 -> 01:00: local 01:30 happens twice. fold=0 = first (UTC+1).
    assert parse_timestamp("2026-09-20 01:30:00", CASA).astimezone(timezone.utc) == datetime(
        2026, 9, 20, 0, 30, tzinfo=timezone.utc
    )


@pytest.mark.parametrize(
    "value", ["", "yesterday", "13/13/2026 10:42", "2026-13-45 10:00:00"]
)
def test_unparseable_timestamps_are_rejected(value: str) -> None:
    with pytest.raises(RowRejected):
        parse_timestamp(value, CASA)


@pytest.mark.parametrize("value", ["1,234.50", "1.234,50", "abc", "", "NaN", "1,2,3"])
def test_ambiguous_or_invalid_numbers_are_rejected(value: str) -> None:
    with pytest.raises(RowRejected):
        parse_decimal(value, "unit_price")


def test_price_with_more_than_two_decimals_or_negative_is_rejected() -> None:
    with pytest.raises(RowRejected, match="2 decimals"):
        parse_unit_price("2.505")
    with pytest.raises(RowRejected, match="negative"):
        parse_unit_price("-1")
    assert parse_unit_price("0") == Decimal("0.00")  # free item is valid (R3)


def test_bad_rows_are_reported_but_do_not_stop_the_import() -> None:
    result = parse(
        HEADER
        + "1,2026-11-05T10:00:00Z,Café,Chaud,1,25,paid\n"
        + "2,2026-11-05T10:00:00Z,Café,Chaud,1.5,25,paid\n"  # fractional quantity
        + "3,2026-11-05T10:00:00Z,Café,Chaud,1,25,pending\n"  # unknown status
        + "4,2026-11-05T10:00:00Z,Café,Chaud,0,25,paid\n"
        + "5,2026-11-05T10:00:00Z,,Chaud,1,25,paid\n"  # no product
        + "6,2026-11-05T10:00:00Z,Café,Chaud,500,25,paid\n"  # absurd quantity
    )
    assert result.rows_received == 6 and len(result.sales) == 1
    assert sorted(e.row for e in result.errors) == [2, 3, 4, 5, 6]


def test_status_aliases_and_default_status() -> None:
    result = parse(
        HEADER
        + "1,2026-11-05T10:00:00Z,A,C,1,5,annulé\n"
        + "2,2026-11-05T10:00:00Z,A,C,1,5,Refund\n"
        + "3,2026-11-05T10:00:00Z,A,C,1,5,PAID\n"
    )
    assert [s.status for s in result.sales] == ["voided", "refunded", "paid"]
    no_status_column = parse(
        "external_id,timestamp,product_name,quantity,unit_price\n1,2026-11-05T10:00:00Z,A,1,5\n"
    )
    assert no_status_column.sales[0].status == "paid"


def test_duplicates_inside_a_file() -> None:
    row = "1,2026-11-05T10:00:00Z,Café,Chaud,1,25,paid\n"
    exact = parse(HEADER + row + row)
    assert len(exact.sales) == 1 and not exact.errors
    conflicting = parse(HEADER + row + "1,2026-11-05T10:00:00Z,Café,Chaud,2,25,paid\n")
    assert len(conflicting.sales) == 1 and "conflicting duplicate" in conflicting.errors[0].message


def test_file_level_errors() -> None:
    with pytest.raises(PosImportError, match="missing required columns"):
        parse("external_id,timestamp\n1,2026-11-05\n")
    with pytest.raises(PosImportError, match="UTF-8"):
        parse(b"\xff\xfe\x00bad")
    with pytest.raises(PosImportError, match="empty"):
        parse("")
    with pytest.raises(PosImportError, match="too many rows"):
        parse(HEADER + "".join(f"{i},2026-11-05T10:00:00Z,A,C,1,5,paid\n" for i in range(5)), max_rows=3)


def test_custom_column_names_and_utf8_bom() -> None:
    adapter = CsvImportAdapter(
        column_map={"external_id": "Ticket", "timestamp": "Date", "product_name": "Article",
                    "quantity": "Qté", "unit_price": "Prix"}
    )
    content = "\ufeffTicket;Date;Article;Qté;Prix\nT-9;05/11/2026 08:15;Thé;1;12,00\n".encode()
    result = adapter.parse(content, site_id="cafe-01", tz=CASA)
    assert result.sales[0].external_id == "T-9" and result.sales[0].product_name == "Thé"
    with pytest.raises(ValueError, match="unknown canonical"):
        CsvImportAdapter(column_map={"nope": "x"})


def test_registry() -> None:
    assert "csv" in available_adapters()
    assert get_adapter("csv").name == "csv"
    with pytest.raises(KeyError):
        get_adapter("unknown")
    with pytest.raises(ValueError, match="already registered"):
        register_adapter("csv", CsvImportAdapter)


def test_your_pos_template_refuses_to_guess() -> None:
    from datetime import timedelta

    from app.pos.adapters.your_pos import YourPosAdapter

    now = datetime.now(timezone.utc)
    with pytest.raises(NotImplementedError):
        YourPosAdapter().fetch_sales(site_id="x", since=now - timedelta(hours=1), until=now, tz=CASA)


def test_category_resolution_prefers_product_over_pos_category() -> None:
    mapping = {
        ("pos_category", normalize_key("Boissons  Chaudes")): "coffee",
        ("product_name", normalize_key("Eau Gazeuse")): "soft_drink",
    }
    assert resolve_category(mapping, product_name="x", pos_category="boissons chaudes") == "coffee"
    assert resolve_category(mapping, product_name="EAU gazeuse", pos_category="boissons chaudes") == "soft_drink"
    assert resolve_category(mapping, product_name="x", pos_category=None) is None
    assert resolve_category(mapping, product_name="x", pos_category="unknown") is None


# ---------------------------------------------------------------- HTTP import
def upload(client, world, text: str, headers=None, site=None):
    return client.post(
        f"/api/v1/sites/{site or world.site}/pos/import",
        files={"file": ("sales.csv", text.encode(), "text/csv")},
        headers=headers or world.manager,
    )


def test_import_is_idempotent_and_reports_unmapped_categories(client, world, db) -> None:
    body = HEADER + "1,2026-11-05T10:00:00Z,Café,Chaud,2,25.00,paid\n2,2026-11-05T10:05:00Z,Coca,Soft,1,18.00,paid\n"
    first = upload(client, world, body).json()
    assert (first["rows_inserted"], first["rows_unchanged"], first["rows_rejected"]) == (2, 0, 0)
    assert first["unmapped"] == ["Chaud", "Soft"]  # no mapping configured yet

    second = upload(client, world, body).json()
    assert (second["rows_inserted"], second["rows_updated"], second["rows_unchanged"]) == (0, 0, 2)
    assert db.query(PosSale).count() == 2


def test_a_later_status_change_updates_the_sale_and_is_reported(client, world, db) -> None:
    upload(client, world, HEADER + "1,2026-11-05T10:00:00Z,Café,Chaud,1,25.00,paid\n")
    report = upload(client, world, HEADER + "1,2026-11-05T10:00:00Z,Café,Chaud,1,25.00,voided\n").json()
    assert report["rows_updated"] == 1 and report["status_changes"] == ["1"]
    assert db.query(PosSale).one().status == "voided"


def test_import_errors_and_limits(client, world, monkeypatch) -> None:
    assert upload(client, world, "external_id,timestamp\n1,x\n").status_code == 422
    monkeypatch.setattr("app.config.settings.pos_import_max_bytes", 50)
    assert upload(client, world, HEADER + "x" * 200).status_code == 413


def test_import_requires_membership_of_the_site_organization(client, world) -> None:
    assert upload(client, world, HEADER, headers=world.other_admin).status_code == 404
    assert client.post(f"/api/v1/sites/{world.site}/pos/import", files={"file": ("a.csv", b"x")}).status_code == 401


def test_import_batches_are_listed_for_audit(client, world) -> None:
    upload(client, world, HEADER + "1,2026-11-05T10:00:00Z,Café,Chaud,1,25.00,paid\n")
    batches = client.get(f"/api/v1/sites/{world.site}/pos/imports", headers=world.manager).json()
    assert len(batches) == 1 and batches[0]["rows_inserted"] == 1 and batches[0]["status"] == "completed"


def test_slash_dates_are_read_day_first_and_the_report_shows_the_period(client, world) -> None:
    """11/05/2026 is 11 May, not 5 November: month-first exports would be misread, so the
    import report exposes the earliest/latest sale time for the user to eyeball."""
    assert parse_timestamp("11/05/2026 10:42", CASA).month == 5
    report = upload(client, world, HEADER.replace(",", ";") + "1;11/05/2026 10:42;Café;Chaud;1;25,00;paid\n").json()
    assert report["earliest"].startswith("2026-05-11T09:42") and report["latest"] == report["earliest"]
