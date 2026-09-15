"""Non-executing inventory of research source files and their workbench adapters.

Keep originals in place: sibling imports and historical reports depend on their paths.
An adapter link describes provenance, never a claim of backtest equivalence.
"""
import ast
import hashlib
from collections import Counter
from pathlib import Path


FAMILIES = {
    'cme': 'Momentum and portfolios', 'es_nq': 'Index signals',
    'orb': 'Opening range', 'mgc': 'Gold sessions', 'overnight': 'Overnight',
    'spy_qqq_intraday': 'ETF intraday', 'lucid': 'Prop account studies',
    'ninjatrader': 'Platform validation', 'misc': 'Support',
}

# These files contain rules as well as research/reporting machinery. Do not lose
# them through filename heuristics such as treating every "screen" as a utility.
RULE_COLLECTIONS = {
    'short_horizon_backtest', 'es_nq_strategies', 'intraday_bakeoff',
    'intraday_strategy_screen', 'SND_phase4_backtest', 'SND_phase5_combinations',
    'SND_phase7_relative_volume', 'mnq_scenario_grid', 'mnq_optimal_stop_search',
    'mnq_window_scan_backtest', 'mnq_orb_recency', 'mnq_orb_2026_review',
}
STUDIES = {'es_nq_terms', 'mnq_ny_close_asia_fill_backtest', 'SND_phase3_screen',
           'lucid_prop_year_sim', 'lucid_container_scan'}


def role(path):
    stem = path.stem
    name = stem.lower()
    if path.parent.name == 'strategies':
        return 'Strategy'
    if stem in RULE_COLLECTIONS:
        return 'Rule collection'
    if stem in STUDIES:
        return 'Research study'
    if name.startswith(('fetch', 'build', 'export', 'databento_fetch', 'probe_')):
        return 'Data utility'
    if name == 'dashboard_compatible_strategy':
        return 'Support'
    if any(word in name for word in ('verify', 'parity', 'crosscheck', 'smoke_test', 'sizing_check', 'prop_fit_check', 'forward_check', 'release')):
        return 'Validation'
    if any(word in name for word in ('report', 'dashboard', 'playbook', 'loss_profile')):
        return 'Report'
    if 'backtest' in name or 'strategy' in name:
        return 'Strategy'
    if 'dataset' in name:
        return 'Data utility'
    return 'Support'


def family(path):
    if path.parent.name == 'strategies':
        return 'Canonical engine'
    if path.parent.name == 'mnq':
        if path.stem.startswith('SND_'):
            return 'Supply and demand'
        if 'asia' in path.stem:
            return 'Asia gap fill'
        if 'profile' in path.stem:
            return 'Market profile'
        if any(x in path.stem for x in ('orb', 'opening')):
            return 'Opening range'
        return 'MNQ overnight variants'
    return FAMILIES.get(path.parent.name, 'Support')


def requirements(path, category):
    if category not in ('Strategy', 'Rule collection', 'Research study'):
        return 'Supporting source; not a standalone trading strategy.'
    name, folder = path.stem, path.parent.name
    if folder == 'strategies':
        return 'Canonical engine implementation. Unlinked rules need a workbench adapter for their multi-leg or intrabar execution contract.'
    if name == 'factor_ls_backtest':
        return 'Requires the equity factor panel, borrow costs, and a multi-asset runner; futures OHLCV cannot replace factor data.'
    if name in ('commodity_xsec_momentum_backtest', 'trend_overnight_book_backtest', 'short_horizon_backtest'):
        return 'Requires the original multi-instrument inputs and portfolio accounting adapter.'
    if folder in ('cme', 'es_nq'):
        return 'Original workflow uses PWB cash/commodity or ETF proxies. Full reproduction requires those inputs and its sizing/accounting adapter.'
    if folder == 'spy_qqq_intraday' or name == 'orb_backtest':
        return 'Requires cached SPY/QQQ bars and the original ETF execution/accounting adapter; NQ/ES futures are different instruments.'
    if folder == 'mgc':
        return 'Requires MGC data and the original intrabar/session execution and sizing adapter.'
    if name.startswith('SND_'):
        return 'Requires supply/demand zone construction, bracket fills, and the original multi-timeframe execution adapter.'
    if 'profile' in name:
        return 'Requires market-profile construction and intrabar value-area/nPOC fill accounting.'
    if 'asia_fill' in name:
        return 'Requires reference-close matching and stop/limit/deadline execution with its original fill assumptions.'
    if folder == 'lucid':
        return 'Requires the original trade inputs and prop-account rules; this is an account study.'
    return 'Requires the original session, intrabar fill, sizing, and/or study adapter. A next-open bar signal is not an equivalent replacement.'


def inventory(root, strategies):
    root = Path(root).resolve()
    links = {}
    for strategy in strategies:
        for source in strategy.get('legacy_sources', []):
            links.setdefault(source, []).append({
                'id': strategy['id'], 'name': strategy['name'],
                'scope': strategy.get('migration_scope', 'Signal adapter; original backtest parity not established.'),
            })
    paths = sorted({*root.glob('*.py'), *(root / 'scripts').rglob('*.py'),
                    *(root / 'ninjatrader').rglob('*.py'),
                    *(root / 'strategy_engine' / 'strategies').glob('*.py')})
    entries, errors = [], []
    for path in paths:
        if '__pycache__' in path.parts or path.name == '__init__.py':
            continue
        relative = path.relative_to(root).as_posix()
        try:
            raw = path.read_bytes()
            tree = ast.parse(raw.decode('utf-8-sig'))
            category = role(path)
            doc = ast.get_docstring(tree) or ''
            title = next((line.strip() for line in doc.splitlines() if line.strip()), path.stem.replace('_', ' '))
            functions = [node.name for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
            cli = []
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == 'add_argument':
                    flags = [a.value for a in node.args if isinstance(a, ast.Constant) and isinstance(a.value, str) and a.value.startswith('--')]
                    if flags:
                        cli.append({'flags': flags, 'options': {kw.arg: ast.unparse(kw.value) for kw in node.keywords if kw.arg in ('default', 'choices', 'type', 'action', 'help')}})
            adapters = links.get(relative, [])
            entries.append({
                'id': hashlib.sha256(relative.encode()).hexdigest()[:20],
                'path': relative, 'name': title, 'description': doc, 'family': family(path),
                'role': category, 'file_hash': hashlib.sha256(raw).hexdigest(),
                'functions': functions, 'arguments': cli, 'adapters': adapters,
                'status': 'Workbench adapter available' if adapters else 'Adapter required' if category in ('Strategy', 'Rule collection', 'Research study') else 'Supporting source',
                'requirements': requirements(path, category),
            })
        except (OSError, UnicodeError, SyntaxError) as exc:
            errors.append({'file': relative, 'error': str(exc)})
    from .pine_audit import inventory as pine_inventory
    entries.extend(pine_inventory(root, strategies))
    return {'entries': entries, 'counts': dict(Counter(e['role'] for e in entries)),
            'total': len(entries), 'errors': errors}


def markdown_report(result):
    def cell(value):
        return str(value).replace('|', '\\|').replace('\n', ' ')
    library = result['library']
    lines = ['# Consolidated strategy library', '',
             'Generated from local Python and Pine source using static parsing; discovery does not execute scripts.', '',
             f"{library['total']} Python and Pine sources; {len(result['strategies'])} runnable workbench adapters.", '',
             '## Runnable adapters', '',
             '| Strategy | Parameters | Migration scope |', '| --- | --- | --- |']
    for spec in result['strategies']:
        lines.append(f"| [{cell(spec['name'])}]({Path(spec['file']).as_posix()}) | {cell(', '.join(spec['parameters']))} | {cell(spec.get('migration_scope', 'New workbench strategy'))} |")
    lines += ['', '## Original source inventory', '',
              'Adapter links cover only the documented rules. Other variants within the same script still require migration.', '',
              '| Source | Family | Role | Status | Workbench adapters |', '| --- | --- | --- | --- | --- |']
    for entry in library['entries']:
        adapters = ', '.join(a['id'] for a in entry['adapters']) or '—'
        lines.append(f"| [{entry['path']}]({entry['path']}) | {cell(entry['family'])} | {entry['role']} | {entry['status']} | {adapters} |")
    lines += ['', '## Remaining execution contracts', '',
              '- Intrabar strategies: preserve stop/limit ordering, gap handling, deadlines, and sizing; the current signal runner only fills at the next bar open.',
              '- Multi-instrument strategies: require synchronized legs and portfolio accounting.',
              '- Factor and ETF strategies: require their original inputs. The four normalized futures ZIP datasets are not substitutes.',
              '- Research studies: require their original selection, resampling, and report workflows in addition to signal rules.', '',
              'The Scripts page shows per-source requirements, source hashes, original documentation, functions, and CLI declarations.',
              'Refresh this report with `python -m workbench.library --output STRATEGY_LIBRARY.md`.', '']
    return '\n'.join(lines)


if __name__ == '__main__':
    import argparse
    from .contract import discover
    parser = argparse.ArgumentParser(description='Export the consolidated source inventory')
    parser.add_argument('--root', type=Path, default=Path.cwd())
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = discover(args.root.resolve())
    if result['errors']:
        raise SystemExit(str(result['errors']))
    args.output.write_text(markdown_report(result), encoding='utf-8')
    print(f"Exported {result['library']['total']} sources and {len(result['strategies'])} adapters to {args.output}")
