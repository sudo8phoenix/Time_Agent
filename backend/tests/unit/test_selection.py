from types import SimpleNamespace

import pytest

from app.matching.selection import SelectionValidationError, select_candidate


def observation(**overrides):
    values = dict(area="North", work_type="welding", asset_tags=["pipe-a"], text="weld pipe")
    values.update(overrides)
    return SimpleNamespace(**values)


def candidate(candidate_id, **overrides):
    values = dict(
        candidate_id=candidate_id,
        external_id=f"EXT-{candidate_id}",
        activity_name="Weld pipe A",
        area="North",
        work_type="welding",
        asset_tags=["pipe-a"],
        is_leaf=True,
        retrieval_rank=1,
        retrieval_score=0.9,
        project_id="project-1",
    )
    values.update(overrides)
    return SimpleNamespace(**values)


def fragment(fragment_id="frag-1"):
    return SimpleNamespace(fragment_id=fragment_id, quote="Observed weld", fields=["text"])


def model_result(candidate_id, **overrides):
    result = dict(
        candidate_id=candidate_id,
        mapping_state="suggested",
        evidence_fragment_ids=["frag-1"],
        reason_codes=["ID_MATCH"],
        explanation="The activity is supported by the report.",
        missing_information=[],
    )
    result.update(overrides)
    return result


def test_model_receives_dynamic_candidate_enum_and_selected_result_is_review():
    seen = {}

    def call(**kwargs):
        seen.update(kwargs)
        return model_result("a")

    result = select_candidate(observation(), [candidate("a"), candidate("b")], [fragment()], model_call=call, project_id="project-1")

    assert result.candidate_id == "a"
    assert result.match_strength.value == "review"
    assert result.review_state.value == "pending"
    assert seen["schema"]["properties"]["candidate_id"]["anyOf"][0]["enum"] == ["a", "b"]
    assert [c["candidate_id"] for c in seen["user"]["candidates"]] == ["a", "b"]


def test_empty_retrieval_bypasses_model_and_returns_unmatched():
    def never_called(**kwargs):
        raise AssertionError("model must not be called")

    result = select_candidate(observation(), [], model_call=never_called)

    assert result.candidate_id is None
    assert result.mapping_state.value == "unmatched"
    assert result.match_strength.value == "unresolved"
    assert result.candidates == []


def test_ambiguous_result_is_safe_null_selection_with_two_candidates():
    result = select_candidate(
        observation(), [candidate("a"), candidate("b")], [fragment()],
        model_call=lambda **kwargs: model_result(None, mapping_state="ambiguous", evidence_fragment_ids=[]),
        project_id="project-1",
    )

    assert result.candidate_id is None
    assert result.mapping_state.value == "ambiguous"
    assert len(result.candidates) == 2


@pytest.mark.parametrize("field, value, code", [
    ("area", "South", "AREA_CONFLICT"),
    ("work_type", "concrete_pour", "WORK_TYPE_CONFLICT"),
    ("asset_tags", ["unrelated"], "TAG_CONFLICT"),
    ("is_leaf", False, "SUMMARY_ACTIVITY"),
])
def test_contradictory_candidates_are_excluded_and_abstained(field, value, code):
    candidate_item = candidate("a", **{field: value})
    seen = {}

    def call(**kwargs):
        seen.update(kwargs)
        return model_result(None, mapping_state="unmatched", reason_codes=[code], evidence_fragment_ids=[])

    result = select_candidate(observation(), [candidate_item], [fragment()], model_call=call, project_id="project-1")

    assert result.candidate_id is None
    assert result.mapping_state.value == "unmatched"
    assert seen == {}


def test_wrong_project_is_excluded_and_abstained():
    result = select_candidate(
        observation(), [candidate("a", project_id="project-2")], [fragment()],
        model_call=lambda **kwargs: pytest.fail("model must not be called"), project_id="project-1",
    )

    assert result.candidate_id is None
    assert result.mapping_state.value == "unmatched"


def test_unknown_model_id_is_rejected():
    with pytest.raises(SelectionValidationError, match="eligible supplied ID"):
        select_candidate(
            observation(), [candidate("a")], [fragment()],
            model_call=lambda **kwargs: model_result("unknown"), project_id="project-1",
        )


def test_unknown_evidence_is_rejected():
    with pytest.raises(SelectionValidationError, match="evidence_fragment_id"):
        select_candidate(
            observation(), [candidate("a")], [fragment()],
            model_call=lambda **kwargs: model_result("a", evidence_fragment_ids=["missing"]), project_id="project-1",
        )


def test_selection_without_evidence_is_rejected():
    with pytest.raises(SelectionValidationError, match="source evidence"):
        select_candidate(
            observation(), [candidate("a")], [],
            model_call=lambda **kwargs: model_result("a", evidence_fragment_ids=[]), project_id="project-1",
        )
