from pathlib import Path

from app.ingest.native_schedule.primavera import read_schedule


ROOT = Path(__file__).resolve().parents[4]


def test_workspace_p6_xer_preserves_task_ids_wbs_and_relationships():
    preview = read_schedule(ROOT / "PROJECT.xer")
    assert preview.source_format == "p6_xer"
    assert preview.selected_project_id == "4507"
    assert len(preview.tasks) == 24
    assert len(preview.relationships) == 3
    assert preview.tasks[2].source_task_id == "101717"
    # XER task_code is the external activity identity; MPXJ's display row ID is not.
    assert preview.tasks[2].external_id == "1.1"
    assert preview.tasks[2].source_fields["wbs"] == "PROJECT.1"
    assert preview.relationships[0].relation_type == "FS"


def test_pmxml_and_multi_project_xer_use_actual_parser_and_require_selection():
    fixtures = ROOT / "site-progress-agent/backend/tests/fixtures/native_schedule"
    pmxml = read_schedule(fixtures / "tiny_p6.xml")
    assert pmxml.source_format == "p6_xml"
    assert pmxml.selected_project_id == "1"
    assert {task.external_id for task in pmxml.tasks if not task.is_summary} == {
        "00024", "00025", "MILE-1"
    }
    assert len(pmxml.relationships) == 1

    unselected = read_schedule(fixtures / "two_projects.xer")
    assert unselected.selected_project_id is None
    assert {project.source_project_id for project in unselected.projects} == {"1", "2"}
    assert unselected.tasks == []
    selected = read_schedule(fixtures / "two_projects.xer", "1")
    assert selected.selected_project_id == "1"
    assert any(task.external_id == "00024" for task in selected.tasks)
