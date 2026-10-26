"""Generate the auditable descriptive report from the saved live matrix; no API calls."""
from pathlib import Path
from hashlib import sha256
import json
import statistics

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).parent
NAMES = ['qwen', 'gpt120', 'gpt20', 'deepseek']
EXPECTED = {
    'qwen': ['01', '03', '02', '04', '05', '01'],
    'gpt120': ['01', '03', '02', '02', '04', '05', '05', '01'],
    'gpt20': ['01', '03', '02', '04', '05', '01'],
    'deepseek': ['01', '01', '03', '03', '02', '04', '04', '05', '01', None],
}
# Manual source review: eight core facts, then an explicitly subjective defect count.
CORE = {'qwen': 7, 'gpt120': 8, 'gpt20': 8, 'deepseek': 8}
ISSUES = {'qwen': 1, 'gpt120': 1, 'gpt20': 1, 'deepseek': 2}


def main():
    p = json.loads((HERE / 'four-model-matrix.json').read_text())
    for extractor in NAMES:
        observations = p['extraction'][extractor]['observations']
        assert len(observations) == len(EXPECTED[extractor]), 'Extraction changed; review scoring'
        for selector in NAMES:
            rows = p['selection'].get(f'{extractor}::{selector}', [])
            assert sorted(row['observation'] for row in rows) == list(range(1, len(observations) + 1)), (
                f'Incomplete or duplicate pair: {extractor}::{selector}')
    assert set(p['planner_retest_fenced_json_v1']['deepseek']) == {'intake', 'analysis', 'review'}
    planners = {**p['planner'], **p.get('planner_retest_fenced_json_v1', {})}
    lines = ['# Four-model role comparison — 26 October 2026', '',
        'GPT-OSS 20B extraction is the most compact candidate that preserves all eight core facts in this one report. Qwen is the fastest observed legal planner. Under the disclosed compactness-first rubric, Qwen planning / GPT-OSS 20B extraction / Qwen selection ranks first; GPT-OSS 120B selection is effectively tied on elapsed time and handles DeepSeek’s extra records better. DeepSeek and GPT-OSS 120B selection each scored 30/30 across all extractor outputs; Qwen and GPT-OSS 20B each scored 29/30. DeepSeek extraction preserves more inspection and blocker detail, at the cost of ten selection calls rather than GPT20’s six. These are trial recommendations, not a production acceptance or a universal model ranking.', '',
        '## Scope and reproducibility', '',
        'Four planners × four extractors × four selectors produce 64 **composed** assignments. We measured three legal planner transitions per model, one extraction per model and every extractor–selector pair. We did not execute 64 independent graphs. Planner decisions merely confirm one supplied legal next stage and do not inspect report text. The fixed five-row candidate pool includes explicit source activity identifiers, making this an easy mapping task; it does not measure retrieval quality.', '',
        'The source is `artifacts/gonka-model-comparison/input.txt`; schedule: `data/review/gt10-five-entry/schedule.csv`. Full validated observations, per-observation selection results, errors, timestamps and safe usage metadata are in `artifacts/gonka-model-comparison/four-model-matrix.json`. Selection explanations and reason codes were not retained by this runner; the saved selection outputs are activity, state, event/quantity, error and elapsed time. Failed raw generations were not retained; an invalid-JSON category does not establish whether syntax or local schema validation failed. Earlier six-event DeepSeek extraction and MiniMax trials are separate evidence.', '',
        'PostgreSQL `progress_test` and Docker were unavailable during the original setup. No durable graph, retrieval, persistence, approval, ledger update or PMIS delivery was tested. No active model assignment or private key was changed. Gonka transport admission is supported, but its queue pre-claim check and numeric provider-metrics collection are not yet covered; those currently cover Groq/OpenRouter. Standalone call diagnostics here are separate from durable metrics.', '',
        'Resume: `.venv/bin/python artifacts/gonka-model-comparison/four_model_matrix.py --retest-deepseek-planner --retry-transport-failures`. Completed work is skipped; the versioned planner retest preserves the initial results. Only explicit transport-failure rows are archived and retried with the flag; schema failures remain in the matrix. Calls retain all attempts and interruptions. Rebuild this report with `.venv/bin/python artifacts/gonka-model-comparison/summarize_matrix.py`.', '',
        'Groq uses planner slot 1 and worker slot 2, with account scopes disabled. Shared header-aware admission and the 10.5-second Gonka gate apply. Calls use temperature zero, zero automatic retries and no fallback. Planner output budget is 128; extraction requests 4096; compact selection requests 768. Groq GPT-OSS reasoning is low; no explicit Gonka reasoning switch is sent. Gonka accepts a complete JSON fence and still enforces the requested schema. Its 4096 cap does not increase the planner’s explicit 128-token request.', '',
        'Model identities: ' + '; '.join(f"`{n}` = `{p["models"][n][0]}` / `{p["models"][n][1]}`" for n in NAMES) + '.', '', '## Planner results', '',
        '| Model | Legal stages | Intake / analysis / review (seconds) | Trial |',
        '|---|---:|---|---|']
    for n in NAMES:
        stages = planners[n]
        count = sum('action' in stages[s] for s in ('intake', 'analysis', 'review'))
        lines.append(f"| {n} | {count}/3 | " + ' / '.join(str(stages[s]['elapsed_seconds']) for s in ('intake', 'analysis', 'review')) + f" | {'Updated fence adapter' if n == 'deepseek' else 'Original matrix'} |")
    lines += ['', 'DeepSeek’s initial planner trial passed 0/3 (two invalid JSON, one incomplete response). The updated-adapter retest is independently retained under `planner_retest_fenced_json_v1`; its failures must not be replaced by the successful extraction result. A planner failure makes the composed assignment unusable under this model-assisted contract. A larger planner budget would be a separate experiment, not a correction to this result.', '',
        '## Extraction semantics', '',
        'Eight core checks: (1) exactly 300 kg installed column reinforcement as a delta, (2) exactly 60 m² installed shuttering as a delta, (3) no column concrete placed, (4) no slab concrete placed, (5) staged 800 kg not counted as installed slab reinforcement, (6) no first-floor actual progress, (7) no whole-activity finish inferred, and (8) final inspection represented as inspection. All four outputs pass schema validation with no extraction validation errors. These are application-normalized observations, not raw generations: validators clear installed quantities on no-work, blocker, material-delivery and planned-work records and can clear unsupported dates. Core scores describe the combined extraction contract, not unaided model ability. Schema validity alone does not establish semantic correctness.', '',
        '| Extractor | Rows | Core checks | Elapsed seconds | Review finding |', '|---|---:|---:|---:|---|']
    findings = {
        'qwen': 'Final inspection is actual_progress/other; quantities and no-work facts are correct. Date guesses were removed by validation; warnings remain.',
        'gpt120': 'Inspection preserved; separate blocker rows retain both causes. Column-concrete blocker carries rebar_installation despite identifying SUP-GF-02, a work-type mismatch.',
        'gpt20': 'Six compact core events, inspection preserved. Blocker causes remain in text/evidence but structured blocker fields are null; column cause requires reading the quote.',
        'deepseek': 'Three inspection rows, no-work rows and planned first-floor statement remain separate. Internal bar relocation is labeled material_delivery; column checks and final inspection may overlap. No installed 800 kg or first-floor progress is invented.',
    }
    for n in NAMES:
        e = p['extraction'][n]
        lines.append(f"| {n} | {len(e['observations'])} | {CORE[n]}/8 | {e['elapsed_seconds']} | {findings[n]} |")
    lines += ['', 'Inspection/material/planned-work observed_status=completed refers to the event, not completion of a schedule activity. Every saved actual_finish and lifecycle_effects field is empty. DeepSeek material movement quantity was normalized to null; its 800 kg remains in the summary and evidence. GPT-OSS outputs use civil discipline where the schedule uses structural; successful mapping here does not certify discipline normalization.', '',
        '## All 16 worker pairs', '',
        'A correct identity is the source activity suffix shown in the observation appendix. DeepSeek observation 10 has no first-floor candidate and must abstain (null candidate with unmatched). Selecting a no-work activity identifies context; it does not approve installed progress. Pair scores therefore include this negative control.', '',
        '| Extractor | Selector | Rows saved / expected | Valid proposals | Correct identities or abstentions | Selection seconds |',
        '|---|---|---:|---:|---:|---:|']
    pairs = {}
    for e in NAMES:
        for s in NAMES:
            rows = p['selection'].get(f'{e}::{s}', [])
            good = 0
            for row in rows:
                expected = EXPECTED[e][row['observation'] - 1]
                good += int(not row['error'] and ((row['activity'] == f'SUP-GF-{expected}') if expected else
                    row['activity'] is None and row['mapping_state'] in ('unmatched',)))
            pairs[e, s] = (good, len(EXPECTED[e]), sum(r['elapsed_seconds'] for r in rows), sum(not r['error'] for r in rows))
            lines.append(f'| {e} | {s} | {len(rows)}/{len(EXPECTED[e])} | {pairs[e,s][3]} | {good}/{len(EXPECTED[e])} | {pairs[e,s][2]:.3f} |')
    lines += ['', 'First-floor negative control (DeepSeek observation 10):', '',
        '| Selector | Saved activity | State | Correct abstention |',
        '|---|---|---|---|']
    for selector in NAMES:
        row = next(r for r in p['selection'][f'deepseek::{selector}'] if r['observation'] == 10)
        correct = row['activity'] is None and row['mapping_state'] == 'unmatched' and not row['error']
        lines.append(f"| {selector} | {row['activity']} | {row['mapping_state']} | {'Yes' if correct else 'No'} |")
    lines += ['', 'Qwen’s suggested SUP-GF-01 for the first-floor statement is schema-valid but semantically wrong: no first-floor row exists in this pool. GPT-OSS 120B, 20B and DeepSeek correctly return unmatched. Separately, GPT-OSS 20B returns unmatched on DeepSeek observation 7 (bar relocation) instead of SUP-GF-04, giving that pair 9/10 overall. This is a conservative loss of identity recall, not an invented installation; the exact-identity scoring rule still counts it as a miss. GPT-OSS 120B and DeepSeek selection score 10/10 on DeepSeek extraction. This observation demonstrates why all proposals passing validation is insufficient for declaring a pair correct.', '']
    lines += ['', '## Ranking all 64 composed assignments', '',
        'Descriptive lexicographic ranking: complete legal planner and complete correct pair first; among nonpassing rows, legal planners precede failed planners; then higher core-check count; then fewer manually flagged secondary issues; then fewer extracted rows; then lower sum of planner + extraction + selection elapsed seconds; finally lower recorded token count. Secondary issue counts are Qwen 1 (inspection), GPT120 1 (blocker type), GPT20 1 (structured blocker loss), DeepSeek 2 (relocation label and potential inspection overlap). These subjective counts are disclosed rather than treated as calibrated accuracy. Latency is only a tie-breaker. Different priorities, especially structured blocker retention, can favor GPT120 or DeepSeek instead.', '',
        'Each row reuses measured components; time and tokens are **composed totals**, not a fresh end-to-end measurement. Elapsed includes admission and cross-provider call order. Many Groq worker calls wait about 22 seconds; this cannot establish pure inference speed. Tokens are reported without prices or a dollar-cost ranking. Failed attempts and interruptions are excluded from successful-path token totals but remain in the call audit.', '',
        '| Rank | Planner | Extractor | Selector | Contract/pair | Core | Secondary issues | Rows | Composed seconds | Successful-path tokens |',
        '|---:|---|---|---|---|---:|---:|---:|---:|---:|']
    def tokens(n, role, labels=None):
        return sum((a.get('usage') or {}).get('total_tokens', 0) or 0 for c in p['calls']
                   if c['model'] == p['models'][n][1] and c['role'] == role and c['ok']
                   and (labels is None or c['label'] in labels) for a in c['attempts'])
    combos = []
    for planner in NAMES:
        for e in NAMES:
            for s in NAMES:
                good, total, elapsed, valid = pairs[e,s]
                legal = all('action' in stage for stage in planners[planner].values())
                ready = legal and good == total and valid == total
                t = sum(stage['elapsed_seconds'] for stage in planners[planner].values()) + p['extraction'][e]['elapsed_seconds'] + elapsed
                tok = tokens(planner, 'orchestrator') + tokens(e, 'extraction') + tokens(s, 'selection', {f'{e} observation {i}' for i in range(1,total+1)})
                combos.append((not ready, -CORE[e], ISSUES[e], total, t, tok, planner, e, s, f"{'legal' if legal else 'planner failed'}; {good}/{total}"))
    combos.sort(key=lambda c: (c[0], "planner failed" in c[9], *c[1:9]))
    for rank, c in enumerate(combos,1):
        _, core, issues, rows, t, tok, planner, e, s, state = c
        lines.append(f'| {rank} | {planner} | {e} | {s} | {state} | {-core}/8 | {issues} | {rows} | {t:.3f} | {tok} |')
    lines += ['', '## Successful-call latency and token summary', '',
        'These aggregates include admission and are grouped across different inputs. Counts are operations; an operation may contain more than one provider attempt if the selector asks for a consistency correction. Failed operations are excluded here and retained in the audit.', '',
        '| Model | Role | Successful operations | Median seconds | Total seconds | Prompt / completion / total tokens |',
        '|---|---|---:|---:|---:|---|']
    for n in NAMES:
        for role in ('orchestrator', 'extraction', 'selection'):
            calls = [c for c in p['calls'] if c['model'] == p['models'][n][1] and c['role'] == role and c['ok']]
            if not calls:
                lines.append(f'| {n} | {role} | 0 | — | — | — |')
                continue
            usage = {k: sum((a.get('usage') or {}).get(k, 0) or 0 for c in calls for a in c['attempts']) for k in ('prompt_tokens','completion_tokens','total_tokens')}
            lines.append(f"| {n} | {role} | {len(calls)} | {statistics.median(c['elapsed_seconds'] for c in calls):.3f} | {sum(c['elapsed_seconds'] for c in calls):.3f} | {usage['prompt_tokens']} / {usage['completion_tokens']} / {usage['total_tokens']} |")
    lines += ['', '## Recommendation and limits', '',
        'Use the first fully passing row above as the trial candidate under this explicit rubric. Treat near-identical composed times as ties in practice: the GPT20-extraction pairs using Qwen and GPT120 selection differ by only 0.079 seconds, far below what this single paced trial can resolve. Qwen planning with GPT-OSS 20B extraction is the compact candidate; choose the selector using the measured pair result. GPT120 extraction retains structured blockers at the expense of two extra rows and a blocker work-type error. DeepSeek extraction preserves more ancillary events but increases selection calls from six to ten, including a necessary first-floor abstention. Qwen extraction needs correction of the inspection event. DeepSeek model-assisted planning is not recommended under the tested 128-token contract.', '',
        'The privately configured profile checked on 26 October is Qwen orchestrator (Groq slot 1), GPT-OSS 120B extractor (Groq slot 2), GPT-OSS 20B selector (Groq slot 2), V2/model-assisted enabled and account scopes disabled. This report does not change it. Trial recommendations require repeated reports, ambiguous identifiers, missing candidates, full retrieval, database-backed graph execution and human review before deployment selection.', '',
        'One report, one extraction per model and one completed trial per pair cannot establish significance, robustness, stable latency or universal superiority. Eight to ten correlated rows from one report are not independent evaluation samples. There was no randomized call order or frozen preregistered scoring rubric. Changes to the adapter occurred between initial and retest planner trials. Raw wire payloads and call-time source hashes were not saved, limiting exact reproduction. `artifacts/gonka-model-comparison/completion-manifest.json` fingerprints the source, schedule, runner, adapters and result at report generation only; it does not attest earlier call-time code. No provider price assumptions are made.', '',
        '## Full validated observation summaries and selections', '',
        'The JSON artifact retains every observation field and evidence quote. Below are all event summaries and every saved selection as activity / state / error; safe call diagnostics follow. This is not a dump of failed raw model generations.', '']
    for e in NAMES:
        lines += [f'### {e}', '']
        for i,o in enumerate(p['extraction'][e]['observations'],1):
            lines += [f"{i}. `{o['event_type']}` / `{o['work_type']}` / `{o['observed_status']}`; quantity `{o['quantity']}` `{o['unit']}`, kind `{o['quantity_kind']}`; expected `{EXPECTED[e][i-1] or 'abstain'}`. " + o['summary'].replace('\n',' '), '']
            for s in NAMES:
                row = next((r for r in p['selection'].get(f'{e}::{s}',[]) if r['observation'] == i), None)
                lines += [f"   - {s}: " + (f"`{row['activity']}` / `{row['mapping_state']}` / `{row['error']}` ({row['elapsed_seconds']}s)" if row else 'PENDING')]
            lines.append('')
    lines += ['## Complete safe call audit', '', '| # | Role | Model | Label | Result | Seconds | HTTP / finish / tokens |', '|---:|---|---|---|---|---:|---|']
    for i,c in enumerate(p['calls'],1):
        meta = '; '.join(f"{a['http_status']} / {a['finish_reason']} / {(a.get('usage') or {}).get('total_tokens')}" for a in c['attempts']) or 'No HTTP response'
        lines.append(f"| {i} | {c['role']} | {c['model']} | {c['label']} | {'OK' if c['ok'] else c.get('error')} | {c.get('elapsed_seconds')} | {meta} |")
    (ROOT / 'docs/FOUR_MODEL_ROLE_COMPARISON.md').write_text('\n'.join(lines) + '\n')
    (HERE / 'ranked-assignments.json').write_text(json.dumps([{'rank':i,'planner':c[6],'extractor':c[7],'selector':c[8],'contract_pair_pass':not c[0],'core_checks':-c[1],'secondary_issues':c[2],'rows':c[3],'composed_seconds':round(c[4],3),'successful_path_tokens':c[5]} for i,c in enumerate(combos,1)],indent=2)+'\n')
    files = [
        'artifacts/gonka-model-comparison/input.txt',
        'artifacts/gonka-model-comparison/four-model-matrix.json',
        'artifacts/gonka-model-comparison/four_model_matrix.py',
        'artifacts/gonka-model-comparison/summarize_matrix.py',
        'data/review/gt10-five-entry/schedule.csv',
        'backend/app/agent/hierarchy.py', 'backend/app/agent/schedule_decision.py',
        'backend/app/llm/gonka.py', 'backend/app/llm/groq.py',
        'backend/app/llm/openrouter.py', 'backend/app/llm/extract.py',
    ]
    (HERE / 'completion-manifest.json').write_text(json.dumps({
        'scope': 'Hashes at report generation, not call-time attestations of earlier trials',
        'sha256': {name: sha256((ROOT / name).read_bytes()).hexdigest() for name in files},
    }, indent=2) + '\n')
    print(f'Report: {len(p["calls"])} calls; {sum(v[1] for v in pairs.values())} expected selections; top assignment {combos[0][6:9]}')

if __name__ == '__main__':
    main()
