from pathlib import Path

import pytest

from app.ingest.schedules import parse_schedule_csv


FIXTURE = Path(__file__).resolve().parents[3] / "data/synthetic/schedules/demo-utility-01.csv"


def test_canonical_schedule_parses_and_preserves_identifiers():
    rows, _, errors = parse_schedule_csv(FIXTURE.read_bytes())
    assert errors == []
    assert rows is not None
    assert len(rows) == 12


@pytest.mark.parametrize(
    ("before", "after", "error_fragment"),
    [
        ("PIP-B-ERECT-024", "PIP-A-ERECT-024", "duplicate activity ID"),
        ("activity_name", "activity_label", "missing required columns"),
        ("2026-09-19", "not-a-date", "must be ISO date"),
    ],
)
def test_schedule_validation_rejects_bad_rows(before, after, error_fragment):
    raw = FIXTURE.read_text(encoding="utf-8").replace(before, after, 1).encode()
    rows, _, errors = parse_schedule_csv(raw)
    assert rows is None
    assert any(error_fragment in error["message"] for error in errors)


def test_leading_zero_identifier_survives():
    raw = FIXTURE.read_text(encoding="utf-8").replace("PIP-A-ERECT-024", "00024", 1).encode()
    rows, _, errors = parse_schedule_csv(raw)
    assert errors == []
    assert rows[0][0]["activity_id"] == "00024"
