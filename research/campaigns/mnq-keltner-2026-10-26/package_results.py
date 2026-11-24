"""Package the verified study outputs without copying the source market dataset."""
from pathlib import Path
from datetime import datetime, timezone
import gzip
import hashlib
import json
import shutil
import zipfile

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
OUT = ROOT / 'artifacts/mnq-keltner-2026-10-26'
REPORT = ROOT / 'reports/mnq-keltner-2026-10-26'
EVIDENCE = ROOT / 'evidence/campaigns/mnq-keltner-2026-10-26'


def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):
            h.update(chunk)
    return h.hexdigest()


def main():
    pdf=REPORT/'MNQ_Keltner_Statistical_Report.pdf'
    assert pdf.exists()
    audit=json.loads((OUT/'independent_audit.json').read_text())
    result=json.loads((OUT/'statistical_result.json').read_text())
    assert result['directional_claims']==0
    readme='''MNQ KELTNER CANDLE-SIZE STUDY - 26 OCTOBER 2026

Read the separate MNQ_Keltner_Statistical_Report.pdf first.
This package contains statistical tables, full event/control CSV ledgers,
frozen protocol, reproducible research source, and audit evidence.

Scope: MNQ 5m/15m, all Globex sessions, EMA(close,20), SMA(true range,20),
2.25 ATR bands. Sizing means candle range, wick length and extension depth.
History: 2019-05-05 to 2026-09-03. Later test: 2025-01-01 onward.
No position sizing, trade-execution simulation or profit claim is included.

RESULT: 0/16 predeclared extension cells passed the historical criteria.
The broad 0.5-ATR/60-minute reversion shares are near 50%.
Secondary effects and all sparse/adverse cells remain visible.

IMPORTANT CONTROL DIAGNOSTIC:
The initial matched-control comparisons are contaminated when an earlier
control's forward window includes the subsequently selected breach candle.
Do not use positive control_difference fields as supporting evidence.
control_overlap_sensitivity.csv excludes overlap from the SAME frozen matches,
without rematching. Every test-period interval then includes zero.
This is a post-protocol diagnostic, not new confirmatory validation.

HOW TO READ THE TABLES:
- primary_summary.csv: full fixed extension grid across all periods.
- size_summary.csv: close extension, whole/outside wick, range, proportions,
  and prior-ATR denominator sensitivity; these are exploratory marginal slices.
- horizon/session/side/year/cohort/trend/open_state summaries: other views.
- p_reversion: reversion / (reversion + continuation), a conditional share.
- decisive excludes unresolved, ambiguous and incomplete windows.
- ambiguity_bound_low/high assign every ambiguous touch against/for reversion;
  these are empirical identification bounds, not confidence intervals.
- return columns: positive means continuation, negative means reversion.
- *_touch and band_return: reaching or passing frozen levels, including entry
  gaps; not necessarily later traded touches.
- 'all' split pools the entire history and is descriptive only.
- timeframe is minutes. Clock/session labels use America/Chicago.
- bins include the left endpoint and exclude the right endpoint.
- 1+ means at least one ATR. 20-point ATR is an illustrative example in PDF.
- control_id keys a source chart candle and event-side direction; repeated
  controls share their original-day bootstrap weights.

The two timeframes and repeated events share underlying prices. Treat neither
row counts nor overlapping horizons as independent replications. The cache's
original vendor acquisition receipt is unverified. Roll reset/complete-window
rules are documented in protocol.json and audit.json.

REPRODUCTION IN THE ORIGINAL QUANT WORKSPACE:
1. .venv/Scripts/python.exe research/campaigns/mnq-keltner-2026-10-26/build_events.py --self-test
2. Run build_events.py without --self-test to rebuild the ledgers.
3. Run analyze.py, then control_overlap_audit.py.
4. Run report.py --charts using the analysis environment and --pdf using the
   bundled reportlab environment. Raw data must match protocol's SHA-256.
Source commands write into the campaign's artifacts/report folders.
The original acquisition dataset is not included in this export.

The first generator attempt is preserved locally under
artifacts/mnq-keltner-2026-10-26/attempt-01-initial.
Its correction affected control matching only; signal features and outcomes
were bit-identical. attempts.json retains that history and checksums.
'''
    (REPORT/'READ_ME.txt').write_text(readme,encoding='utf-8')
    archive=REPORT/'MNQ_Keltner_Tables_and_Event_Data.zip'
    packaged=[]
    with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        z.writestr('READ_ME.txt',readme)
        for path in sorted(OUT.glob('*_summary.csv')) + [OUT/'control_overlap_sensitivity.csv']:
            z.write(path,'tables/'+path.name)
            packaged.append({'path':'tables/'+path.name,'sha256':digest(path)})
        for path in sorted(OUT.glob('*.csv.gz')):
            name='ledgers/'+path.name[:-3]
            h=hashlib.sha256()
            with gzip.open(path,'rb') as src, z.open(name,'w',force_zip64=True) as dst:
                for chunk in iter(lambda:src.read(1024*1024),b''):
                    h.update(chunk); dst.write(chunk)
            packaged.append({'path':name,'sha256':h.hexdigest()})
        for path in sorted(HERE.glob('*.py'))+[HERE/'protocol.json']:
            z.write(path,'source/'+path.name)
            packaged.append({'path':'source/'+path.name,'sha256':digest(path)})
        for name in ['audit.json','statistical_result.json','independent_audit.json','calendar.json','attempts.json']:
            path=OUT/name
            z.write(path,'audit/'+name)
            packaged.append({'path':'audit/'+name,'sha256':digest(path)})
        quality=REPORT/'report_quality.json'
        z.write(quality,'audit/'+quality.name)
        packaged.append({'path':'audit/'+quality.name,'sha256':digest(quality)})
        z.writestr('package_manifest.json',json.dumps({'files':packaged},indent=2))
    with zipfile.ZipFile(archive) as z:
        assert z.testzip() is None
    EVIDENCE.mkdir(parents=True,exist_ok=True)
    files=list(OUT.glob('*_summary.csv'))+[OUT/'control_overlap_sensitivity.csv',OUT/'audit.json',OUT/'independent_audit.json',OUT/'statistical_result.json',OUT/'attempts.json',REPORT/'report_quality.json',pdf,archive]
    manifest={
        'study_id':'mnq-keltner-2026-10-26','created_at':datetime.now(timezone.utc).isoformat(),
        'disposition':'No validated candle-extension size sweet spot under the frozen primary criteria; 0 of 16 cells pass.',
        'stage':'Custom historical event study; no faithful KC workbench adapter or strategy milestone promotion.',
        'control_limitation':'Original matched controls can overlap signal candles; retain original fields as failed diagnostic only. Same-match nonoverlap sensitivity is post-protocol and all test intervals include zero.',
        'protocol_sha256':digest(HERE/'protocol.json'),
        'dataset_sha256':json.loads((HERE/'protocol.json').read_text())['dataset_sha256'],
        'primary_test_cells':16,'directional_claims':0,
        'files':[{'path':str(p.relative_to(ROOT)).replace('\\','/'),'sha256':digest(p),'bytes':p.stat().st_size} for p in sorted(files)],
        'sources':[{'path':str(p.relative_to(ROOT)).replace('\\','/'),'sha256':digest(p)} for p in sorted(HERE.glob('*.py'))]
    }
    (EVIDENCE/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    (OUT/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    print(json.dumps({'pdf':str(pdf),'archive':str(archive),'archive_mb':round(archive.stat().st_size/1e6,1),'files':len(packaged),'manifest':str(EVIDENCE/'manifest.json')},indent=2))


if __name__=='__main__':
    main()
