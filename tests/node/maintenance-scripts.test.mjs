import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import test from 'node:test';

import {
  LARGE_FILE_ALLOWLIST,
  auditTrackedFiles,
  generatedPathReason,
} from '../../scripts/check-repo-hygiene.mjs';
import {
  parseDocumentedRuntimeTargets,
  parseRequirements,
  satisfiesVersion,
} from '../../scripts/doctor.mjs';

test('generated paths cover output roots and caches without matching normal source', () => {
  assert.equal(generatedPathReason('reports/campaign/result.json'), 'generated research reports');
  assert.equal(generatedPathReason('Reports/campaign/result.json'), 'generated research reports');
  assert.equal(generatedPathReason('src\\__pycache__\\module.pyc'), 'cache directory (__pycache__)');
  assert.equal(generatedPathReason('tmp/run.log'), 'temporary output');
  assert.equal(generatedPathReason('src/features/runs.ts'), null);
});

test('hygiene audit permits only exact approved large fixture paths', () => {
  const approved = [...LARGE_FILE_ALLOWLIST][0];
  const report = auditTrackedFiles(
    [
      { path: approved, size: 20 },
      { path: 'data/mnq_dom_sample/unreviewed.parquet', size: 20 },
      { path: 'src/index.ts', size: 3 },
    ],
    { largeFileLimitBytes: 10 },
  );

  assert.equal(report.ok, false);
  assert.deepEqual(report.allowedLarge, [{ path: approved, size: 20 }]);
  assert.deepEqual(report.oversized, [
    { path: 'data/mnq_dom_sample/unreviewed.parquet', size: 20 },
  ]);
});

test('hygiene audit rejects generated paths independently of file size', () => {
  const report = auditTrackedFiles([
    { path: 'reports/small.json', size: 1 },
    { path: 'src/main.ts', size: 1 },
  ]);
  assert.equal(report.ok, false);
  assert.equal(report.generated.length, 1);
  assert.equal(report.generated[0].path, 'reports/small.json');
});

test('version checks support runtime floors and package ranges', () => {
  assert.equal(satisfiesVersion('24.1.0', '>=24'), true);
  assert.equal(satisfiesVersion('23.9.0', '>=24'), false);
  assert.equal(satisfiesVersion('8.4.0', '^8.3.1'), true);
  assert.equal(satisfiesVersion('9.0.0', '^8.3.1'), false);
  assert.equal(satisfiesVersion('5.8.4', '~5.8.3'), true);
  assert.equal(satisfiesVersion('5.9.0', '~5.8.3'), false);
  assert.equal(satisfiesVersion('0.116.2', '>=0.116,<1'), true);
});

test('doctor parsers derive targets from maintained project files', () => {
  assert.deepEqual(
    parseDocumentedRuntimeTargets('Requires Node 24+ and Python 3.12. From the repository root:'),
    { node: '>=24', python: '>=3.12' },
  );
  assert.deepEqual(
    Object.fromEntries(
      parseRequirements('pandas==3.0.5\nuvicorn[standard]>=0.35,<1\n# comment\n'),
    ),
    { pandas: '==3.0.5', uvicorn: '>=0.35,<1' },
  );
});

test('documented research validation commands use configured state and artifact roots', () => {
  const root = resolve(import.meta.dirname, '..', '..');
  for (const relative of [
    'scripts/analyze-orb-exits.py',
    'scripts/validate-2026.mjs',
    'scripts/validate-potential.mjs',
  ]) {
    const source = readFileSync(resolve(root, relative), 'utf8');
    assert.match(source, /load(?:WorkbenchLayout|_layout)/, relative);
    assert.doesNotMatch(source, /["']reports\//, relative);
    assert.doesNotMatch(source, /["']data\/workbench/, relative);
  }

  const orb = readFileSync(resolve(root, 'scripts/analyze-orb-exits.py'), 'utf8');
  assert.match(orb, /resolve_dataset_path\(dataset, STATE_ROOT\)/);
  assert.match(orb, /LAYOUT\.artifacts_root \/ 'research'/);

  for (const relative of [
    'scripts/validate-2026.mjs',
    'scripts/validate-potential.mjs',
  ]) {
    const source = readFileSync(resolve(root, relative), 'utf8');
    assert.match(source, /layout\.artifactsRoot/, relative);
    assert.match(source, /layout\.stateRoot/, relative);
  }
});
