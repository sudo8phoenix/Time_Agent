"""Equivalent wire representation diagnostic; production schema is unchanged."""
from copy import deepcopy


def explicit_multi_unions(schema):
    """Express unions with >2 primitives as anyOf, retaining the accepted values."""
    changes = []
    def visit(node, path):
        if isinstance(node, list):
            return [visit(v, path+'/'+str(i)) for i, v in enumerate(node)]
        if not isinstance(node, dict):
            return node
        result = {k: visit(v, path+'/'+k) for k, v in node.items()}
        types = result.get('type')
        if isinstance(types, list) and len(types) > 2:
            if not all(t in {'string', 'number', 'integer', 'boolean', 'null'} for t in types):
                raise ValueError('Only primitive unions supported')
            result.pop('type')
            result['anyOf'] = [{'type': t} for t in types]
            changes.append(dict(path=path, before={'type': deepcopy(types)},
                                after={'anyOf': deepcopy(result['anyOf'])}))
        return result
    return visit(schema, '#'), changes
