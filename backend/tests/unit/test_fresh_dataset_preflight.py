from copy import deepcopy
from hashlib import sha256
import json

from evaluation.fresh_dataset_preflight import check, digest, text_digest


def bundle(tmp_path, rows, *, tuning='stopped'):
    paths = {name: tmp_path/(name+'.json') for name in ['manifest','inputs','labels','review','configuration']}
    paths['inputs'].write_text(json.dumps(rows))
    # Deliberately not JSON: eligibility must never open or interpret gold labels.
    paths['labels'].write_text('protected gold label contents')
    paths['review'].write_text(json.dumps({'status':'reviewed','kind':'ai_assisted','case_ids':[r['case_id'] for r in rows]}))
    paths['configuration'].write_text(json.dumps({'selection_status':'frozen_for_validation','source_snapshot_sha256':'a'*64}))
    paths['manifest'].write_text(json.dumps({'status':'frozen','tuning_status':tuning,
        'hashes':{k:digest(v) for k,v in paths.items() if k!='manifest'},
        'membership':{r['case_id']:{'group_id':r['group_id'],'split':r['split']} for r in rows}}))
    return paths


def row(cid,group,split,text='New separately sourced narrative'):
    return dict(case_id=cid,group_id=group,split=split,text=text,report_date='2026-10-20',
                source_document_sha256=sha256((group+text).encode()).hexdigest(),source_kind='synthetic',
                provenance_locator='synthetic:1',parent_group_ids=[])


def run(paths,known=()):
    return check(*(paths[k] for k in ['manifest','inputs','labels','review','configuration']),known)


def test_structural_check_does_not_read_gold_or_claim_review_identity_or_release(tmp_path):
    result = run(bundle(tmp_path,[row('new','new-family','holdout')]))
    assert result['structurally_eligible'] and not result['labels_read']
    assert not result['review_identity_verified'] and not result['release_accepted']


def test_renaming_a_consumed_case_and_changing_whitespace_does_not_make_it_unseen(tmp_path):
    known = [dict(case_id='old-id',group_id='old-family',text_sha256=text_digest('Excavated 2 m3.'),document_sha256=None)]
    result = run(bundle(tmp_path,[row('new-id','new-family','holdout','Excavated   2 m3.\n')]),known)
    assert not result['structurally_eligible']
    assert 'consumed_family_in_validation_or_holdout' in result['failures']


def test_source_families_and_documents_cannot_cross_splits(tmp_path):
    a = row('a','group','validation')
    b = deepcopy(a)
    b.update(case_id='b',split='holdout')
    result = run(bundle(tmp_path,[a,b]))
    assert 'cross_split_group_leakage' in result['failures']
    assert 'cross_split_source_leakage' in result['failures']


def test_holdout_freeze_requires_tuning_to_stop_and_hashes_to_stay_frozen(tmp_path):
    paths = bundle(tmp_path,[row('a','new','holdout')],tuning='active')
    paths['configuration'].write_text('{}')
    result = run(paths)
    assert {'dataset_not_frozen_after_tuning','frozen_hash_mismatch','assembled_configuration_not_selected_and_frozen'} <= set(result['failures'])


def test_input_label_leakage_and_consumed_parent_family_are_rejected(tmp_path):
    item = row('a','new','holdout')
    item['expected_quantity'] = 2
    result = run(bundle(tmp_path,[item]))
    assert 'input_contract_or_label_leakage' in result['failures']
    item.pop('expected_quantity')
    item['parent_group_ids']=['consumed']
    paths = bundle(tmp_path,[item])
    result=run(paths,[dict(case_id='old',group_id='consumed',text_sha256='x',document_sha256=None)])
    assert 'consumed_family_in_validation_or_holdout' in result['failures']


def test_invalid_provenance_and_dates_cannot_pass_structural_eligibility(tmp_path):
    item = row('a', 'new', 'holdout')
    item.update(source_document_sha256='invented', report_date='2026-02-30')
    result = run(bundle(tmp_path, [item]))
    assert {'invalid_source_document_hash', 'invalid_report_date'} <= set(result['failures'])
    item['parent_group_ids'] = [{'family': 'untrusted'}]
    result = run(bundle(tmp_path, [item]))
    assert 'unknown_source_or_lineage' in result['failures']


def test_common_parent_cannot_bridge_validation_and_holdout(tmp_path):
    a = row('a', 'new-a', 'validation', 'First independent wording')
    b = row('b', 'new-b', 'holdout', 'Second independent wording')
    a['parent_group_ids'] = b['parent_group_ids'] = ['shared-original']
    result = run(bundle(tmp_path, [a, b]))
    assert 'cross_split_lineage_leakage' in result['failures']


def test_transitive_parent_and_consumed_cousin_are_not_fresh(tmp_path):
    a = row('a', 'new-a', 'holdout', 'First new wording')
    b = row('b', 'new-b', 'holdout', 'Second new wording')
    a['parent_group_ids'] = ['new-b']
    b['parent_group_ids'] = ['original']
    known = [dict(case_id='old', group_id='old-family', text_sha256='x',
                  document_sha256=None, parent_group_ids=['original'])]
    result = run(bundle(tmp_path, [a, b]), known)
    assert 'consumed_family_in_validation_or_holdout' in result['failures']


def test_lineage_cycles_are_bounded_and_still_detect_leakage(tmp_path):
    a = row('a', 'new-a', 'validation', 'First wording')
    b = row('b', 'new-b', 'holdout', 'Second wording')
    a['parent_group_ids'] = ['new-b']
    b['parent_group_ids'] = ['new-a']
    assert 'cross_split_lineage_leakage' in run(bundle(tmp_path, [a, b]))['failures']


def test_source_snapshot_must_be_a_real_hash_shape(tmp_path):
    paths = bundle(tmp_path, [row('a', 'new', 'holdout')])
    paths['configuration'].write_text(json.dumps(dict(selection_status='frozen_for_validation',
                                                     source_snapshot_sha256='placeholder')))
    assert 'assembled_configuration_not_selected_and_frozen' in run(paths)['failures']


def test_long_ancestry_does_not_exhaust_python_stack(tmp_path):
    item = row('new', 'ancestor-0', 'holdout')
    known = [dict(case_id=f'old-{i}', group_id=f'ancestor-{i}', text_sha256='x',
                  document_sha256=None, parent_group_ids=[f'ancestor-{i+1}'])
             for i in range(1500)]
    assert 'consumed_family_in_validation_or_holdout' in run(bundle(tmp_path, [item]), known)['failures']
