"""Build the selected source bundle from verified local research and source files."""
from pathlib import Path
import datetime
import hashlib
import json
import shutil
import zipfile

ROOT = Path(__file__).resolve().parents[1]
FOLDER = ROOT / 'ninjatrader/selected_mnq'
REPORT = ROOT / 'reports/tsmom-orb-fix-2026-09-29'
NAMES = ['WorkbenchMnqMinuteReversal.cs', 'WorkbenchMnqReversalCore.cs',
         'WorkbenchMnqOvernightBlock.cs', 'WorkbenchMnqOvernightRules.cs',
         'WorkbenchMnqTsmomOrb.cs', 'WorkbenchMnqTsmomOrbCore.cs']


def main():
    results = json.loads((REPORT / 'results.json').read_text())
    assert results['all_attempts_terminal'] and results['current_cases_all_checks_pass']
    assert results['current_source_behavior_supported']
    focused = json.loads((REPORT / 'focused-checks.json').read_text())
    assert all(r['exit_code'] == 0 for r in focused)
    realdata = REPORT / 'orb-core-realdata.json'
    if not realdata.exists():
        raise RuntimeError('Real-data C# differential report is required before packaging')
    realdata_report = json.loads(realdata.read_text())
    assert realdata_report['result'] == 'PASS'
    assert realdata_report['source_unchanged_during_test']
    for path, expected in realdata_report['source_sha256'].items():
        assert hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == expected, path
    assert results['results'] and all(
        r['calendar_audit']['overnight_carry_count'] == 0 for r in results['results'])
    (FOLDER / 'Strategies').mkdir(parents=True, exist_ok=True)
    files = []
    for name in NAMES:
        source = ROOT / 'ninjatrader' / name
        destination = FOLDER / 'Strategies' / name
        shutil.copy2(source, destination)
        files.append(dict(file='Strategies/' + name, sha256=hashlib.sha256(source.read_bytes()).hexdigest()))
    copies = {
        ROOT / 'reports/overnight-comparison-2026-09-29/README.md': 'overnight-comparison.md',
        ROOT / 'reports/overnight-comparison-2026-09-29/comparison.json': 'overnight-comparison.json',
        REPORT / 'results.json': 'orb-results.json',
        REPORT / 'campaign.json': 'orb-campaign.json',
        REPORT / 'focused-checks.json': 'focused-checks.json',
        REPORT / 'broader-checks.json': 'broader-checks.json',
        REPORT / 'compile.log': 'compile.log',
        REPORT / 'python-calendar-nextopen-tests.log': 'python-calendar-nextopen-tests.log',
        REPORT / 'csharp-orb-tests.log': 'csharp-orb-tests.log',
        realdata: 'orb-core-realdata.json',
        ROOT / 'ninjatrader/working_nq_to_mnq/selection.json': 'source-selection-original.json',
        ROOT / 'ninjatrader/working_nq_to_mnq/reversal-validation.json': 'reversal-validation.json',
    }
    for source, name in copies.items():
        shutil.copy2(source, FOLDER / name)
    md = (REPORT / 'RESULTS.md').read_text(encoding='utf-8')
    md = md.replace('(results.json)', '(orb-results.json)')
    md = md.replace('(../../ninjatrader/working_nq_to_mnq/selection.json)', '(source-selection-original.json)')
    (FOLDER / 'orb-results.md').write_text(md, encoding='utf-8')
    manifest = {
        'created_at_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'selected_strategies': ['WorkbenchMnqOvernightBlock', 'WorkbenchMnqMinuteReversal', 'WorkbenchMnqTsmomOrb'],
        'overnight_selection': 'Block won the matched actual-MNQ compiled-clock comparison; Session left installed as an unselected alternate.',
        'compile': {'platform': 'Installed NinjaTrader 8.1.8.2 Core/Gui/Custom assemblies', 'errors': 0, 'warnings': 0},
        'checks': focused,
        'historical_current_orb_cases_passed': results['current_case_count'],
        'historical_orb_attempts_retained': results['attempt_count'],
        'zero_overnight_carries': True,
        'orb_core_historical_differential': {
            'result': realdata_report['result'],
            'decisions_compared': realdata_report['compared_bars'],
            'scope': realdata_report['scope'],
        },
        'broader_checks': json.loads((REPORT / 'broader-checks.json').read_text()),
        'native_ninjatrader_backtest_or_playback_verified': False,
        'accounts_selected_or_strategies_enabled': False,
        'limits': 'Historical replay on previously inspected data; fills, orders, calendar updates and live profitability remain unverified.',
        'files': files,
    }
    (FOLDER / 'validation.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    archive = ROOT / 'ninjatrader/Selected_MNQ_NinjaTrader8.zip'
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as z:
        for path in sorted(FOLDER.rglob('*')):
            if path.is_file() and not any(part.startswith('install-backup-') for part in path.relative_to(FOLDER).parts):
                z.write(path, path.relative_to(FOLDER).as_posix())
    with zipfile.ZipFile(archive) as z:
        assert z.testzip() is None
        assert len([name for name in z.namelist() if name.endswith('.cs')]) == len(NAMES)
        for item in files:
            assert hashlib.sha256(z.read(item['file'])).hexdigest() == item['sha256']
    print(json.dumps(dict(archive=str(archive), bytes=archive.stat().st_size,
                         strategies=manifest['selected_strategies'], checksums_verified=True), indent=2))


if __name__ == '__main__':
    main()
