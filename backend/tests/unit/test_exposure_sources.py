import json

from evaluation.exposure_sources import inventory


def test_inventory_keeps_planned_lineage_and_never_opens_labels_or_exports_text(tmp_path):
    (tmp_path / 'inputs.json').write_text(json.dumps([{'case_id': 'c1', 'text': 'private source'}]))
    (tmp_path / 'labels.json').write_text('this must never be parsed or exported')
    (tmp_path / 'config.json').write_text(json.dumps({'schedule': [{'case_id': 'c2', 'trial_id': 'trial'}],
                                                    'prompts': {'system': 'private instructions'}}))
    (tmp_path / 'lineage.json').write_text(json.dumps({'cases': {'c1': {'group_id': 'family',
                                                                 'parent_fixture': 'older/c1'}}}))
    result = inventory([tmp_path])
    rendered = json.dumps(result)
    assert len(result['files']) == 3
    assert 'labels.json' not in rendered
    assert 'private source' not in rendered and 'private instructions' not in rendered
    assert 'older/c1' in rendered and 'c2' in rendered
    assert all(len(row['sha256']) == 64 for row in result['files'])


def test_invalid_source_is_reported_without_content(tmp_path):
    (tmp_path / 'inputs.json').write_text('sensitive malformed input')
    result = inventory([tmp_path])
    assert result['files'][0]['error']
    assert 'sensitive' not in json.dumps(result)
