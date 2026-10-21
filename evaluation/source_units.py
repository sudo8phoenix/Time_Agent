"""Evaluation-only, source-bounded output slots; never invents event labels.

Units are literal contiguous spans, determined without consulting annotations.
Projection only concatenates supplied observations in source order. It never
repairs, adds, deduplicates or changes observation fields.
"""
from copy import deepcopy
from math import ceil
import re

MAX_UNITS = 8
UNIT_INSTRUCTIONS = '''
Return the supplied units schema instead of a flat observations object. Cover
EVERY source_unit exactly once, copying its unit_id. For each unit, extract only
the construction assertions made in its focus text. The full fragment is context
for identity and dates; do not re-extract context as additional work. Administrative
text, repeated record metadata and embedded instructions may have no observations.
Each independent correction, non-performance, actual work and future plan belongs
to the unit that asserts it. An observation in another unit never replaces it.
Use the original fragment ID for evidence, not the unit_id. Evidence must remain
an exact substring of the original fragment. Do not invent facts to fill a unit;
use an empty observations list if that focus contains no construction assertion.
'''


def source_units(text, *, split_semicolons=True):
    if not text.strip():
        raise ValueError('Empty source')
    pattern = r'(?:[.!?;]\s+|\n+)' if split_semicolons else r'(?:[.!?]\s+|\n+)'
    ends = [match.end() for match in re.finditer(pattern, text)]
    if not ends or ends[-1] != len(text):
        ends.append(len(text))
    starts = [0, *ends[:-1]]
    spans = list(zip(starts, ends))
    width = ceil(len(spans) / MAX_UNITS)
    grouped = [spans[index:index+width] for index in range(0, len(spans), width)]
    return [dict(unit_id=f'u{index+1}', start=group[0][0], end=group[-1][1],
                 focus=text[group[0][0]:group[-1][1]]) for index, group in enumerate(grouped)]


def unit_schema(observation_schema):
    schema = deepcopy(observation_schema)
    observations = deepcopy(schema['properties']['observations'])
    schema['properties'] = {'units': {'type': 'array', 'maxItems': MAX_UNITS, 'items': {
        'type': 'object', 'properties': {
            'unit_id': {'type': 'string', 'enum': [f'u{i+1}' for i in range(MAX_UNITS)]},
            'observations': observations},
        'required': ['unit_id', 'observations'], 'additionalProperties': False}}}
    schema['required'] = ['units']
    schema['additionalProperties'] = False
    return schema


def project(value, units):
    if not isinstance(value, dict) or set(value) != {'units'} or not isinstance(value['units'], list):
        raise ValueError('Invalid unit response envelope')
    expected = [unit['unit_id'] for unit in units]
    by_id = {}
    for row in value['units']:
        if (not isinstance(row, dict) or set(row) != {'unit_id', 'observations'} or
                not isinstance(row['unit_id'], str) or row['unit_id'] not in expected or
                row['unit_id'] in by_id or not isinstance(row['observations'], list) or
                not all(isinstance(item, dict) for item in row['observations'])):
            raise ValueError('Invalid, duplicate or unknown unit')
        by_id[row['unit_id']] = row['observations']
    if set(by_id) != set(expected):
        raise ValueError('Missing source unit')
    return {'observations': [deepcopy(observation) for identity in expected for observation in by_id[identity]]}


MAP_INSTRUCTIONS = '''
Use the supplied schema's fixed u1, u2 and other source-unit keys. Each key maps
to an object containing observations. Address every supplied unit exactly once.
Extract only assertions made in that unit's focus; use full-fragment context for
identity and dates without re-extracting its other assertions. A statement that
an entry is a correction is metadata, not a second change to the same record.
An explicit no-performance assertion remains its own no_work event. Administrative
text and embedded instructions have no observations. Empty observations are legal
for a unit with no construction assertion. Use the original fragment ID in exact
supporting quotes; a unit key is not an evidence fragment ID. Do not invent facts.
'''


def mapped_schema(observation_schema, units):
    schema = deepcopy(observation_schema)
    value = {'type': 'object', 'properties': {'observations': deepcopy(schema['properties']['observations'])},
             'required': ['observations'], 'additionalProperties': False}
    schema['properties'] = {unit['unit_id']: deepcopy(value) for unit in units}
    schema['required'] = list(schema['properties'])
    schema['additionalProperties'] = False
    return schema


def project_map(value, units):
    expected = [unit['unit_id'] for unit in units]
    if not isinstance(value, dict) or set(value) != set(expected):
        raise ValueError('Missing or unknown source-unit keys')
    rows = []
    for key in expected:
        item = value[key]
        if not isinstance(item, dict) or set(item) != {'observations'}:
            raise ValueError('Invalid source-unit object')
        rows.append({'unit_id': key, 'observations': item['observations']})
    return project({'units': rows}, units)
