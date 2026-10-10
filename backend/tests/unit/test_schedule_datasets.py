"""Public schedule adapter regression against audited source files."""
from pathlib import Path

import pytest

from app.ingest.schedule_datasets.cambridge import read_cambridge
from app.ingest.schedule_datasets.gt10_xlsx import read_gt10

DATA = Path(__file__).resolve().parents[4] / "data"


def test_gt10_export_and_input_keep_identity_and_raw_dates():
    root = DATA / "GT10BLDG-P6-Schedule"
    export = read_gt10(root / "exports/GT10BLDG_v1_P6_export.xlsx")
    source = read_gt10(root / "source/GT10BLDG_input_activities_relationships.xlsx", version="input")
    assert (export["task_count"], export["relationship_count"]) == (140, 176)
    assert (source["task_count"], source["relationship_count"]) == (140, 176)
    assert {row["cells"]["task_code"] for row in export["tasks"]} == {
        row["cells"]["Activity ID"] for row in source["tasks"]
    }
    f8 = next(row for row in export["tasks"] if row["cells"]["task_code"] == "SUP-F8-06")
    assert f8["cells"]["task_name"] == "De-shuttering - F9"
    assert f8["cells"]["start_date"]["precision"] == "source_datetime"
    assert f8["cells"]["start_date"]["timezone_basis"] == "unspecified"
    assert not any(key.startswith("actual") for key in f8["cells"])


def test_gt10_rejects_unresolved_link(tmp_path):
    from openpyxl import Workbook
    book = Workbook()
    task = book.active
    task.title = "TASK"
    task.append(["task_code"])
    task.append(["Activity ID"])
    task.append(["A"])
    edge = book.create_sheet("TASKPRED")
    edge.append(["pred_task_id", "task_id"])
    edge.append(["Predecessor", "Successor"])
    edge.append(["A", "MISSING"])
    path = tmp_path / "broken.xlsx"
    book.save(path)
    with pytest.raises(ValueError, match="unresolved links"):
        read_gt10(path)


def test_cambridge_stream_preserves_composite_id_and_raw_values():
    item = next(read_cambridge(DATA / "cambridge -construction schedules/JPF_Anonymised_Project_Data.json"))
    assert item["project_id"] == "26256"
    assert len(item["activities"]) == 7864
    activity = item["activities"][0]
    assert activity["identity"] == ["cambridge", "26256", "1249674"]
    assert "Actual_Start_Date" in activity["raw"]
    assert activity["timestamp_basis"] == "source_string_timezone_unspecified"
