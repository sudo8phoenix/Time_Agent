import pytest
from app.schemas.observation import Observation
from app.progress.effects import build_effects


def observation(event_type="actual_start", effects=None):
    return Observation.model_validate(dict(
        discipline="civil", work_type="excavation", event_type=event_type,
        observed_status="in_progress", area=None, asset_tags=["F-01"],
        explicit_activity_id=None, work_date="2026-10-09", date_basis="report_context",
        quantity=None, quantity_kind="none", unit=None, raw_unit=None,
        reported_percent=None, actual_start=None, actual_finish=None, blocker=None,
        summary="Started excavation at F-01 at 08:30",
        evidence=[{"fields": ["event_type"], "fragment_id": "f1", "quote": "Started excavation"}],
        warnings=[], lifecycle_effects=effects or []))


def test_quantity_free_start_effect_preserves_precision():
    obs = observation(effects=[{
        "kind": "actual_start", "scope": "whole_activity",
        "endpoint": {"local_date": "2026-10-09", "local_time": "08:30:00",
                     "precision": "minute", "basis": "report_context",
                     "raw_expression": "at 08:30"},
        "evidence": [{"fields": ["kind", "endpoint"], "fragment_id": "f1",
                      "quote": "Started excavation at F-01 at 08:30"}]}])
    result = build_effects(obs)
    assert result["event_type"] == "actual_start"
    assert result["endpoint"]["local_time"] == "08:30:00"
    assert "quantity" not in result


def test_unresolved_start_produces_no_effect():
    assert build_effects(observation()) == {}


def test_old_graph_observation_parses_without_new_field():
    from app.schemas.observation import Observation
    old = observation(event_type="actual_progress").model_dump(mode="json")
    old.pop("lifecycle_effects")
    assert Observation.model_validate(old).lifecycle_effects == []


def test_extractor_rejects_untrusted_context_and_keeps_two_atomic_events():
    from datetime import date
    from app.llm.extract import BatchInput, FragmentInput, extract_batch
    quote = "Started excavation at F-01 at 08:30. Finished excavation at F-01 at 17:00."
    fragment = FragmentInput("f1", "p1", quote)
    start = observation(effects=[{
        "kind": "actual_start", "scope": "whole_activity",
        "endpoint": {"local_date": "2026-10-09", "local_time": "08:30:00",
                     "precision": "minute", "basis": "report_context", "raw_expression": "at 08:30"},
        "evidence": [{"fields": ["kind"], "fragment_id": "f1", "quote": "Started excavation at F-01 at 08:30"}]}]).model_dump(mode="json")
    start["evidence"][0]["quote"] = "Started excavation at F-01 at 08:30"
    finish = observation(event_type="actual_finish", effects=[{
        "kind": "actual_finish", "scope": "whole_activity",
        "endpoint": {"local_date": "2026-10-09", "local_time": "17:00:00",
                     "precision": "minute", "basis": "report_context", "raw_expression": "at 17:00"},
        "evidence": [{"fields": ["kind"], "fragment_id": "f1", "quote": "Finished excavation at F-01 at 17:00"}]}]).model_dump(mode="json")
    finish["evidence"][0]["quote"] = "Finished excavation at F-01 at 17:00"
    untrusted = extract_batch(BatchInput("b", (fragment,), date(2026, 10, 9), False),
                              lambda **_: {"observations": [start, finish]})
    assert not untrusted.observations and len(untrusted.errors) == 2
    trusted = extract_batch(BatchInput("b", (fragment,), date(2026, 10, 9), True),
                            lambda **_: {"observations": [start, finish]})
    assert len(trusted.observations) == 2
    assert [build_effects(o)["event_type"] for o in trusted.observations] == ["actual_start", "actual_finish"]


def test_source_grounded_clock_zone_repair_only():
    from datetime import date
    from app.llm.extract import BatchInput, FragmentInput, extract_batch, ExtractionError
    source = "Started excavation at F-01 at 08:30."
    raw = observation(effects=[{
        "kind": "actual_start", "scope": "whole_activity",
        "endpoint": {"local_date": "2026-10-09", "local_time": "08:30:00",
                     "precision": "minute", "basis": "report_context", "raw_expression": "at 08:30"},
        "evidence": [{"fields": ["kind"], "fragment_id": "f1", "quote": source}]}]).model_dump(mode="json")
    raw["evidence"][0]["quote"] = source
    raw["lifecycle_effects"][0]["endpoint"]["local_time"] = "08:30:00Z"
    batch = BatchInput("b", (FragmentInput("f1", "p1", source),), date(2026, 10, 9), True)
    result = extract_batch(batch, lambda **_: {"observations": [raw]})
    assert result.observations[0].lifecycle_effects[0].endpoint.local_time.isoformat() == "08:30:00"
    assert result.observations[0].warnings
    raw["lifecycle_effects"][0]["endpoint"]["local_time"] = "09:30:00Z"
    with pytest.raises(ExtractionError):
        extract_batch(batch, lambda **_: {"observations": [raw]})


def test_both_worker_modes_share_lifecycle_builder():
    from app.jobs.pipeline import _effects as legacy_effects
    from app.agent.runtime import _effects as graph_effects
    obs = observation(effects=[{
        "kind": "actual_start", "scope": "whole_activity",
        "endpoint": {"local_date": "2026-10-09", "local_time": "08:30:00",
                     "precision": "minute", "basis": "report_context", "raw_expression": "at 08:30"},
        "evidence": [{"fields": ["kind"], "fragment_id": "f1",
                      "quote": "Started excavation at F-01 at 08:30"}]}])
    assert legacy_effects(obs) == graph_effects(obs) == build_effects(obs)


def test_source_stated_clock_repairs_incomplete_minute_endpoint():
    from datetime import date
    from app.llm.extract import BatchInput, FragmentInput, extract_batch, ExtractionError
    source = "Started excavation at F-01 at 08:30."
    raw = observation(effects=[{
        "kind": "actual_start", "scope": "whole_activity",
        "endpoint": {"local_date": "2026-10-09", "local_time": "08:30:00",
                     "precision": "minute", "basis": "report_context", "raw_expression": "at 08:30"},
        "evidence": [{"fields": ["endpoint"], "fragment_id": "f1", "quote": source}]}]).model_dump(mode="json")
    raw["evidence"][0]["quote"] = source
    endpoint = raw["lifecycle_effects"][0]["endpoint"]
    endpoint.pop("local_time")
    batch = BatchInput("b", (FragmentInput("f1", "line 1", source),), date(2026, 10, 9), True)
    accepted = extract_batch(batch, lambda **_: {"observations": [raw]})
    assert accepted.observations[0].lifecycle_effects[0].endpoint.local_time.hour == 8
    assert accepted.observations[0].warnings
    endpoint["raw_expression"] = "at 09:30"
    with pytest.raises(ExtractionError):
        extract_batch(batch, lambda **_: {"observations": [raw]})


def test_quoted_clock_upgrades_model_date_only_endpoint_without_fabricating_other_times():
    from datetime import date
    from app.llm.extract import BatchInput, FragmentInput, extract_batch
    source = "Started excavation at F-01 at 08:30."
    raw = observation(effects=[{
        "kind": "actual_start", "scope": "whole_activity",
        "endpoint": {"local_date": "2026-10-09", "local_time": None,
                     "precision": "date", "basis": "report_context", "raw_expression": "at 08:30"},
        "evidence": [{"fields": ["endpoint"], "fragment_id": "f1", "quote": source}]}]).model_dump(mode="json")
    raw["evidence"][0]["quote"] = source
    batch = BatchInput("b", (FragmentInput("f1", "line 1", source),), date(2026, 10, 9), True)
    result = extract_batch(batch, lambda **_: {"observations": [raw]})
    endpoint = result.observations[0].lifecycle_effects[0].endpoint
    assert endpoint.local_time.hour == 8 and endpoint.precision.value == "minute"
    raw["lifecycle_effects"][0]["endpoint"]["raw_expression"] = "finished"
    result = extract_batch(batch, lambda **_: {"observations": [raw]})
    assert result.observations[0].lifecycle_effects[0].endpoint.local_time is None
