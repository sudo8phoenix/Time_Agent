"""Read-only sanitized preflight for a fixed slot-2 development experiment."""
from datetime import datetime, timezone
import argparse
import json
from pathlib import Path
from urllib.request import Request, urlopen

from app.db.session import engine
from app.settings import get_settings
from evaluation.repeated_development import ExperimentStop, verify_plan, write
from ops.runtime_status import build_report


def check(prepared, output):
    plan, _, _ = verify_plan(prepared)
    settings = get_settings()
    key = settings.groq_api_key_2
    if not key:
        raise ExperimentStop('Slot 2 unavailable')
    with engine.connect() as db:
        runtime = build_report(db, settings)
    queued = any(info and any(info.get('by_state', {}).get(state, 0) for state in ('running', 'queued'))
                 for info in (runtime['jobs'], runtime['conversation_tasks']))
    capacity = (runtime.get('hosted_provider_admission') or {}).get('groq', {})
    active = bool(capacity.get('cooldown_remaining_seconds') or capacity.get('lease_remaining_seconds'))
    request = Request('https://api.groq.com/openai/v1/models', headers={
        'Authorization': 'Bearer ' + key.get_secret_value(), 'User-Agent': 'site-progress-agent/0.1'})
    try:
        with urlopen(request, timeout=20) as response:
            body = json.loads(response.read(2 * 1024 * 1024))
            listed = any(row.get('id') == plan['model'] for row in body.get('data', []))
    except Exception as error:
        raise ExperimentStop('Model catalog check failed: ' + type(error).__name__) from None
    result = dict(checked_at=datetime.now(timezone.utc).isoformat(), model=plan['model'], key_slot=2,
                  model_access_verified=listed, price_verified=plan['price_checked'] == datetime.now(timezone.utc).date().isoformat(),
                  price_source=plan['price_source'], prices_per_million=plan['prices_per_million'],
                  no_pending_work=not queued, no_active_lease_or_cooldown=not active,
                  remaining_requests=capacity.get('remaining_requests', -1),
                  quota_evidence='Latest shared admission observation; not verified slot-specific entitlement',
                  capacity_snapshot=capacity, account_scope='Owner-confirmed independent slot 2 organization',
                  other_account_consumers='unknown', runtime=runtime,
                  price_verification='Public model pricing checked on plan price_checked date; not billing evidence',
                  permissions='Catalog check verifies listed model; inference can still reject and will stop')
    write(output, result)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepared', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    check(args.prepared, args.output)
