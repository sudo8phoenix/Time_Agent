import shutil
import socket

import pytest

from evaluation.published_model_comparison import FIXTURE, verify_and_score


def test_published_outcomes_rescore_with_retained_failures_without_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Publication scoring must stay offline")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    result = verify_and_score()
    assert {name: row["exact"] for name, row in result["configurations"].items()} == {
        "All 20B": 4,
        "120B + 20B": 4,
        "Qwen + 20B": 4,
        "All Qwen": 2,
    }
    assert result["retained_report_attempts"] == 18
    assert result["latest_comparisons"] == 16
    assert result["release_accepted"] is False


def test_changed_published_evidence_is_rejected_before_scoring(tmp_path):
    root = tmp_path / "fixture"
    shutil.copytree(FIXTURE, root)
    (root / "outcomes.json").write_text("[]\n")
    with pytest.raises(ValueError, match="Published evidence changed"):
        verify_and_score(root)
