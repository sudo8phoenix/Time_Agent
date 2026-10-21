"""Fail closed when frozen evaluation artifacts change during an experiment."""
from hashlib import sha256
import json
from pathlib import Path


class EvaluationIntegrityError(RuntimeError):
    code = 'FROZEN_INPUT_CHANGED'


class FrozenExperimentGuard:
    """Recheck prepared artifacts and source/label/scorer hashes before each call.

    This detects changed evidence/configuration, not undiscovered semantic bugs.
    Raw file content and private paths never appear in the exported exception.
    """
    def __init__(self, prepared, plan):
        self.expected = {}
        prepared = Path(prepared)
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

    def check(self):
        try:
            if any(sha256(path.read_bytes()).hexdigest() != expected
                   for path, expected in self.expected.items()):
                raise EvaluationIntegrityError('Frozen evaluation input changed; stop and review affected results')
        except OSError:
            raise EvaluationIntegrityError('Frozen evaluation input unavailable; stop and review affected results') from None
