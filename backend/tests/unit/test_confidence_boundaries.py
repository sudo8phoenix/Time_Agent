"""Confidence retains stage identity, source policy and verified denominators."""
import json
from pathlib import Path
import pytest
from app.confidence.provenance import capture
from evaluation.calibrate import assess


def score(value):
    return dict(score=value, method='fixture', version='test-only')


def test_extraction_and_link_scores_cannot_substitute_for_each_other():
    labels = [dict(case_id='a', targets={'event':'start','link':'A'})]
    pred = dict(case_id='a', targets=labels[0]['targets'],
                confidence={'extraction':score(.2),'linking':score(.9)})
    result = assess(labels,[pred], min_support=1)
    assert result['metrics']['event']['tradeoffs'][0]['threshold'] == .2
    assert result['metrics']['link']['tradeoffs'][0]['threshold'] == .9
    pred['confidence'].pop('linking')
    result = assess(labels,[pred],min_support=1)
    assert result['metrics']['link']['unavailable_score_count'] == 1
    assert result['metrics']['link']['review_priority_threshold'] is None
    assert result['metrics']['event']['review_priority_threshold'] is not None
    stored = capture({}, {}, metadata={'prompt_version':'extract-v1','selection_prompt_version':'select-v2'})
    assert stored['confidence']['extraction']['stage'] == 'extraction'
    assert stored['confidence']['linking']['stage'] == 'linking'
    assert stored['confidence']['extraction']['version'] == 'extract-v1'
    assert stored['confidence']['linking']['version'] == 'select-v2'
    assert all(v['score'] is None for v in stored['confidence'].values())


@pytest.mark.parametrize('state',['failed','cancelled','invalid','unattempted','running','queued'])
def test_diagnostic_gold_on_failed_output_cannot_fit_a_threshold(state):
    labels=[dict(case_id='a',targets={'event':'start','link':'A'})]
    pred=dict(case_id='a',state=state,targets=labels[0]['targets'],
              confidence={'extraction':score(1),'linking':score(1)})
    result=assess(labels,[pred],min_support=1)
    for kind in ('event','link'):
        assert result['metrics'][kind]['unavailable_score_count']==1
        assert result['metrics'][kind]['review_priority_threshold'] is None
        assert result['metrics'][kind]['tradeoffs']==[]


def test_missing_null_is_not_verified_abstention():
    labels=[dict(case_id='a',targets={'link':None})]
    assert assess(labels,[])['metrics']['link']['correct_abstentions']==0
    assert assess(labels,[dict(case_id='a',targets={})])['metrics']['link']['correct_abstentions']==0
    assert assess(labels,[dict(case_id='a',targets={'link':None})])['metrics']['link']['correct_abstentions']==1
    assert assess(labels,[dict(case_id='a',state='failed',targets={'link':None})])['metrics']['link']['correct_abstentions']==0


def test_frozen_study_precision_and_support_do_not_imply_population_assurance():
    policy=json.loads(Path('data/evaluation/prototype-v1/calibration-study-policy-v1.json').read_text())['policy']
    assert policy == {'target_precision':.98,'min_support':20}
    labels=[dict(case_id=str(i),targets={'link':'A'}) for i in range(20)]
    predictions=[dict(case_id=str(i),targets={'link':'A'},confidence={'linking':score(.9)}) for i in range(20)]
    assert assess(labels,predictions[:19],**policy)['metrics']['link']['review_priority_threshold'] is None
    result=assess(labels,predictions,**policy)
    assert result['metrics']['link']['review_priority_threshold']['count']==20
    assert result['policy']['authorized_acceptance_required']
    predictions[-1]['targets']['link']='WRONG'
    assert assess(labels,predictions,**policy)['metrics']['link']['review_priority_threshold'] is None
