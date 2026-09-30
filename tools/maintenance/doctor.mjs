import { existsSync, readFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const KEY_NODE_PACKAGES = [
  '@mantine/core',
  '@playwright/test',
  'react',
  'typescript',
  'vite',
];
const KEY_PYTHON_PACKAGES = ['databento', 'numpy', 'pandas', 'pyarrow'];

function numericVersion(version) {
  const match = String(version ?? '').trim().match(/^v?(\d+)(?:\.(\d+))?(?:\.(\d+))?/);
  if (!match) {
    return null;
  }
  return [Number(match[1]), Number(match[2] ?? 0), Number(match[3] ?? 0)];
}

function compareVersionTuples(left, right) {
  for (let index = 0; index < 3; index += 1) {
    if (left[index] !== right[index]) {
      return left[index] < right[index] ? -1 : 1;
    }
  }
  return 0;
}

function satisfiesComparator(actualTuple, comparator) {
  const match = comparator.trim().match(/^(>=|<=|>|<|==|=)?\s*v?(\d+(?:\.\d+){0,2})$/);
  if (!match) {
    return false;
  }
  const targetTuple = numericVersion(match[2]);
  const comparison = compareVersionTuples(actualTuple, targetTuple);
  switch (match[1] ?? '=') {
    case '>=':
      return comparison >= 0;
    case '<=':
      return comparison <= 0;
    case '>':
      return comparison > 0;
    case '<':
      return comparison < 0;
    default:
      return comparison === 0;
  }
}

export function satisfiesVersion(actual, specification) {
  const actualTuple = numericVersion(actual);
  const spec = String(specification ?? '').trim();
  if (!actualTuple || !spec) {
    return false;
  }

  if (spec.startsWith('^') || spec.startsWith('~')) {
    const targetTuple = numericVersion(spec.slice(1));
    if (!targetTuple || compareVersionTuples(actualTuple, targetTuple) < 0) {
      return false;
    }
    if (spec.startsWith('~')) {
      return actualTuple[0] === targetTuple[0] && actualTuple[1] === targetTuple[1];
    }
    if (targetTuple[0] > 0) {
      return actualTuple[0] === targetTuple[0];
    }
    if (targetTuple[1] > 0) {
      return actualTuple[0] === 0 && actualTuple[1] === targetTuple[1];
    }
    return actualTuple[0] === 0 && actualTuple[1] === 0 && actualTuple[2] === targetTuple[2];
  }

  return spec.split(',').every(comparator => satisfiesComparator(actualTuple, comparator));
}

export function parseRequirements(contents) {
  const requirements = new Map();
  for (const rawLine of contents.split(/\r?\n/)) {
    const line = rawLine.split('#', 1)[0].trim();
    if (!line || line.startsWith('-')) {
      continue;
    }
    const match = line.match(/^([A-Za-z0-9_.-]+)(?:\[[^\]]+\])?\s*(.*)$/);
    if (match) {
      requirements.set(match[1].toLowerCase(), match[2].trim() || 'installed');
    }
  }
  return requirements;
}

export function parseDocumentedRuntimeTargets(workbenchDocument) {
  const match = workbenchDocument.match(/Requires\s+Node\s+(\d+(?:\.\d+)*)\+\s+and\s+Python\s+(\d+(?:\.\d+)*)/i);
  if (!match) {
    throw new Error('Could not find the Node/Python target line in WORKBENCH.md.');
  }
  return { node: `>=${match[1]}`, python: `>=${match[2]}` };
}

function readJson(filePath) {
  return JSON.parse(readFileSync(filePath, 'utf8'));
}

function findInstalledNodePackageVersion(repoRoot, packageName) {
  const manifestPath = join(repoRoot, 'node_modules', ...packageName.split('/'), 'package.json');
  if (!existsSync(manifestPath)) {
    return null;
  }
  return readJson(manifestPath).version ?? null;
}

function resolvePython(repoRoot) {
  if (process.env.WORKBENCH_PYTHON) {
    return { command: process.env.WORKBENCH_PYTHON, source: 'WORKBENCH_PYTHON' };
  }
  const virtualEnvironment = join(
    repoRoot,
    process.platform === 'win32' ? '.venv/Scripts/python.exe' : '.venv/bin/python',
  );
  if (existsSync(virtualEnvironment)) {
    return { command: virtualEnvironment, source: 'repository .venv' };
  }
  return {
    command: process.platform === 'win32' ? 'python' : 'python3',
    source: 'PATH fallback (.venv not found)',
  };
}

function probePython(repoRoot, packageNames) {
  const python = resolvePython(repoRoot);
  const probe = [
    'import json, platform, sys',
    'from importlib import metadata',
    `names = ${JSON.stringify(packageNames)}`,
    'versions = {}',
    'for name in names:',
    '    try:',
    '        versions[name] = metadata.version(name)',
    '    except metadata.PackageNotFoundError:',
    '        versions[name] = None',
    "print(json.dumps({'version': platform.python_version(), 'executable': sys.executable, 'packages': versions}))",
  ].join('\n');
  const result = spawnSync(python.command, ['-c', probe], {
    cwd: repoRoot,
    encoding: 'utf8',
    maxBuffer: 4 * 1024 * 1024,
    windowsHide: true,
  });
  if (result.error || result.status !== 0) {
    const detail = String(result.stderr || result.error?.message || '').trim();
    return { ...python, error: detail || `interpreter exited with status ${result.status}` };
  }
  try {
    return { ...python, ...JSON.parse(result.stdout) };
  } catch (error) {
    return { ...python, error: `invalid probe output: ${error.message}` };
  }
}

function status(name, actual, target, source) {
  if (!actual) {
    return { name, actual: null, target, source, state: 'missing' };
  }
  const comparableTarget = target === 'installed' ? null : target;
  return {
    name,
    actual,
    target,
    source,
    state: comparableTarget && !satisfiesVersion(actual, comparableTarget) ? 'mismatch' : 'ok',
  };
}

export function inspectEnvironment(repoRoot) {
  const packageManifest = readJson(join(repoRoot, 'package.json'));
  const workbenchDocument = readFileSync(join(repoRoot, 'WORKBENCH.md'), 'utf8');
  const runtimeTargets = parseDocumentedRuntimeTargets(workbenchDocument);
  const requirements = parseRequirements(
    readFileSync(join(repoRoot, 'requirements-workbench.txt'), 'utf8'),
  );
  const declaredNodePackages = {
    ...(packageManifest.dependencies ?? {}),
    ...(packageManifest.devDependencies ?? {}),
  };

  const checks = [status('Node runtime', process.versions.node, runtimeTargets.node, 'WORKBENCH.md')];
  for (const packageName of KEY_NODE_PACKAGES) {
    const target = declaredNodePackages[packageName];
    if (target) {
      checks.push(
        status(
          `Node package ${packageName}`,
          findInstalledNodePackageVersion(repoRoot, packageName),
          target,
          'package.json',
        ),
      );
    }
  }

  const python = probePython(repoRoot, KEY_PYTHON_PACKAGES);
  if (python.error) {
    checks.push({
      name: 'Python runtime',
      actual: null,
      target: runtimeTargets.python,
      source: 'WORKBENCH.md',
      state: 'missing',
      detail: python.error,
    });
  } else {
    checks.push(status('Python runtime', python.version, runtimeTargets.python, 'WORKBENCH.md'));
    for (const packageName of KEY_PYTHON_PACKAGES) {
      const target = requirements.get(packageName);
      if (target) {
        checks.push(
          status(
            `Python package ${packageName}`,
            python.packages[packageName],
            target,
            'requirements-workbench.txt',
          ),
        );
      }
    }
  }

  const counts = { ok: 0, mismatch: 0, missing: 0 };
  for (const check of checks) {
    counts[check.state] += 1;
  }
  return {
    repoRoot,
    packageName: packageManifest.name,
    python: {
      command: python.command,
      source: python.source,
      executable: python.executable ?? null,
      error: python.error ?? null,
    },
    checks,
    counts,
    ok: counts.mismatch === 0 && counts.missing === 0,
  };
}

function printDoctorReport(report) {
  console.log(`Strategy Workbench environment doctor (${report.packageName})`);
  console.log(`Repository: ${report.repoRoot}`);
  console.log(
    `Python selection: ${report.python.executable ?? report.python.command} (${report.python.source})`,
  );
  console.log('');
  for (const check of report.checks) {
    const actual = check.actual ?? 'not available';
    console.log(`[${check.state}] ${check.name}: ${actual}; target ${check.target} (${check.source})`);
    if (check.detail) {
      console.log(`  ${check.detail}`);
    }
  }
  console.log('');
  console.log(
    `Summary: ${report.counts.ok} ok, ${report.counts.mismatch} mismatch, ` +
      `${report.counts.missing} missing.`,
  );
  console.log('Read-only diagnostic: no packages or runtimes were installed or changed.');
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
  const report = inspectEnvironment(repoRoot);
  if (json) {
    console.log(JSON.stringify(report, null, 2));
  } else {
    printDoctorReport(report);
  }
  return report.ok ? 0 : 1;
}

const invokedPath = process.argv[1] ? resolve(process.argv[1]) : null;
if (invokedPath === fileURLToPath(import.meta.url)) {
  try {
    process.exitCode = main();
  } catch (error) {
    console.error(`Environment doctor could not run: ${error.message}`);
    process.exitCode = 2;
  }
}
