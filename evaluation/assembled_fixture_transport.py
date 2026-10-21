"""Deterministic test double for the two assembled-development fixtures.

No network access, provider import, label-file reads or production use. This
verifies harness plumbing and payload sensitivity, never live model quality.
"""
from hashlib import sha256
import json
import re

from evaluation.prompt_ablation import observation


class SyntheticTransport:
    def __init__(self):
        self.payload_hashes = []

    def __call__(self, provider, method, url, payload, timeout, headers):
        self.payload_hashes.append(sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest())
        properties = payload['response_format']['json_schema']['schema']['properties']
        text = payload['messages'][1]['content']
        if 'observations' in properties:
            match = re.search(r'\[([^ ]+) \| synthetic:1\]\n(.*)', text, re.S)
            if not match:
                raise ValueError('Unexpected synthetic fragment layout')
            fid, source = match.groups()
            amount = re.search(r'(\d+) m3', source).group(1)
            value = dict(observations=[observation(fid, source, work_date='2026-10-20',
                         quantity=amount, quantity_kind='delta', unit='m3', raw_unit='m3',
                         area='Zone Cedar' if 'Zone Cedar' in source else None,
                         asset_tags=['TR-030'] if 'TR-030' in source else [])])
        else:
            context = json.loads(text)
            if 'action' in properties:
                value = dict(action=context['legal_actions'][0])
            elif 'candidate_ids' in properties:
                rows = context['schedule_activities']
                cedar = context['observation'].get('area') == 'Zone Cedar'
                value = dict(candidate_ids=[r['id'] for r in rows if not cedar or r['external_id'] == 'EXC-CEDAR'])
            elif 'candidate_id' in properties:
                cedar = context['observation'].get('area') == 'Zone Cedar'
                value = dict(candidate_id=context['candidates'][0]['candidate_id'] if cedar else None,
                             mapping_state='suggested' if cedar else 'ambiguous',
                             evidence_fragment_ids=list(context['fragments']),
                             reason_codes=['DIRECT_MATCH'] if cedar else ['AMBIGUOUS_LOCATION'],
                             explanation='Synthetic fixture selection; identity requires clarification.' if not cedar else 'Explicit synthetic identity.',
                             missing_information=[] if cedar else ['Area and asset identity'])
            else:
                raise ValueError('Unexpected synthetic request stage')
        return 200, dict(model=payload['model'], usage=dict(prompt_tokens=0, completion_tokens=0),
                         choices=[dict(finish_reason='stop', message=dict(content=json.dumps(value)))])
