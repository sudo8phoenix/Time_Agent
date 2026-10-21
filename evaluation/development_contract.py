"""Score explicitly enumerated coherent development annotation alternatives.

This opt-in diagnostic never changes the historical selected-field scorer and
never equates lexical fact checks with semantic evidence entailment.
"""
from evaluation.score_paired_pilot import fields_exact

VERSION = 'development-alternatives-v1'
SCORED_FIELDS = {'event_type', 'work_date', 'area', 'asset_tags', 'quantity',
                 'unit', 'quantity_kind', 'date_basis', 'summary', 'evidence'}


def score_case(case, observations, *, completed):
    alternatives = case.get('alternatives', [])
    if not alternatives or any(not isinstance(x, dict) or not x.get('id') or
                               not isinstance(x.get('events'), list) or not x['events']
                               for x in alternatives):
        raise ValueError('Explicit nonempty alternative inventories required')
    ids = [x['id'] for x in alternatives]
    if len(ids) != len(set(ids)):
        raise ValueError('Duplicate alternative IDs')
    if any(set(event) - SCORED_FIELDS for alternative in alternatives for event in alternative['events']):
        raise ValueError('Unsupported annotation fields would be unscored')
    inventories = [{tuple(sorted(event)) for event in alternative['events']}
                   for alternative in alternatives]
    if any(len(inventory) != 1 for inventory in inventories) or any(
            inventory != inventories[0] for inventory in inventories):
        raise ValueError('Alternatives must score the same explicit fields')
    matched = [alternative['id'] for alternative in alternatives
               if completed is True and fields_exact(alternative['events'], observations)]
    return {'scoring_version': VERSION, 'completed': completed,
            'accepted_alternative_ids': matched, 'fields_exact_any_alternative': bool(matched),
            'semantic_evidence_correct': None,
            'review_status': case.get('review_status', 'unreviewed')}
