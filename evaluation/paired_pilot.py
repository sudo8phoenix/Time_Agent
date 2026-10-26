"""Fixed four-call synthetic development pilot; production admission stays enabled.

Preparation is offline by default. --execute uses slot 2 for both models. It does
not alter runtime settings or durable jobs. Outputs are development evidence only.
"""
from datetime import date
from hashlib import sha256
import argparse
import json
from pathlib import Path
from pydantic import ValidationError
import time

from app.llm.extract import FragmentInput, extract_fragments, extraction_schema
from app.llm.groq import GroqChatAdapter
from app.llm.hosted import request
from app.llm.metrics import capture_provider_metrics
from app.llm.openrouter import _matches_schema
from app.schemas.observation import ObservationBatch
from app.prompts.extraction_v1 import PROMPT_VERSION, get_extraction_prompt
from evaluation.strict_schema import build_wire_schema

MODELS = ("openai/gpt-oss-20b", "openai/gpt-oss-120b")
PRICES = {MODELS[0]: (.075, .30), MODELS[1]: (.15, .60)}
PRICE_SOURCE = "https://console.groq.com/docs/models"
FIXTURE = Path(__file__).parent / "fixtures/paired-pilot-v1/inputs.json"


# Evaluation-only instruction: does not register or change production prompts.
CLAUSE_COVERAGE_SUFFIX = """
Preserve explicit non-performance as its own atomic no_work event even when the
same work scope also has a future plan. A future planned_work observation never
replaces a statement that work did not occur today. Keep independent time-specific
assertions separate, each with its own source evidence and date. Do not invent
no_work merely because no quantity is stated.
"""


QUANTITY_SUFFIX = """
Wire-field contract: quantity, unit and quantity_kind describe performed/installed
progress only. For planned_work, material_delivery, blocker and no_work, always
write quantity=null, unit=null, quantity_kind=none, even when the source states an
amount. Preserve that source amount in summary. For actual_progress retain an
explicit measured amount and its stated unit; do not clear actual quantities.
"""
BROAD_FIXTURE = FIXTURE.parent.parent / "broad-pilot-v1/inputs.json"
EXPLICIT_FIXTURE = FIXTURE.parent.parent / "explicit-location-v1/inputs.json"
COMPARISONS = ("model", "clause-coverage", "nonactual-quantity", "broad-candidate", "strict-schema")


class BudgetStop(RuntimeError):
    pass


class Budget:
    def __init__(self, *, clock=time.monotonic):
        self.clock = clock
        self.started = clock()
        self.calls = self.tokens = 0
        self.reserved_usd = 0.0

    def reserve(self, payload):
        # Byte count plus generous framing allowance is a conservative token
        # reservation, not measured usage. Schema/messages are included.
        input_bound = len(json.dumps(payload, ensure_ascii=False).encode()) + 1024
        output_bound = payload["max_completion_tokens"]
        model = payload["model"]
        if model not in PRICES or output_bound > 1536 or output_bound <= 0:
            raise BudgetStop("Unsupported model/output budget")
        cost = (input_bound * PRICES[model][0] + output_bound * PRICES[model][1]) / 1e6
        remaining = 360 - (self.clock() - self.started)
        if (self.calls >= 4 or self.tokens + input_bound + output_bound > 160000 or
                self.reserved_usd + cost > .05 or remaining <= 1):
            raise BudgetStop("Fixed experiment budget reached")
        self.calls += 1
        self.tokens += input_bound + output_bound
        self.reserved_usd += cost
        return min(60, remaining)


def append(path, row):
    with path.open("a") as stream:
        stream.write(json.dumps(row, default=str) + "\n")


def run(output, *, execute=False, comparison="model"):
    if comparison not in COMPARISONS:
        raise ValueError("Unknown comparison")
    output.mkdir(parents=True, exist_ok=False)
    fixture = (BROAD_FIXTURE if comparison == "broad-candidate" else
               EXPLICIT_FIXTURE if comparison == "strict-schema" else FIXTURE)
    cases = json.loads(fixture.read_text())
    # Counterbalance paired arms; broad slice is a single-candidate diagnostic.
    if comparison == "model":
        arms = [(model, model, "") for model in MODELS]
    elif comparison == "clause-coverage":
        arms = [("baseline", MODELS[0], ""), ("clause-coverage", MODELS[0], CLAUSE_COVERAGE_SUFFIX)]
    elif comparison == "nonactual-quantity":
        arms = [("clause-coverage", MODELS[0], CLAUSE_COVERAGE_SUFFIX),
                ("coverage-and-quantity", MODELS[0], CLAUSE_COVERAGE_SUFFIX + QUANTITY_SUFFIX)]
    elif comparison == "strict-schema":
        arms = [("best-effort", MODELS[0], CLAUSE_COVERAGE_SUFFIX + QUANTITY_SUFFIX),
                ("strict", MODELS[0], CLAUSE_COVERAGE_SUFFIX + QUANTITY_SUFFIX)]
    else:
        arms = [("coverage-and-quantity", MODELS[0], CLAUSE_COVERAGE_SUFFIX + QUANTITY_SUFFIX)]
    if len(cases) * len(arms) != 4:
        raise ValueError("Experiments require exactly four scheduled calls")
    schedule = [(case, arm, model, suffix) for index, case in enumerate(cases)
                for arm, model, suffix in (arms if index % 2 == 0 else list(reversed(arms)))]
    _, base_prompt = get_extraction_prompt(PROMPT_VERSION)
    wire_schema, schema_changes = (build_wire_schema(extraction_schema()) if comparison == "strict-schema"
                                   else (extraction_schema(), []))
    source = [Path(__file__), fixture, Path("backend/app/llm/extract.py"),
              Path("backend/app/llm/groq.py"), Path("backend/app/llm/openrouter.py"),
              Path("backend/app/prompts/extraction_v1.py"),
              Path("evaluation/score_paired_pilot.py"), Path("evaluation/strict_schema.py"),
              Path("backend/app/schemas/observation.py"), Path("backend/app/schemas/common.py"),
              Path("backend/app/schemas/events.py")]
    config = {"scope": "synthetic AI-authored development diagnostic; not holdout or acceptance",
              "prompt_version": PROMPT_VERSION, "key_slot": 2,
              "account_scope": "owner-confirmed independent organization; shared admission retained",
              "comparison": comparison,
              "annotation_contract_sha256": (sha256(Path("evaluation/contracts/development-annotation-contract.md").read_bytes()).hexdigest()
                                             if comparison == "strict-schema" else None),
              "schema_sha256": sha256(json.dumps(extraction_schema(), sort_keys=True).encode()).hexdigest(),
              "wire_schema_sha256": sha256(json.dumps(wire_schema, sort_keys=True).encode()).hexdigest(),
              "wire_schema_changes": schema_changes,
              "primary_comparison": ("strict flag only; identical core wire schema and prompt" if comparison == "strict-schema" else comparison),
              "schedule": [{"case_id": c["case_id"], "arm": arm, "model": model,
                            "strict": comparison == "strict-schema" and arm == "strict",
                            "effective_system_sha256": sha256((base_prompt + suffix).encode()).hexdigest()}
                           for c, arm, model, suffix in schedule],
              "arm_suffixes": {arm: suffix for arm, _, suffix in arms},
              "candidate_suffix": CLAUSE_COVERAGE_SUFFIX if comparison == "clause-coverage" else None,
              "fixture_path": str(fixture),
              "label_sha256": sha256(fixture.with_name("labels.json").read_bytes()).hexdigest(),
              "budget": {"calls": 4, "reserved_tokens": 160000, "list_price_usd": .05,
                         "wall_seconds": 360, "request_seconds": 60, "output_tokens_per_call": 1536},
              "prices_per_million": PRICES, "price_source": PRICE_SOURCE,
              "price_checked": "2026-10-20", "transport_retries": 0, "repair_calls": 0,
              "source_sha256": {str(p): sha256(p.read_bytes()).hexdigest() for p in source},
              "executed": execute}
    (output / "wire-schema.json").write_text(json.dumps(wire_schema, indent=2) + "\n")
    (output / "config.json").write_text(json.dumps(config, indent=2) + "\n")
    if not execute:
        return config
    from app.settings import Settings
    settings = Settings()
    key = settings.groq_api_key_2
    if not key:
        raise BudgetStop("Slot 2 is unavailable")
    budget = Budget()
    rows = []
    for case, arm, model, suffix in schedule:
        row = {"case_id": case["case_id"], "arm": arm, "requested_model": model, "state": "failed"}
        began = time.monotonic()
        metrics = {}
        response_checks = {}
        stop = False

        def transport(method, url, payload, timeout, headers):
            if comparison == "strict-schema":
                payload["response_format"]["json_schema"]["strict"] = arm == "strict"
            allowed_timeout = budget.reserve(payload)
            status, body = request("groq", method, url, payload, min(timeout, allowed_timeout), headers)
            # Retain only numerical usage and identity, never headers or reasoning.
            append(output / "usage.jsonl", {"case_id": case["case_id"], "arm": arm, "model": model,
                   "status": status, "returned_model": body.get("model"),
                   "usage": {k: v for k, v in body.get("usage", {}).items()
                             if isinstance(v, (int, float)) and not isinstance(v, bool)}})
            if status >= 400:
                raise BudgetStop("Provider error; stop without retries")
            if body.get("model") != model:
                raise BudgetStop("Unexpected returned model")
            # Synthetic evaluation evidence is captured before local schema validation.
            try:
                value = json.loads(body["choices"][0]["message"]["content"])
            except (KeyError, IndexError, TypeError, ValueError):
                value = None
            choice = body.get("choices", [{}])[0] if body.get("choices") else {}
            response_checks.update(response_complete=choice.get("finish_reason") == "stop",
                                   refusal_present=bool(choice.get("message", {}).get("refusal")),
                                   parsed_json_object=isinstance(value, dict),
                                   wire_schema_valid=isinstance(value, dict) and _matches_schema(value, wire_schema))
            try:
                ObservationBatch.model_validate(value)
                response_checks["raw_domain_schema_valid"] = True
            except ValidationError as error:
                response_checks["raw_domain_schema_valid"] = False
                response_checks["domain_schema_errors"] = error.errors(
                    include_input=False, include_context=False, include_url=False)
            if isinstance(value, dict):
                append(output / "model-outputs.jsonl", {"case_id": case["case_id"],
                       "arm": arm, "model": model, "value": value})
            if response_checks["refusal_present"]:
                raise BudgetStop("Provider refusal; stop without retries")
            return status, body

        adapter = GroqChatAdapter(model, bearer_token=key.get_secret_value(),
                                  timeout=60, max_retries=0, transport=transport)

        def call(**kwargs):
            kwargs["system"] += suffix
            # The adapter defaults to 8112 output tokens; this pilot reserves
            # at most 1536 per call before any provider request is made.
            kwargs["settings"] = {**kwargs.get("settings", {}), "num_predict": 1536}
            if comparison == "strict-schema":
                kwargs["schema"] = wire_schema
            return adapter.chat(**kwargs)

        try:
            with capture_provider_metrics() as metrics:
                results = extract_fragments(
                    [FragmentInput(case["case_id"], "synthetic:1", case["text"], 1)], call,
                    report_date=date.fromisoformat(case["report_date"]), report_date_trusted=True,
                    prompt_version=PROMPT_VERSION)
            errors = [e for result in results for e in result.errors]
            row.update(state="completed" if not errors else "invalid",
                       observations=[o.model_dump(mode="json") for r in results for o in r.observations],
                       validation_errors=errors)
        except Exception as error:
            row["error_type"] = type(error).__name__
            row["error_code"] = getattr(error, "code", "PILOT_STOP")
            if isinstance(error.__cause__, ValidationError):
                row["schema_errors"] = error.__cause__.errors(
                    include_input=False, include_context=False, include_url=False)
            stop = True
        row.update(elapsed_ms=round((time.monotonic() - began) * 1000), provider_metrics=metrics,
                   response_checks=response_checks)
        append(output / "predictions.jsonl", row)
        rows.append(row)
        print(json.dumps({k: row[k] for k in ("case_id", "arm", "requested_model", "state", "elapsed_ms")}), flush=True)
        if stop or row["state"] != "completed":
            break
    summary = {"scheduled": 4, "attempted": len(rows), "completed": sum(r["state"] == "completed" for r in rows),
               "reserved_calls": budget.calls, "reserved_tokens": budget.tokens,
               "reserved_list_price_usd": budget.reserved_usd,
               "elapsed_seconds": round(time.monotonic() - budget.started, 3),
               "quality_decision": "unscored; no model ranking or release acceptance"}
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    (output / "capture-manifest.json").write_text(json.dumps({p.name: sha256(p.read_bytes()).hexdigest()
        for p in output.iterdir() if p.is_file()}, indent=2) + "\n")
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--comparison", choices=COMPARISONS, default="model")
    args = parser.parse_args()
    print(json.dumps(run(args.output_dir, execute=args.execute, comparison=args.comparison), indent=2))


if __name__ == "__main__":
    main()
