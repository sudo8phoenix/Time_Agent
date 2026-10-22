"""Fail closed when frozen evaluation artifacts change during an experiment."""
from hashlib import sha256
import json
import os
from pathlib import Path

from evaluation.protocol_controls import StopGate


class EvaluationIntegrityError(RuntimeError):
    code = 'FROZEN_INPUT_CHANGED'


class FrozenExperimentGuard:
    """Recheck prepared artifacts and source/label/scorer hashes before each call.

    This detects changed evidence/configuration, not undiscovered semantic bugs.
    Raw file content and private paths never appear in the exported exception.
    """
    def __init__(self, prepared, plan):
        self.expected = {}
        self.stop_gate = StopGate()
        prepared = Path(prepared).resolve()
        # Outside the sealed directory: never rewrite a historical prepared file.
        # A marker's presence (even empty/corrupt) blocks every new guard instance.
        self.stop_marker = prepared.with_name(prepared.name + '.evaluation-stop.json')
        self._check_marker()
        try:
            if json.loads((prepared / 'plan.json').read_text()) != plan:
                raise EvaluationIntegrityError('Frozen evaluation plan changed; stop and review affected results')
            for filename, key in [('wire-schema.json', 'wire_schema_sha256'),
                                  ('unit-wire-schema.json', 'unit_wire_schema_sha256')]:
                if key in plan:
                    value = json.loads((prepared / filename).read_text())
                    if sha256(json.dumps(value, sort_keys=True).encode()).hexdigest() != plan[key]:
                        raise EvaluationIntegrityError('Frozen evaluation schema changed; stop and review affected results')
        except (OSError, ValueError):
            raise EvaluationIntegrityError('Frozen evaluation input invalid or unavailable; stop and review affected results') from None
        for name, expected in plan['source_sha256'].items():
            self.expected[Path(name)] = expected
        for path in prepared.iterdir():
            if path.is_file():
                self.expected.setdefault(path, sha256(path.read_bytes()).hexdigest())
        for name, expected in plan.get('file_sha256', {}).items():
            self.expected[prepared / name] = expected
        self.check()

    def report_defect(self, *, category, evidence_sha256, output):
        """Stop immediately on a reported semantic defect, even without hash drift.

        Persist to a new artifact outside the frozen prepared directory. If
        persistence fails, the in-memory guard stays stopped and the error is
        propagated; callers must not resume the experiment.
        """
        self._report_stop(kind='integrity', category=category,
                          evidence_sha256=evidence_sha256, output=output)

    def report_safety(self, *, category, evidence_sha256, output):
        self._report_stop(kind='safety', category=category,
                          evidence_sha256=evidence_sha256, output=output)

    def record_result(self, trial_id):
        """Include each persisted terminal outcome in later affected-result review."""
        self.check()
        self.stop_gate.complete(trial_id)

    def _report_stop(self, *, kind, category, evidence_sha256, output):
        self.stop_gate.observe(kind=kind, category=category,
                               evidence_sha256=evidence_sha256)
        value = json.dumps(self.stop_gate.snapshot(), indent=2) + '\n'
        # Write the permanent latch before optional capture evidence. A collision
        # retains the previous stop; an I/O failure leaves this instance stopped.
        try:
            with self.stop_marker.open('x') as stream:
                stream.write(value)
                stream.flush()
                os.fsync(stream.fileno())
        except FileExistsError:
            pass
        with Path(output).open('x') as stream:
            stream.write(value)

    def _check_marker(self):
        try:
            self.stop_marker.lstat()
        except FileNotFoundError:
            return
        except OSError:
            raise EvaluationIntegrityError('Evaluation stop state unavailable; stop and review') from None
        raise EvaluationIntegrityError('Retained evaluation stop; use a separately reviewed study')

    def requires_review(self):
        if self.stop_gate.stops:
            return True
        try:
            self.stop_marker.lstat()
        except FileNotFoundError:
            return False
        except OSError:
            return True
        return True

    def check(self):
        if self.stop_gate.stops:
            raise EvaluationIntegrityError(
                'Reported evaluation defect; stop and review affected results')
        self._check_marker()
        try:
            if any(sha256(path.read_bytes()).hexdigest() != expected
                   for path, expected in self.expected.items()):
                raise EvaluationIntegrityError('Frozen evaluation input changed; stop and review affected results')
        except OSError:
            raise EvaluationIntegrityError('Frozen evaluation input unavailable; stop and review affected results') from None
