"""Measure full-schedule traversal at audited Cambridge sizes; injected model only.

No label or model accuracy claim. Every batch returns a known synthetic target
when present, allowing measurement of candidate retention and model-call cost.
"""
import json
from pathlib import Path
from time import perf_counter
from app.agent.schedule_decision import shortlist_activities


def run(size):
    rows = [{"id": f"fixture-{i}", "external_id": f"TASK-{i}", "name": "Synthetic excavation",
             "work_type": "excavation", "area": None, "is_leaf": True} for i in range(size)]
    targets = {rows[0]["id"], rows[size // 2]["id"], rows[-1]["id"]}
    calls = 0
    def model(**kwargs):
        nonlocal calls
        calls += 1
        return {"candidate_ids": [r["id"] for r in kwargs["user"]["schedule_activities"] if r["id"] in targets]}
    started = perf_counter()
    candidates = shortlist_activities({"summary": "Synthetic target assertion"}, "fixture", rows, model_call=model)
    hits = targets & {str(c.candidate_id) for c in candidates}
    return {"activities": size, "injected_model_calls": calls, "fixture_target_count": len(targets),
            "retained_target_count": len(hits), "fixture_recall": len(hits) / len(targets),
            "python_seconds": round(perf_counter() - started, 4)}


if __name__ == "__main__":
    catalog = json.loads(Path("../data/schedule-audit-2026-10-09/cambridge-project-catalog.json").read_text())
    def counts(value):
        if isinstance(value, dict):
            if isinstance(value.get("activities"), int):
                yield value["activities"]
            for child in value.values():
                yield from counts(child)
        elif isinstance(value, list):
            for child in value:
                yield from counts(child)
    sizes = sorted(counts(catalog))
    result = {"status": "verified_fixture", "model": "injected exact-ID fixture; no live model",
              "limitations": "Recall is traversal retention only, not semantic model accuracy. Python timing excludes inference. No retrieval pruning introduced.",
              "cases": [run(size) for size in sorted({140, sizes[len(sizes)//2], sizes[-1]})]}
    Path("docs/validation/m01-matching-scale-fixture.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
