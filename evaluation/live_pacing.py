"""Schedule live evaluation cases in small groups without bypassing admission."""
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import time


def provider_cooldown_seconds():
    from app.db.models import HostedProviderAdmission
    from app.db.session import session_factory
    with session_factory() as db:
        row = db.get(HostedProviderAdmission, 'groq')
        value = (row.state or {}).get('cooldown', 0) if row else 0
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
        raise ValueError('Invalid provider cooldown state')
    return max(0, value - time.time())


def wait_before_case(output: Path, case_id, index, *, batch_size=5, pause_seconds=60,
                     cooldown=provider_cooldown_seconds, clock=time.monotonic,
                     sleep=time.sleep, max_wait_seconds=1800):
    """Pace before enqueue, recording time excluded from report readiness.

    This does not change provider quotas, request timeouts, retries or key slots.
    A 429 persisted by admission delays the next case, including within a group.
    """
    if not 1 <= batch_size <= 5 or not math.isfinite(pause_seconds) or pause_seconds < 60:
        raise ValueError('Use groups of at most five and pauses of at least 60 seconds')
    began = clock()
    pause = pause_seconds if index and index % batch_size == 0 else 0
    announced = False
    try:
        while True:
            elapsed = clock() - began
            delay = max(0, pause - elapsed, cooldown())
            if delay <= 0:
                break
            if not announced:
                print(json.dumps({'case_id': case_id, 'state': 'waiting_before_submission',
                    'delay_seconds': round(delay, 3)}), flush=True)
                announced = True
            if elapsed + delay > max_wait_seconds:
                raise RuntimeError('Live evaluation wait budget exceeded; preserve partial capture')
            sleep(min(5, delay))
    finally:
        row = {'case_id': case_id, 'recorded_at': datetime.now(timezone.utc).isoformat(),
            'case_index': index, 'batch_size': batch_size,
            'batch_pause_seconds': pause, 'pre_submission_wait_seconds': round(clock() - began, 3),
            'excluded_from_per_report_readiness': True}
        with (output / 'pacing.jsonl').open('a') as stream:
            stream.write(json.dumps(row) + '\n')
    return row['pre_submission_wait_seconds']
