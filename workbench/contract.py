"""Discovery never imports strategies. Only explicit worker runs execute code."""
import ast
import hashlib
import json
import math
import re
from pathlib import Path

PROTOCOL = 1


def checksum(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def metadata(path):
    tree = ast.parse(Path(path).read_text(encoding='utf-8'))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'STRATEGY' for t in node.targets):
            value = ast.literal_eval(node.value)
            if not re.fullmatch(r'[a-z][a-z0-9-]{1,80}', value['id']):
                raise ValueError('Strategy id must be lowercase words separated by hyphens')
            for key in ('name', 'description', 'parameters', 'timeframes'):
                if key not in value:
                    raise ValueError(f'Missing metadata: {key}')
            sources = value.get('legacy_sources', [])
            if not isinstance(sources, list) or any(
                not isinstance(source, str) or not source.endswith('.py') or
                source.startswith('/') or ':' in source or '\\' in source or
                '..' in source.split('/') for source in sources
            ):
                raise ValueError('legacy_sources must list repository-relative Python paths using forward slashes')
            if not isinstance(value.get('migration_scope', ''), str):
                raise ValueError('migration_scope must be a string')
            if value.get('execution_model', 'signals-v1') not in ('signals-v1', 'event-v1'):
                raise ValueError('Unsupported execution_model')
            pine = value.get('pine_sources', [])
            if not isinstance(pine, list) or any(not isinstance(s, str) or not s.endswith('.pine') or s.startswith('/') or ':' in s or '\\' in s or '..' in s.split('/') for s in pine):
                raise ValueError('pine_sources must list repository-relative .pine paths')
            warmup = value.get('default_warmup_days', 60)
            if type(warmup) is not int or not 0 <= warmup <= 1000:
                raise ValueError('default_warmup_days must be an integer from 0 to 1000')
            resolve_parameters(value, {})
            return value
    raise ValueError('Missing literal STRATEGY dictionary')


def resolve_parameters(spec, supplied):
    fields = spec['parameters']
    unknown = set(supplied) - set(fields)
    if unknown:
        raise ValueError(f'Unknown parameters: {sorted(unknown)}')
    result = {}
    for key, field in fields.items():
        value = supplied.get(key, field.get('default'))
        kind = field['type']
        valid = ((kind == 'integer' and type(value) is int) or
                 (kind == 'number' and type(value) in (int, float) and math.isfinite(value)) or
                 (kind == 'boolean' and type(value) is bool) or
                 (kind in ('string', 'enum') and isinstance(value, str)))
        if not valid:
            raise ValueError(f'{key}: expected {kind}')
        if kind in ('integer', 'number'):
            if value < field.get('minimum', -math.inf) or value > field.get('maximum', math.inf):
                raise ValueError(f'{key}: outside permitted range')
        if kind == 'enum' and value not in field['choices']:
            raise ValueError(f'{key}: unsupported choice')
        if isinstance(value, str) and len(value) > 2000:
            raise ValueError(f'{key}: string exceeds 2000 characters')
        result[key] = value
    for key, field in fields.items():
        condition = field.get('required_when', {})
        if condition and all(result.get(k) == v for k, v in condition.items()) and result[key] == '':
            raise ValueError(f'{key}: required for this configuration')
    return result


def discover(root):
    found, errors, ids = [], [], set()
    for path in sorted((Path(root) / 'strategies').glob('*.py')):
        if path.name.startswith('_'):
            continue
        try:
            spec = metadata(path)
            for source in spec.get('legacy_sources', []) + spec.get('pine_sources', []):
                if not (Path(root) / source).is_file():
                    raise ValueError(f'Original source not found: {source}')
            if spec['id'] in ids:
                raise ValueError('Duplicate strategy id')
            ids.add(spec['id'])
            found.append({**spec, 'file': str(path.relative_to(root)), 'file_hash': checksum(path)})
        except Exception as exc:
            errors.append({'file': path.name, 'error': str(exc)})
    from .library import inventory
    library = inventory(root, found)
    return {'strategies': found, 'errors': errors + library['errors'], 'library': library}


if __name__ == '__main__':
    import sys
    print(json.dumps(discover(Path(sys.argv[1]).resolve())))
