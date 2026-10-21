"""Frozen two-account study controls; no network or real credentials."""

from copy import deepcopy
import json
from threading import Lock

import pytest

from app.llm.hosted import HostedAdmission, HostedCapacityError
from evaluation.account_pair_study import CASES, DEMOS, SCHEMA, Study, dynamic_examples, prepare


def test_preparation_is_frozen_synthetic_and_bounded(tmp_path):
    p = tmp_path / "prepared"
    plan = prepare(p)
    assert plan["budget"]["calls"] == 64 and plan["budget"]["list_price_usd"] == 1
    assert plan["margin"]["tokens_per_minute"] == 6000
    assert not plan["release_accepted"]
    assert {row["family"] for row in CASES}.isdisjoint({row["family"] for row in DEMOS})
    assert len({row["id"] for row in plan["trials"]}) == len(plan["trials"])
    with pytest.raises(FileExistsError):
        prepare(p)


@pytest.mark.parametrize("case", CASES, ids=lambda row: row["id"])
def test_dynamic_index_is_training_only_and_does_not_mutate_sources(case):
    before = deepcopy((CASES, DEMOS))
    chosen = dynamic_examples(case["text"])
    assert len(chosen) == 1 and chosen[0] in DEMOS and chosen[0] not in CASES
    assert before == (CASES, DEMOS)


@pytest.mark.parametrize("case", CASES, ids=lambda row: row["id"])
def test_base_payload_has_no_evaluated_gold_and_grounded_output_is_scored(tmp_path, case):
    study = object.__new__(Study)
    study.output = tmp_path
    study.lock = Lock()
    study.tokens = {2: "fixture-secret"}
    captured = []

    def transport(slot, trial, method, url, payload, timeout, headers):
        captured.append(payload)
        return 200, dict(
            choices=[
                dict(
                    finish_reason="stop",
                    message=dict(content=json.dumps({"events": case["events"]})),
                )
            ]
        )

    study.transport = transport
    row = study.trial(
        dict(
            id=case["id"],
            kind="extract",
            case=case["id"],
            slot=2,
            model="openai/gpt-oss-20b",
            prompt="base",
        )
    )
    assert row["success"]
    assert captured[0]["messages"][1]["content"] == case["text"]
    assert captured[0]["response_format"]["json_schema"]["schema"] == SCHEMA
    assert "fixture-secret" not in json.dumps(captured)


def test_truncated_correct_json_does_not_receive_success_credit(tmp_path):
    study = object.__new__(Study)
    study.output = tmp_path
    study.lock = Lock()
    study.tokens = {2: "fixture-secret"}
    study.transport = lambda *args: (
        200,
        dict(choices=[dict(finish_reason="length", message=dict(content='{"events":[]}'))]),
    )
    row = study.trial(
        dict(
            id="truncate",
            kind="extract",
            case="administrative",
            slot=2,
            model="openai/gpt-oss-20b",
            prompt="base",
        )
    )
    assert not row["success"] and not row["complete"]


def test_current_provider_wide_policy_still_blocks_second_account_on_first_cooldown():
    # Measured negative result, not an independent-scope implementation claim.
    gate = HostedAdmission(intervals={}, clock=lambda: 100)
    gate.acquire("groq", {}, 10)
    gate.release("groq", status=429, headers={"retry-after": "60"})
    with pytest.raises(HostedCapacityError):
        gate.acquire("groq", {}, 1)
    assert len(gate.states) == 1


def test_new_alias_cannot_multiply_current_shared_allowance():
    gate = HostedAdmission(intervals={}, clock=lambda: 100)
    gate.acquire("groq", {}, 10)
    gate.release(
        "groq",
        status=200,
        headers={"x-ratelimit-remaining-tokens": "1", "x-ratelimit-reset-tokens": "60s"},
    )
    with pytest.raises(HostedCapacityError):
        gate.acquire("groq", {"max_completion_tokens": 20}, 1)
    assert len(gate.states) == 1
