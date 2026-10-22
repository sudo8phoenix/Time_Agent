"""Offline evaluation controls; no provider transport or production activation.

Token IDs must come from the evaluated guard's tokenizer, including an explicit
reservation for policy/wrapper tokens. These controls do not attest tokenizer
compatibility, semantic labels, reviewer identity, or unseen-data provenance.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from collections.abc import Sequence
from hashlib import sha256
import json
from typing import Callable


SAFETY_EFFECTS = frozenset({
    'unapproved_progress_mutation', 'unapproved_delivery', 'unauthorized_access',
    'cross_project_leakage', 'invented_approval', 'duplicate_committed_effect',
})
DEFECTS = frozenset({'schema', 'scorer', 'annotation'})


def _identity(value):
    if not isinstance(value, str) or not value or value.strip() != value:
        raise ValueError('Canonical nonblank identity required')
    return value


def _digest(value):
    return sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def screen_tokens(tokens, classify: Callable, *, context_tokens, reserved_tokens,
                  overlap_tokens, max_chunks, required=True):
    """Screen every token, retain unknown coverage, and fail closed on outages.

    classify receives an immutable tuple of token IDs and returns safe/unsafe.
    Invalid replies and exceptions mean unavailable. Optional outages permit
    continuation but can never claim screening completed. Policy metadata is
    checked separately by policy_contract before a Safeguard experiment.
    """
    if type(required) is not bool:
        raise ValueError('Explicit required flag required')
    if (any(type(v) is not int for v in
            (context_tokens, reserved_tokens, overlap_tokens, max_chunks))
            or context_tokens <= 0 or reserved_tokens < 0 or max_chunks <= 0):
        raise ValueError('Invalid chunk limits')
    width = context_tokens - reserved_tokens
    if width <= 0 or not 0 <= overlap_tokens < width:
        raise ValueError('Overlap must be smaller than available context')
    if not isinstance(tokens, Sequence) or not tokens:
        raise ValueError('Bounded nonempty token sequence required')
    total = len(tokens)
    if total > width + (max_chunks - 1) * (width - overlap_tokens):
        return dict(status='unavailable', allowed=not required, screened=False,
                    covered_tokens=0, total_tokens=total, calls=0,
                    reason='chunk_budget', chunks=[])
    tokens = tuple(tokens)
    if any(type(t) is not int or t < 0 for t in tokens):
        raise ValueError('Nonempty nonnegative token IDs required')
    ranges = []
    start = 0
    while start < len(tokens):
        end = min(start + width, len(tokens))
        ranges.append((start, end))
        if len(ranges) > max_chunks:
            return dict(status='unavailable', allowed=not required, screened=False,
                        covered_tokens=0, total_tokens=len(tokens), calls=0,
                        reason='chunk_budget', chunks=[])
        if end == len(tokens):
            break
        start = end - overlap_tokens
    chunks = []
    covered = 0
    for start, end in ranges:
        try:
            verdict = classify(tokens[start:end])
            if verdict not in ('safe', 'unsafe'):
                verdict = 'unavailable'
        except Exception:
            verdict = 'unavailable'
        chunks.append(dict(start=start, end=end, verdict=verdict))
        if verdict == 'unavailable':
            return dict(status=verdict, allowed=not required, screened=False,
                        covered_tokens=covered, total_tokens=len(tokens), calls=len(chunks),
                        reason='guard_unavailable', chunks=chunks)
        covered = end
        if verdict == 'unsafe':
            return dict(status=verdict, allowed=False, screened=False,
                        covered_tokens=covered, total_tokens=len(tokens), calls=len(chunks),
                        reason='guard_rejection', chunks=chunks)
    return dict(status='safe', allowed=True, screened=True,
                covered_tokens=covered, total_tokens=len(tokens), calls=len(chunks),
                reason=None, chunks=chunks)


def policy_contract(policy, labels):
    """Require an explicit reviewed injection policy; never score event accuracy."""
    if not isinstance(policy, dict):
        raise ValueError('Explicit policy required')
    for key in ('version', 'text', 'review_basis', 'review_evidence'):
        _identity(policy.get(key))
    if policy.get('task') != 'prompt_injection' or policy.get('review_status') != 'reviewed':
        raise ValueError('Reviewed injection policy required')
    if not labels:
        raise ValueError('Reviewed policy labels required')
    seen = set()
    for row in labels:
        identity = _identity(row.get('case_id'))
        if identity in seen or type(row.get('attack')) is not bool:
            raise ValueError('Unique explicit policy labels required')
        seen.add(identity)
        if (row.get('policy_version') != policy['version']
                or row.get('review_status') != 'reviewed'):
            raise ValueError('Policy label review/version mismatch')
    return dict(policy_sha256=_digest(policy), label_sha256=_digest(labels),
                labels=len(labels), task='prompt_injection',
                event_correctness_assessed=False, review_basis=policy['review_basis'])


def blind_judge_request(*, source, prediction, rubric):
    """Allowlist the request shape; callers supply semantic payloads only.

    This strips envelope metadata by never accepting it. Source/prediction text
    may itself name a model; semantic redaction requires separate review.
    """
    if any(not isinstance(value, str) or not value.strip()
           for value in (source, prediction, rubric)):
        raise ValueError('Source, prediction and rubric text required')
    return dict(source=source, prediction=prediction, rubric=rubric)


def judge_agreement(labels, verdicts):
    """Measure same-domain reviewed-label agreement, retaining missing judgments."""
    if not labels:
        raise ValueError('Reviewed labels required')
    expected = {}
    for row in labels:
        identity = _identity(row.get('case_id'))
        if (identity in expected or type(row.get('correct')) is not bool
                or row.get('review_status') != 'reviewed'):
            raise ValueError('Unique reviewed binary labels required')
        _identity(row.get('review_evidence'))
        expected[identity] = row['correct']
    actual = {}
    for row in verdicts:
        identity = _identity(row.get('case_id'))
        if (identity not in expected or identity in actual
                or type(row.get('correct')) is not bool):
            raise ValueError('Unique scheduled binary judgments required')
        actual[identity] = row['correct']
    tp = sum(actual[k] and expected[k] for k in actual)
    tn = sum(not actual[k] and not expected[k] for k in actual)
    fp = sum(actual[k] and not expected[k] for k in actual)
    fn = sum(not actual[k] and expected[k] for k in actual)
    return dict(total=len(expected), judged=len(actual), missing=len(expected)-len(actual),
                tp=tp, tn=tn, fp=fp, fn=fn,
                agreement=(tp+tn)/len(actual) if actual else None,
                agreement_over_scheduled=(tp+tn)/len(expected),
                independent_review_verified=False, release_accepted=False)


def disagreement_gate(*, critical, worker_correct, judge_correct, adjudication=None):
    if any(type(v) is not bool for v in (critical, worker_correct, judge_correct)):
        raise ValueError('Explicit binary judgments required')
    disagreement = worker_correct != judge_correct
    resolved = False
    if adjudication is not None:
        if not isinstance(adjudication, dict):
            raise ValueError('Adjudication evidence required')
        for key in ('reviewer', 'evidence', 'decision'):
            _identity(adjudication.get(key))
        if adjudication['decision'] not in ('worker', 'judge', 'neither'):
            raise ValueError('Unknown adjudication decision')
        resolved = True
    return dict(disagreement=disagreement, adjudicated=resolved,
                blocked=critical and disagreement and not resolved,
                agreement_is_factual_proof=False)


def _split_families(splits):
    """Join declared ancestors before comparing splits, including renamed cousins."""
    if not isinstance(splits, dict) or set(splits) != {
            'development', 'train', 'validation', 'holdout'}:
        raise ValueError('Four explicit splits required')
    cases, groups, families, contents = {}, {}, {}, {}

    def root(group):
        families.setdefault(group, group)
        while families[group] != group:
            families[group] = families[families[group]]
            group = families[group]
        return group

    for split, rows in splits.items():
        if not isinstance(rows, list):
            raise ValueError('Explicit split rows required')
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError('Explicit split rows required')
            case, group = _identity(row.get('case_id')), _identity(row.get('group_id'))
            if case in cases or (group in groups and groups[group] != split):
                raise ValueError('Case or lineage crosses splits')
            cases[case], groups[group] = split, split
            parents = row.get('parent_group_ids', [])
            if not isinstance(parents, list):
                raise ValueError('Explicit parent lineage list required')
            root(group)
            for parent in parents:
                families[root(group)] = root(_identity(parent))
            for key in ('text_sha256', 'source_document_sha256'):
                if key not in row:
                    continue
                digest = row[key]
                if (not isinstance(digest, str) or len(digest) != 64
                        or any(c not in '0123456789abcdef' for c in digest)):
                    raise ValueError('Canonical source SHA-256 required')
                identity = (key, digest)
                if identity in contents and contents[identity] != split:
                    raise ValueError('Source content crosses splits')
                contents[identity] = split
    owners = {}
    for group, split in groups.items():
        family = root(group)
        if family in owners and owners[family] != split:
            raise ValueError('Case or lineage crosses splits')
        owners[family] = split
    return {group: root(group) for group in families}, cases, groups


def split_contract(splits):
    """Reject declared lineage/content overlap; unrecorded aliases stay unknown."""
    families, cases, groups = _split_families(splits)
    return dict(cases=len(cases), groups=len(groups), freshness_certified=False,
                lineage_components=len(set(families.values())),
                split_sha256=_digest(splits))


def calibration_contract(splits, *, fit_case_ids, evaluation_case_ids, consumed_groups):
    """Enforce fit/evaluation roles and declared exposure before threshold evaluation."""
    families, _, _ = _split_families(splits)
    fit, evaluate = set(fit_case_ids), set(evaluation_case_ids)
    if (not fit or not evaluate or len(fit) != len(fit_case_ids)
            or len(evaluate) != len(evaluation_case_ids) or fit & evaluate):
        raise ValueError('Distinct nonempty fitting/evaluation cases required')
    allowed = {r['case_id'] for s in ('development', 'train', 'validation') for r in splits[s]}
    holdout = {r['case_id']: r['group_id'] for r in splits['holdout']}
    if not fit <= allowed or not evaluate <= set(holdout):
        raise ValueError('Fit only development/train/validation; evaluate only holdout')
    if (not isinstance(consumed_groups, (list, tuple, set))
            or any(not isinstance(g, str) or not g or g.strip() != g for g in consumed_groups)):
        raise ValueError('Explicit canonical consumed group inventory required')
    consumed = {families.get(g, g) for g in consumed_groups}
    if any(families[holdout[c]] in consumed for c in evaluate):
        raise ValueError('Consumed evaluation lineage')
    return dict(fit_cases=len(fit), evaluation_cases=len(evaluate),
                exposure_checked=True, freshness_certified=False,
                thresholds_fitted=False, release_accepted=False)


@dataclass
class StopGate:
    """Sticky in-memory experiment stop with conservative affected-result scope.

    Runner must persist snapshots and call check before each external operation.
    A new process must restore the snapshot; this is not a database transaction.
    """
    completed: list[str] = field(default_factory=list)
    stops: list[dict] = field(default_factory=list)

    def check(self):
        if self.stops:
            raise RuntimeError('Experiment stopped; preserve evidence and review affected results')

    def complete(self, trial_id):
        self.check()
        trial_id = _identity(trial_id)
        if trial_id in self.completed:
            raise ValueError('Duplicate completed trial')
        self.completed.append(trial_id)

    def observe(self, *, kind, category, evidence_sha256):
        if (kind not in ('safety', 'integrity')
                or category not in (SAFETY_EFFECTS if kind == 'safety' else DEFECTS)):
            raise ValueError('Known stop category required')
        if (not isinstance(evidence_sha256, str) or len(evidence_sha256) != 64
                or any(c not in '0123456789abcdef' for c in evidence_sha256)):
            raise ValueError('Evidence SHA-256 required')
        self.stops.append(dict(kind=kind, category=category, evidence_sha256=evidence_sha256))

    def snapshot(self):
        return dict(version='evaluation-stop-v1', completed=list(self.completed),
                    stops=[dict(s) for s in self.stops],
                    affected_results=list(self.completed) if self.stops else [],
                    review_required=bool(self.stops), release_accepted=False)

    @classmethod
    def restore(cls, snapshot):
        if snapshot.get('version') != 'evaluation-stop-v1':
            raise ValueError('Unknown stop snapshot version')
        gate = cls()
        for trial in snapshot['completed']:
            gate.complete(trial)
        for stop in snapshot['stops']:
            gate.observe(**stop)
        if snapshot != gate.snapshot():
            raise ValueError('Inconsistent stop snapshot')
        return gate
