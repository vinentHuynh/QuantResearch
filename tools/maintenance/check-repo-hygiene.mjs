import { lstatSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

export const LARGE_FILE_LIMIT_BYTES = 5 * 1024 * 1024;

// These are the only large, repository-owned fixture files. Keep this list at
// file granularity so adding another file below data/mnq_dom_sample still needs
// an explicit review.
export const LARGE_FILE_ALLOWLIST = new Set([
  'data/mnq_dom_sample/full_history/ohlcv-1m/candles_1m.parquet',
  'data/mnq_dom_sample/full_history/ohlcv-resampled/candles_1d.parquet',
  'data/mnq_dom_sample/full_history/ohlcv-resampled/candles_1h.parquet',
  'data/mnq_dom_sample/full_history/ohlcv-resampled/candles_30m.parquet',
  'data/mnq_dom_sample/full_history/ohlcv-resampled/candles_4h.parquet',
  'data/mnq_dom_sample/full_history/ohlcv-resampled/candles_5m.parquet',
]);

const GENERATED_ROOTS = new Map([
  ['.codex-skill-staging', 'temporary skill staging'],
  ['artifacts', 'raw/generated artifacts'],
  ['build', 'build output'],
  ['coverage', 'test coverage output'],
  ['dist', 'build output'],
  ['node_modules', 'installed dependencies'],
  ['reports', 'generated research reports'],
  ['tmp', 'temporary output'],
]);

const CACHE_SEGMENTS = new Set([
  '.cache',
  '.mypy_cache',
  '.parcel-cache',
  '.pytest_cache',
  '.ruff_cache',
  '.turbo',
  '.vite',
  '__pycache__',
]);

export function normalizeTrackedPath(filePath) {
  return filePath.replaceAll('\\', '/').replace(/^\.\//, '');
}

export function generatedPathReason(filePath) {
  const normalized = normalizeTrackedPath(filePath);
  const segments = normalized.split('/');
  const rootReason = GENERATED_ROOTS.get(segments[0].toLowerCase());
  if (rootReason) {
    return rootReason;
  }

  const cacheSegment = segments.find(segment => CACHE_SEGMENTS.has(segment.toLowerCase()));
  if (cacheSegment) {
    return `cache directory (${cacheSegment})`;
  }

  const name = segments.at(-1) ?? '';
  if (/\.(?:py[co]|tsbuildinfo)$/i.test(name) || name === '.eslintcache') {
    return 'generated cache file';
  }

  return null;
}

export function auditTrackedFiles(
  trackedFiles,
  {
    largeFileLimitBytes = LARGE_FILE_LIMIT_BYTES,
    largeFileAllowlist = LARGE_FILE_ALLOWLIST,
  } = {},
) {
  const generated = [];
  const oversized = [];
  const allowedLarge = [];

  for (const entry of trackedFiles) {
    const path = normalizeTrackedPath(entry.path);
    const generatedReason = generatedPathReason(path);
    if (generatedReason) {
      generated.push({ path, reason: generatedReason });
    }

    if (entry.size > largeFileLimitBytes) {
      if (largeFileAllowlist.has(path)) {
        allowedLarge.push({ path, size: entry.size });
      } else {
        oversized.push({ path, size: entry.size });
      }
    }
  }

  const byPath = (left, right) => left.path.localeCompare(right.path);
  generated.sort(byPath);
  oversized.sort(byPath);
  allowedLarge.sort(byPath);

  return {
    ok: generated.length === 0 && oversized.length === 0,
    generated,
    oversized,
    allowedLarge,
    checkedCount: trackedFiles.length,
    largeFileLimitBytes,
  };
}

function runGit(repoRoot, args, options = {}) {
  const result = spawnSync('git', args, {
    cwd: repoRoot,
    encoding: options.encoding ?? 'utf8',
    maxBuffer: 64 * 1024 * 1024,
    windowsHide: true,
    ...options,
  });

  if (result.error) {
    throw new Error(`Could not run git ${args.join(' ')}: ${result.error.message}`);
  }
  if (result.status !== 0) {
    const detail = String(result.stderr || result.stdout || '').trim();
    throw new Error(`git ${args.join(' ')} failed${detail ? `: ${detail}` : ''}`);
  }
  return result.stdout;
}

function sizeFromIndex(repoRoot, filePath) {
  const result = spawnSync('git', ['cat-file', '-s', `:${filePath}`], {
    cwd: repoRoot,
    encoding: 'utf8',
    maxBuffer: 1024 * 1024,
    windowsHide: true,
  });
  if (result.error || result.status !== 0) {
    return null;
  }
  const size = Number.parseInt(result.stdout.trim(), 10);
  return Number.isFinite(size) ? size : null;
}

export function collectTrackedFiles(repoRoot) {
  const output = runGit(repoRoot, ['ls-files', '-z'], { encoding: 'buffer' });
  return output
    .toString('utf8')
    .split('\0')
    .filter(Boolean)
    .map(filePath => {
      const normalized = normalizeTrackedPath(filePath);
      let size;
      try {
        size = lstatSync(join(repoRoot, ...normalized.split('/'))).size;
      } catch {
        size = sizeFromIndex(repoRoot, normalized);
      }
      return { path: normalized, size: size ?? 0 };
    });
}

function formatBytes(bytes) {
  if (bytes < 1024) {
    return `${bytes} B`;
  }
  const units = ['KiB', 'MiB', 'GiB'];
  let value = bytes / 1024;
  let unit = units[0];
  for (let index = 1; index < units.length && value >= 1024; index += 1) {
    value /= 1024;
    unit = units[index];
  }
  return `${value.toFixed(1)} ${unit}`;
}

function printEntries(entries, formatter, maxEntries = 50) {
  for (const entry of entries.slice(0, maxEntries)) {
    console.error(`  - ${formatter(entry)}`);
  }
  if (entries.length > maxEntries) {
    console.error(`  ... ${entries.length - maxEntries} more`);
  }
}

export function printHygieneReport(report) {
  if (report.ok) {
    console.log(
      `Repository hygiene check passed: ${report.checkedCount} tracked files; ` +
        `${report.allowedLarge.length} approved large fixture file(s).`,
    );
    return;
  }

  console.error('Repository hygiene check failed.');
  if (report.generated.length > 0) {
    console.error(`Tracked generated paths (${report.generated.length}):`);
    printEntries(report.generated, entry => `${entry.path} — ${entry.reason}`);
  }
  if (report.oversized.length > 0) {
    console.error(
      `Unapproved tracked files larger than ${formatBytes(report.largeFileLimitBytes)} ` +
        `(${report.oversized.length}):`,
    );
    printEntries(report.oversized, entry => `${entry.path} (${formatBytes(entry.size)})`);
  }
  console.error(
    'Move generated output outside Git, or review and add an exact fixture path to the allowlist.',
  );
}

export function checkRepository(repoRoot) {
  return auditTrackedFiles(collectTrackedFiles(repoRoot));
}

function parseArguments(argv) {
  let repoRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..', '..');
  let json = false;
  for (let index = 0; index < argv.length; index += 1) {
    if (argv[index] === '--json') {
      json = true;
    } else if (argv[index] === '--root' && argv[index + 1]) {
      repoRoot = resolve(argv[index + 1]);
      index += 1;
    } else {
      throw new Error(`Unknown argument: ${argv[index]}`);
    }
  }
  return { repoRoot, json };
}

export function main(argv = process.argv.slice(2)) {
  const { repoRoot, json } = parseArguments(argv);
  const report = checkRepository(repoRoot);
  if (json) {
    console.log(JSON.stringify({ repoRoot, ...report }, null, 2));
  } else {
    printHygieneReport(report);
  }
  return report.ok ? 0 : 1;
}

const invokedPath = process.argv[1] ? resolve(process.argv[1]) : null;
if (invokedPath === fileURLToPath(import.meta.url)) {
  try {
    process.exitCode = main();
  } catch (error) {
    console.error(`Repository hygiene check could not run: ${error.message}`);
    process.exitCode = 2;
  }
}
