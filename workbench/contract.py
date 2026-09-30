"""Static strategy discovery and protocol-v2 metadata normalization.

Discovery never imports strategies.  Protocol-v1 adapters and preserved source
snapshots did not declare ``schema_version`` or ``source_files``; they remain
readable and are normalized in memory.  New adapters declare their complete
local execution surface explicitly so snapshots need not include unrelated
research or application files.
"""
import ast
import hashlib
import json
import math
import re
from pathlib import Path

from .layout import load_layout


PROTOCOL = 2
LEGACY_PROTOCOL = 1
_DRIVE_PATH = re.compile(r'^[A-Za-z]:')


def checksum(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _repository_root(path):
    """Infer the snapshot/repository root without consulting the live checkout."""
    resolved = Path(path).resolve()
    for parent in resolved.parents:
        try:
            relative = resolved.relative_to(parent)
        except ValueError:
            continue
        if len(relative.parts) > 1 and relative.parts[0] == 'strategies':
            return parent
    return resolved.parent


def _relative_source(value, root, label='source_files'):
    if not isinstance(value, str) or not value:
        raise ValueError(f'{label} must contain nonempty strings')
    if (value.startswith('/') or _DRIVE_PATH.match(value) or '\\' in value or
            '//' in value or any(part in ('', '.', '..') for part in value.split('/'))):
        raise ValueError(f'{label} must list normalized repository-relative paths using forward slashes')
    candidate = (root / value).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError(f'{label} path escapes the repository: {value}') from exc
    if not candidate.is_file():
        raise ValueError(f'Execution source not found: {value}')
    return value


def _module_file(root, module):
    if not module:
        return None
    candidate = root.joinpath(*module.split('.'))
    source = candidate.with_suffix('.py')
    if source.is_file():
        return source
    package = candidate / '__init__.py'
    return package if package.is_file() else None


def _module_name(root, path):
    relative = path.relative_to(root).with_suffix('')
    parts = list(relative.parts)
    if parts and parts[-1] == '__init__':
        parts.pop()
    return '.'.join(parts)


def _package_initializers(root, path):
    found = []
    parent = path.parent
    while parent != root:
        init = parent / '__init__.py'
        if init.is_file():
            found.append(init)
        if root not in parent.parents:
            break
        parent = parent.parent
    return found


def _local_imports(root, path, top_level_only=False):
    """Return statically visible local imports without executing source code."""
    tree = ast.parse(path.read_text(encoding='utf-8-sig'))
    module = _module_name(root, path)
    package = module if path.name == '__init__.py' else module.rpartition('.')[0]
    found = []
    nodes = tree.body if top_level_only else ast.walk(tree)
    for node in nodes:
        modules = []
        if isinstance(node, ast.Import):
            modules = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                parts = package.split('.') if package else []
                keep = len(parts) - node.level + 1
                base_parts = parts[:max(0, keep)]
                if node.module:
                    base_parts.extend(node.module.split('.'))
                base = '.'.join(base_parts)
            else:
                base = node.module or ''
            modules = [base]
            modules.extend(
                f'{base}.{alias.name}' if base else alias.name
                for alias in node.names if alias.name != '*'
            )
        for name in modules:
            imported = _module_file(root, name)
            if imported is not None:
                for dependency in [imported, *_package_initializers(root, imported)]:
                    if dependency not in found:
                        found.append(dependency)
    return found


def _validate_dependency_closure(root, adapter, sources):
    """Require direct adapter imports and import-time dependencies of sources."""
    declared = {(root / source).resolve() for source in sources}
    required = {adapter, *_package_initializers(root, adapter)}
    required.update(_local_imports(root, adapter))
    for source in declared:
        if source.suffix == '.py' and source != adapter:
            required.update(_local_imports(root, source, top_level_only=True))
    missing = sorted(
        source.relative_to(root).as_posix()
        for source in required if source not in declared
    )
    if missing:
        raise ValueError(f'source_files is missing local execution dependencies: {missing}')


def _legacy_source_files(root, adapter):
    """Infer dependencies only for preserved v1 adapters lacking declarations.

    The inference is deliberately conservative and recursive.  V2 adapters use
    explicit declarations, which prevent unrelated imports in tooling modules
    from changing execution identity.
    """
    pending = [adapter]
    found = set()
    while pending:
        source = pending.pop()
        if source in found:
            continue
        found.add(source)
        pending.extend(item for item in _local_imports(root, source) if item not in found)
    return sorted(item.relative_to(root).as_posix() for item in found)


def metadata(path, root=None):
    source_path = Path(path).resolve()
    repository = Path(root).resolve() if root is not None else _repository_root(source_path)
    try:
        adapter = source_path.relative_to(repository).as_posix()
    except ValueError as exc:
        raise ValueError('Strategy adapter must be inside the repository or source snapshot') from exc
    tree = ast.parse(source_path.read_text(encoding='utf-8'))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'STRATEGY' for t in node.targets):
            value = dict(ast.literal_eval(node.value))
            schema = value.get('schema_version', LEGACY_PROTOCOL)
            if type(schema) is not int or schema not in (LEGACY_PROTOCOL, PROTOCOL):
                raise ValueError(f'Unsupported strategy metadata schema_version: {schema!r}')
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
            rule = value.get('warmup_bars')
            if rule is not None:
                if not isinstance(rule, dict) or set(rule) - {'parameter', 'multiplier', 'offset'}:
                    raise ValueError('warmup_bars must declare parameter, optional multiplier and offset')
                field = value['parameters'].get(rule.get('parameter'), {})
                if field.get('type') != 'integer' or field.get('minimum', 0) < 1:
                    raise ValueError('warmup_bars parameter must be a positive integer field')
                for key, default, lower in [('multiplier', 1, 1), ('offset', 0, 0)]:
                    number = rule.get(key, default)
                    if type(number) is not int or number < lower:
                        raise ValueError(f'warmup_bars {key} must be an integer >= {lower}')
            declared = value.get('source_files')
            if declared is None:
                if schema == PROTOCOL:
                    raise ValueError('Protocol-v2 strategy metadata requires source_files')
                sources = _legacy_source_files(repository, source_path)
            else:
                if not isinstance(declared, list) or not declared:
                    raise ValueError('source_files must be a nonempty list')
                sources = [_relative_source(item, repository) for item in declared]
                if len(sources) != len(set(sources)):
                    raise ValueError('source_files must not contain duplicates')
                if adapter not in sources:
                    raise ValueError(f'source_files must include its adapter: {adapter}')
                sources = sorted(sources)
                _validate_dependency_closure(repository, source_path, sources)
            value['schema_version'] = PROTOCOL
            value['source_files'] = sources
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
    root = Path(root).resolve()
    if (root / 'config' / 'workbench-layout.json').is_file():
        adapter_roots = load_layout(root).discovery_paths['strategy_adapters']
    else:
        # Source snapshots and small test fixtures predate the checked-in layout.
        adapter_roots = (root / 'strategies',)
    found, errors, ids = [], [], set()
    paths = sorted({path for folder in adapter_roots for path in folder.glob('*.py')})
    for path in paths:
        if path.name.startswith('_'):
            continue
        try:
            spec = metadata(path, root)
            for source in spec.get('legacy_sources', []) + spec.get('pine_sources', []):
                if not (Path(root) / source).is_file():
                    raise ValueError(f'Original source not found: {source}')
            if spec['id'] in ids:
                raise ValueError('Duplicate strategy id')
            ids.add(spec['id'])
            found.append({**spec, 'file': path.relative_to(root).as_posix(), 'file_hash': checksum(path)})
        except Exception as exc:
            errors.append({'file': path.name, 'error': str(exc)})
    from .library import inventory
    library = inventory(root, found)
    return {'strategies': found, 'errors': errors + library['errors'], 'library': library}


if __name__ == '__main__':
    import sys
    print(json.dumps(discover(Path(sys.argv[1]).resolve())))
