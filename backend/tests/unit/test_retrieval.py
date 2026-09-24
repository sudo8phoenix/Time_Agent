"""W-10 deterministic retrieval coverage and seed fixture measurement."""
import csv
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.models import ActivityEmbedding
from app.retrieval.index import compose_description, cache_key, retrieve_candidates, recall_at_8
from app.retrieval.rebuild import ensure_activity_embeddings, rebuild_index

ROOT = Path(__file__).resolve().parents[3]
SCHEDULE = ROOT / "data/synthetic/schedules/demo-utility-01.csv"
LABELS = ROOT / "data/synthetic/labels/seed-labels.jsonl"


def _activities():
    with SCHEDULE.open(newline="") as fh:
        rows = list(csv.DictReader(fh))
    for row in rows:
        row["id"] = row["activity_id"]
        row["external_id"] = row["activity_id"]
        row["name"] = row["activity_name"]
        row["wbs"] = row["wbs_path"]
        row["is_leaf"] = row["is_leaf"].lower() == "true"
    return rows


def test_description_is_deterministic_bounded_and_identity_first():
    activity = {"name": "Name", "discipline": "piping", "work_type": "welding", "area": "A",
                "asset_tags": "TAG", "wbs_path": "WBS", "aliases": "alias"}
    assert compose_description(activity) == "Name | piping | welding | A | TAG | WBS | alias"
    assert compose_description(activity, max_chars=12) == "Name | pipin"
    assert compose_description(activity) == compose_description(dict(activity))


def test_metadata_exclusions_and_explicit_external_id_handling():
    activities = _activities()
    summary = dict(activities[0], id="summary", activity_id="summary", external_id="SUMMARY", is_leaf=False)
    result = retrieve_candidates({"summary": "erect spools", "area": "AREA-A", "asset_tags": ["24-XX"]}, "v1", activities + [summary])
    assert "summary" in result.excluded_activity_ids
    assert all(c.is_leaf for c in result.candidates)
    exact = retrieve_candidates({"summary": "weld joints", "explicit_activity_id": "PIP-A-WELD-024"}, "v1", activities)
    assert exact.candidates and exact.candidates[0].external_id == "PIP-A-WELD-024"
    assert any(c.external_id != "PIP-A-WELD-024" for c in exact.candidates)
    assert exact.candidates[0].is_leaf
    assert exact.candidates[0].lexical_rank is not None or exact.candidates[0].embedding_rank is not None
    missing = retrieve_candidates({"summary": "anything", "explicit_activity_id": "NO-SUCH-ID"}, "v1", activities)
    assert all(c.external_id != "NO-SUCH-ID" for c in missing.candidates)


def test_exact_id_without_retrieval_rank_is_promoted_and_keeps_fused_fillers():
    activities = [{"id": str(i), "external_id": f"A-{i:02d}", "name": "target work",
                   "is_leaf": True, "area": "A", "asset_tags": "", "work_type": "work",
                   "discipline": "x", "aliases": ""} for i in range(21)]
    activities.append({"id": "exact", "external_id": "EXACT-01", "name": "unrelated",
                       "is_leaf": True, "area": "A", "asset_tags": "", "work_type": "work",
                       "discipline": "x", "aliases": ""})
    result = retrieve_candidates({"summary": "target work", "area": "A",
                                  "explicit_activity_id": "EXACT-01"}, "v1", activities,
                                 embed=lambda text: [1.0, 0.0] if "target work" in text else [0.0, 1.0])
    assert len(result.candidates) == 8
    exact = result.candidates[0]
    assert exact.external_id == "EXACT-01"
    assert exact.lexical_rank is None and exact.embedding_rank is None
    assert exact.lexical_score == 0.0 and exact.embedding_score is None and exact.rrf_score == 0.0
    assert any(candidate.external_id != "EXACT-01" for candidate in result.candidates[1:])


def test_area_and_tag_conflicts_are_excluded():
    activities = _activities()
    result = retrieve_candidates({"summary": "erect spools", "area": "AREA-A", "asset_tags": ["24-XX"]}, "v1", activities)
    ids = {c.external_id for c in result.candidates}
    assert "PIP-B-ERECT-024" not in ids
    assert any("PIP-B-ERECT-024" in x for x in result.excluded_activity_ids) or any("PIP-B-ERECT-024" in x for x in result.conflicts)


def test_rrf_rank_ordering_and_max_eight():
    activities = [{"id": str(i), "external_id": f"A-{i}", "name": f"candidate {i}", "is_leaf": True,
                   "area": "A", "asset_tags": "", "work_type": "work", "discipline": "x", "aliases": ""} for i in range(12)]
    vectors = {"candidate 0": [1, 0], "candidate 1": [.8, .6]}
    result = retrieve_candidates({"summary": "candidate 0", "area": "A"}, "v1", activities,
                                 embed=lambda text: vectors.get(text, [0, 1]))
    assert len(result.candidates) == 8
    assert result.candidates[0].external_id == "A-0"
    assert all(c.rrf_score >= result.candidates[-1].rrf_score for c in result.candidates)
    assert all(c.lexical_rank or c.embedding_rank for c in result.candidates)


def test_empty_retrieval_and_cache_changes_on_relevant_inputs():
    activities = _activities()
    empty = retrieve_candidates({"summary": "", "area": ""}, "v1", [])
    assert empty.candidates == []
    base = cache_key("v1", activities, "model-a", "text-v1")
    assert base != cache_key("v2", activities, "model-a", "text-v1")
    assert base != cache_key("v1", activities, "model-b", "text-v1")
    assert base != cache_key("v1", activities, "model-a", "text-v2")
    changed = [dict(activities[0], aliases="new alias")] + activities[1:]
    assert base != cache_key("v1", changed, "model-a", "text-v1")
    assert rebuild_index(activities, "v1", model_version="model-a")["cache_key"] == base


def test_local_embeddings_are_persisted_reused_and_refreshed_by_description():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    activities = [
        SimpleNamespace(id=uuid4(), name="Install spool", discipline="piping", work_type="erection",
                        area="A", asset_tags="24-XX", wbs="PIP.1", aliases="spool install"),
        SimpleNamespace(id=uuid4(), name="Weld joint", discipline="piping", work_type="welding",
                        area="A", asset_tags="24-XX", wbs="PIP.2", aliases="field weld"),
    ]
    calls = []

    def embed(text):
        calls.append(text)
        return [float(len(text)), 1.0]

    with Session(engine) as db:
        first = ensure_activity_embeddings(db, activities, embed, "mini-v1")
        db.commit()
        assert len(first) == 2 and len(calls) == 2
        reused = ensure_activity_embeddings(db, activities, embed, "mini-v1")
        assert reused == first and len(calls) == 2
        activities[0].aliases = "revised spool alias"
        refreshed = ensure_activity_embeddings(db, activities, embed, "mini-v1")
        db.commit()
        assert len(calls) == 3 and refreshed[str(activities[0].id)] != first[str(activities[0].id)]
        assert db.query(ActivityEmbedding).count() == 2
        ensure_activity_embeddings(db, activities, embed, "mini-v2")
        assert db.query(ActivityEmbedding).count() == 4


def test_retrieval_uses_supplied_persisted_vectors_without_reembedding_activities():
    activities = [
        {"id": "one", "external_id": "ONE", "name": "alpha", "is_leaf": True,
         "area": "A", "asset_tags": "", "work_type": "work", "discipline": "x", "aliases": ""},
        {"id": "two", "external_id": "TWO", "name": "beta", "is_leaf": True,
         "area": "A", "asset_tags": "", "work_type": "work", "discipline": "x", "aliases": ""},
    ]
    calls = []

    def query_only_embed(text):
        calls.append(text)
        if text != "find alpha":
            raise AssertionError("activity descriptions must come from persisted vectors")
        return [1.0, 0.0]

    result = retrieve_candidates(
        {"summary": "find alpha", "area": "A"}, "v1", activities,
        embed=query_only_embed, activity_embeddings={"one": [1.0, 0.0], "two": [0.0, 1.0]},
    )
    assert result.candidates[0].external_id == "ONE"
    assert calls == ["find alpha"]


def test_seed_fixture_recall_at_8_is_deterministic_and_fixture_only(tmp_path):
    activities = _activities()
    by_external = {a["external_id"]: a for a in activities}
    results, expected = [], []
    for line in LABELS.open():
        label = json.loads(line)
        ids = label.get("expected_activity_ids", [])
        if label.get("expected_mapping_state") != "suggested" or not ids or ids[0] not in by_external:
            continue
        activity = by_external[ids[0]]
        observation = {"summary": activity["name"], "area": activity["area"],
                       "asset_tags": [activity["asset_tags"]], "work_type": activity["work_type"],
                       "discipline": activity["discipline"]}
        results.append(retrieve_candidates(observation, "demo-utility-01-v1", activities))
        expected.append(ids[0])
    value = recall_at_8(results, expected)
    assert expected and value == recall_at_8(results, expected)
    evidence = {"denominator": len(expected), "recall_at_8": value,
                "label": "fixture retrieval only", "schedule_path": str(SCHEDULE),
                "labels_path": str(LABELS), "limitations": ["synthetic seed labels; no model benchmark"]}
    (ROOT / "evaluation/results").mkdir(exist_ok=True)
    (ROOT / "evaluation/results/retrieval-seed-fixture.json").write_text(json.dumps(evidence, indent=2) + "\n")
