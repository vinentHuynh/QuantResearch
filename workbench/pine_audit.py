"""Audit Pine source without treating plotting indicators as trading systems."""
import hashlib
import re


EXISTING = {
    'SND_phase6_strategy.pine': ['scripts/mnq/SND_baseline_backtest.py', 'scripts/mnq/SND_phase6_release.py', 'scripts/mnq/SND_phase7_relative_volume.py', 'scripts/mnq/SND_phase6_strategy_parity.py'],
    'SND.pine': ['scripts/mnq/SND_baseline_backtest.py', 'scripts/mnq/SND_phase4_backtest.py', 'scripts/mnq/SND_phase5_combinations.py'],
    'pine/orb_carver.pine': ['scripts/orb/orb_carver_backtest.py'],
    'pine/orb.pine': ['strategy_engine/strategies/opening_range_breakout.py'],
    'pine/cme_tsmom_manual_indicator.pine': ['scripts/cme/cme_time_series_momentum_backtest.py'],
    'pine/overnight_block_indicator.pine': ['scripts/mnq/mnq_time_block_backtest.py'],
}


def inventory(root, strategies):
    entries = []
    for path in sorted([*root.glob('*.pine'), *(root / 'pine').rglob('*.pine')]):
        source = path.read_text(encoding='utf-8-sig')
        relative = path.relative_to(root).as_posix()
        declaration = re.search(r'^\s*(strategy|indicator)\s*\(\s*"([^"]+)"', source, re.M)
        if not declaration:
            raise ValueError(f'Cannot classify Pine declaration: {relative}')
        is_strategy = declaration[1] == 'strategy'
        adapters = [{'id': s['id'], 'name': s['name'], 'scope': s['migration_scope']} for s in strategies if relative in s.get('pine_sources', [])]
        existing = EXISTING.get(relative, [])
        for filename in existing:
            if not (root / filename).is_file():
                raise ValueError(f'Missing Python counterpart: {filename}')
        requirement = ('Existing supply/demand engine, Phase 6 release, Phase 7 RVOL filtering, and Strategy Tester comparison tooling. Reuse these implementations; full Phase 6/7 workbench execution remains separate. No new duplicate engine created.' if relative == 'SND_phase6_strategy.pine' else
                       'Python port available. See the adapter scope for daily feed, fill, and sizing differences; TradingView trade-export parity is not certified.' if adapters else
                       'Indicator with related Python research logic. Its drawings/alerts are not an independently specified entry-and-exit strategy.' if existing else
                       'Display/analysis indicator. No complete entry, exit, and sizing rules to port as a backtest; no trading strategy invented.')
        entries.append({
            'id': hashlib.sha256(relative.encode()).hexdigest()[:20], 'path': relative,
            'name': declaration[2], 'family': 'Pine strategies' if is_strategy else 'Pine indicators',
            'role': 'Pine strategy' if is_strategy else 'Pine indicator',
            'description': '\n'.join(line.removeprefix('//').strip() for line in source.splitlines()[:45] if line.startswith('//') and not line.startswith('//@')),
            'file_hash': hashlib.sha256(path.read_bytes()).hexdigest(),
            'functions': re.findall(r'^\s*(\w+)\([^\n]*\)\s*=>', source, re.M),
            'arguments': [{'flags': [m[1]], 'options': {'Pine declaration': m[2]}} for m in re.finditer(r'^\s*(?:\w+\s+)?(\w+)\s*=\s*(input\.\w+\([^\n]+)', source, re.M)],
            'adapters': adapters, 'python_counterparts': existing,
            'status': 'Python port available' if adapters else 'Existing Python engine' if is_strategy and existing else 'Indicator only',
            'requirements': requirement,
        })
    return entries
