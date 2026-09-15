import { spawn } from 'node:child_process';
import { resolve } from 'node:path';
const python = process.env.WORKBENCH_PYTHON || resolve(process.platform === 'win32' ? '.venv/Scripts/python.exe' : '.venv/bin/python');
const child = spawn(python, process.argv.slice(2), { stdio: 'inherit', windowsHide: true });
child.on('error', error => { console.error(error.message); process.exit(1); });
child.on('exit', code => process.exit(code ?? 1));
