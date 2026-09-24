from pathlib import Path

from app.ingest.native_schedule.microsoft import read_schedule


ROOT = Path(__file__).resolve().parents[3]


def test_mspdi_preserves_uid_separately_from_display_id_and_hierarchy():
    preview = read_schedule(ROOT / "backend/tests/fixtures/native_schedule/tiny_mspdi.xml")
    assert preview.source_format == "msp_xml"
    assert preview.selected_project_id.startswith("project-1:")
    task = next(item for item in preview.tasks if item.source_task_id == "24")
    assert task.external_id == "24"
    assert task.source_fields["display_id"] == "3"
    assert task.source_wbs_id == "10"
    assert len(preview.wbs) == 1
    assert preview.relationships[0].predecessor_source_task_id == "24"
    assert preview.relationships[0].successor_source_task_id == "25"


def test_real_mpp_preserves_uid_hierarchy_and_dependencies():
    path = ROOT / "backend/tests/fixtures/native_schedule/public_sample.mpp"
    preview = read_schedule(path)
    assert preview.source_format == "msp_mpp"
    assert len(preview.tasks) == 35
    assert len(preview.wbs) == 6
    assert len(preview.relationships) == 33
    kickoff = next(task for task in preview.tasks if task.name == "Project Kickoff")
    assert kickoff.external_id == kickoff.source_task_id == "86"
    assert kickoff.source_fields["display_id"] == "1"
