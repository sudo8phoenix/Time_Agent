"""Acceptance checks for the actual local mixed-workload probe."""
import json

from evaluation.probe_runtime_mixed_batch26 import run


def test_actual_mixed_probe_drains_both_queues_and_preserves_unmeasured_provider_fields(tmp_path):
    result = run(tmp_path / "probe", duration_seconds=0)
    assert result["status"] == "completed" and result["errors"] == []
    assert result["report_completions"] == 24
    assert result["provider_admission_wait_ms"] is None
    assert result["provider_transport_ms"] is None
    assert result["phase_resources"][-1]["approved"] == 12
    assert result["phase_resources"][-1]["delivered"] == 12
    assert result["phase_resources"][-1]["conversation_succeeded"] == 12
    assert result["peak_checked_out_connections"] >= 2
    assert {row["shape"] for row in result["api_visible_readiness"]} == {"short", "long_multi_event"}
    assert all(row["submission_to_api_visible_ms"] > 0 for row in result["api_visible_readiness"])
    for metric in ["db_transaction_ms", "db_statement_ms", "application_queue_wait_ms", "api_read_ms"]:
        assert result["measurements"][metric]["count"] > 0
    assert result["measurements"]["cold:long_multi_event:extraction_postprocess_ms"]["count"] == 6
    assert result["measurements"]["warm:long_multi_event:extraction_postprocess_ms"]["count"] == 6
    assert result["queue_samples"][-1]["report_backlog"] == 0
    assert result["queue_samples"][-1]["conversation_backlog"] == 0
    assert json.loads((tmp_path / "probe" / "results.json").read_text())["status"] == "completed"
