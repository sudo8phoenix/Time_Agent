"""Offline structural eligibility for frozen validation/holdout corpora.

Never sends requests or reads label contents. A structurally eligible manifest
is not independent adjudication, representative sampling or release acceptance.
"""
import argparse
from datetime import date
from hashlib import sha256
import json
from pathlib import Path
import re


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def text_digest(text):
    return sha256(re.sub(r'\s+', ' ', text).strip().encode()).hexdigest()


def known_exposure(inputs_path, lineage_path):
    rows = json.loads(inputs_path.read_text())
    lineage = json.loads(lineage_path.read_text())['cases']
    return [dict(case_id=row['case_id'],
                 group_id=lineage[row['case_id']].get('group_id', lineage[row['case_id']].get('family')),
                 text_sha256=text_digest(row['text']),
                 document_sha256=row.get('source_document_sha256'),
                 parent_group_ids=lineage[row['case_id']].get('parent_group_ids', [])) for row in rows]


def check(manifest_path, inputs_path, labels_path, review_path, configuration_path, known):
    manifest = json.loads(manifest_path.read_text())
    rows = json.loads(inputs_path.read_text())
    review = json.loads(review_path.read_text())
    config = json.loads(configuration_path.read_text())
    failures = []
    required_hashes = {'inputs': digest(inputs_path), 'labels': digest(labels_path),
                       'review': digest(review_path), 'configuration': digest(configuration_path)}
    if manifest.get('hashes') != required_hashes:
        failures.append('frozen_hash_mismatch')
    if manifest.get('status') != 'frozen' or manifest.get('tuning_status') != 'stopped':
        failures.append('dataset_not_frozen_after_tuning')
    if (config.get('selection_status') != 'frozen_for_validation' or
            not isinstance(config.get('source_snapshot_sha256'), str) or
            not re.fullmatch(r'[0-9a-f]{64}', config['source_snapshot_sha256'])):
        failures.append('assembled_configuration_not_selected_and_frozen')
    ids, group_splits, texts, documents = set(), {}, {}, {}
    old_ids = {row['case_id'] for row in known}
    old_groups = {row['group_id'] for row in known if row.get('group_id')}
    old_texts = {row['text_sha256'] for row in known}
    old_documents = {row['document_sha256'] for row in known if row.get('document_sha256')}
    membership = {}
    lineage_edges = []
    split_groups = []
    allowed = {'case_id', 'group_id', 'split', 'text', 'report_date', 'source_document_sha256',
               'source_kind', 'provenance_locator', 'parent_group_ids'}
    if not isinstance(rows, list) or not rows:
        raise ValueError('Inputs must be a nonempty list')
    for row in rows:
        if not isinstance(row, dict) or set(row) - allowed or not allowed.issubset(row):
            failures.append('input_contract_or_label_leakage')
            continue
        cid, group, split = row['case_id'], row['group_id'], row['split']
        if not all(isinstance(value, str) and value.strip() for value in
                   (cid, group, row['text'], row['source_document_sha256'], row['provenance_locator'])):
            failures.append('missing_source_identity_or_provenance')
            continue
        if split not in {'development', 'validation', 'holdout'}:
            failures.append('unknown_split')
            continue
        if (row['source_kind'] not in {'real', 'synthetic'} or
                not isinstance(row['parent_group_ids'], list) or
                any(not isinstance(parent, str) or not parent.strip() for parent in row['parent_group_ids'])):
            failures.append('unknown_source_or_lineage')
            continue
        if not re.fullmatch(r'[0-9a-f]{64}', row['source_document_sha256']):
            failures.append('invalid_source_document_hash')
        try:
            if not isinstance(row['report_date'], str) or date.fromisoformat(row['report_date']).isoformat() != row['report_date']:
                raise ValueError('Invalid report date')
        except (TypeError, ValueError):
            failures.append('invalid_report_date')
        if cid in ids:
            failures.append('duplicate_case_id')
        ids.add(cid)
        membership[cid] = dict(group_id=group, split=split)
        if group in group_splits and group_splits[group] != split:
            failures.append('cross_split_group_leakage')
        group_splits[group] = split
        split_groups.append((group, split))
        lineage_edges.extend((group, parent) for parent in row['parent_group_ids'])
        text = text_digest(row['text'])
        document = row['source_document_sha256']
        for collection, identity in [(texts, text), (documents, document)]:
            if identity in collection and collection[identity] != split:
                failures.append('cross_split_source_leakage')
            collection[identity] = split
        if split != 'development' and (cid in old_ids or group in old_groups or text in old_texts or
                                      document in old_documents or set(row['parent_group_ids']) & old_groups):
            failures.append('consumed_family_in_validation_or_holdout')
    # Compare connected source families, including common ancestors and chains.
    # Checking only each row's direct parent misses renamed cousins and descendants.
    families = {}

    def root(group):
        families.setdefault(group, group)
        current = group
        while families[current] != current:
            current = families[current]
        while families[group] != group:
            parent = families[group]
            families[group] = current
            group = parent
        return current

    for previous in known:
        group = previous.get('group_id')
        if group:
            lineage_edges.extend((group, parent) for parent in previous.get('parent_group_ids', []))
    for child, parent in lineage_edges:
        families[root(child)] = root(parent)
    consumed_roots = {root(group) for group in old_groups}
    component_splits = {}
    for group, split in split_groups:
        family = root(group)
        if family in component_splits and component_splits[family] != split:
            failures.append('cross_split_lineage_leakage')
        component_splits[family] = split
        if split != 'development' and family in consumed_roots:
            failures.append('consumed_family_in_validation_or_holdout')
    if membership != manifest.get('membership'):
        failures.append('split_membership_mismatch')
    if review.get('status') != 'reviewed' or set(review.get('case_ids', [])) != ids:
        failures.append('review_not_complete_for_frozen_cases')
    if review.get('kind') not in {'ai_assisted', 'independent_human'}:
        failures.append('review_kind_unavailable')
    return dict(version='fresh-dataset-preflight-v1', structurally_eligible=not failures,
                failures=sorted(set(failures)), cases=len(rows), source_groups=len(group_splits),
                labels_read=False, hashes=required_hashes, release_accepted=False,
                review_kind=review.get('kind'),
                review_identity_verified=False,
                limitations=['Only supplied exposure history is checked; missing history is not proof of freshness.',
                             'Lineage, review identity and representative sampling still need trusted evidence.',
                             'AI-assisted review is not independent human adjudication.'])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('manifest', 'inputs', 'labels', 'review', 'configuration', 'exposure-inputs', 'exposure-lineage', 'output'):
        parser.add_argument('--'+name, type=Path, required=True)
    args = parser.parse_args()
    result = check(args.manifest, args.inputs, args.labels, args.review, args.configuration,
                   known_exposure(args.exposure_inputs, args.exposure_lineage))
    with args.output.open('x') as stream:
        stream.write(json.dumps(result, indent=2)+'\n')
    raise SystemExit(0 if result['structurally_eligible'] else 2)
