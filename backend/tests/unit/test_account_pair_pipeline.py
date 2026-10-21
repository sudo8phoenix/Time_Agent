"""Continuation never resets parent budgets, seals or provider failures."""

import json
from types import SimpleNamespace

import pytest

from evaluation.account_pair_study import prepare as prepare_parent, digest, write
from evaluation.account_pair_pipeline import prepare, PipelineStudy
from evaluation.repeated_development import ExperimentStop


def parent(tmp_path, stopped=False):
    prepared = tmp_path / "parent-plan"
    plan = prepare_parent(prepared)
    live = tmp_path / "parent-live"
    live.mkdir()
    summary = dict(
        stopped=stopped,
        reserved_calls=36,
        reserved_tokens=120000,
        reserved_list_price_usd=0.1,
        account_reserved_tokens={"1": 3000, "2": 40000},
    )
    write(live / "summary.json", summary)
    write(live / "config.json", {"plan_sha256": digest(prepared / "plan.json")})
    write(
        live / "capture-manifest.json",
        {name: digest(live / name) for name in ("summary.json", "config.json")},
    )
    return prepared, live, plan, summary


def test_pipeline_deducts_every_parent_reservation_and_has_no_label_in_input(tmp_path):
    prepared, live, original, used = parent(tmp_path)
    result = prepare(prepared, live, tmp_path / "next")
    assert result["budget"]["calls"] == original["budget"]["calls"] - used["reserved_calls"] == 28
    assert result["budget"]["reserved_tokens"] == 480000
    assert result["budget"]["list_price_usd"] == pytest.approx(0.9)
    assert result["retained_budget"] == used
    assert len(result["schedule"]) == 6
    assert {r["arm"] for r in result["schedule"]} == {
        "deterministic",
        "one_account",
        "two_accounts",
    }
    cases = json.loads((tmp_path / "next/cases.json").read_text())
    assert all(set(case) == {"case_id", "report_date", "text"} for case in cases)
    assert 0 < result["budget"]["wall_seconds"] <= original["budget"]["wall_seconds"]


@pytest.mark.parametrize("change", ["stopped", "seal", "plan"])
def test_failed_or_changed_parent_cannot_start_new_pipeline_budget(tmp_path, change):
    prepared, live, _, _ = parent(tmp_path, stopped=change == "stopped")
    if change == "seal":
        (live / "summary.json").write_text("{}")
    if change == "plan":
        (prepared / "plan.json").write_text("{}")
    with pytest.raises(ExperimentStop):
        prepare(prepared, live, tmp_path / "next")
    assert not (tmp_path / "next").exists()


def test_pipeline_stops_after_budget_failure_before_provider_call():
    study = object.__new__(PipelineStudy)

    class Adapter:
        model = "openai/gpt-oss-20b"
        _transport = None

        def chat(self, **kwargs):
            return self._transport("POST", "unused", {}, 30, {})

    study.factory = lambda *args, **kwargs: Adapter()
    study.transport = lambda *args: (_ for _ in ()).throw(ExperimentStop("ceiling"))
    study.plan = {"absolute_deadline": 10**12}
    study.calls = []
    study.case_id = "fixture"
    study.arm = "one_account"
    study.stopped = False
    adapter = study.create(SimpleNamespace(extraction_key_slot=2), role="extraction")
    with pytest.raises(ExperimentStop):
        adapter.chat(schema={"properties": {"observations": {}}})
    assert study.stopped and study.stop_reason == "ExperimentStop"
    assert len(study.calls) == 1 and not study.calls[0]["ok"]
