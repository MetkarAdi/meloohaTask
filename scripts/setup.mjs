import { spawnSync } from 'node:child_process';
import { existsSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const windows = process.platform === 'win32';
const npm = windows ? (process.env.ComSpec || 'cmd.exe') : 'npm';
const localPython = windows ? resolve(process.env.LOCALAPPDATA || '', 'Programs/Python/Python312/python.exe') : '';
const pythonCandidates = windows
  ? [...(existsSync(localPython) ? [[localPython, []]] : []), ['py', ['-3']], ['python', []]]
  : [['python3', []], ['python', []]];

function run(command, args, options = {}) {
  const result = spawnSync(command, args, { cwd: root, stdio: 'inherit', ...options });
  if (result.error) throw result.error;
  if (result.status !== 0) process.exit(result.status ?? 1);
}

const webModules = ['next', 'react', 'react-dom', 'tailwindcss', '@tailwindcss/postcss'];
if (webModules.some((name) => !existsSync(resolve(root, 'web/node_modules', name)))) {
  run(npm, windows ? ['/d', '/s', '/c', 'npm.cmd --prefix web install'] : ['--prefix', 'web', 'install']);
}

const venv = resolve(root, 'api/.venv');
if (!existsSync(resolve(venv, windows ? 'Scripts/python.exe' : 'bin/python'))) {
  let created = false;
  for (const [python, prefix] of pythonCandidates) {
    const result = spawnSync(python, [...prefix, '-m', 'venv', venv], { cwd: root, stdio: 'inherit' });
    if (result.error?.code === 'ENOENT') continue;
    if (result.error) throw result.error;
    if (result.status !== 0) process.exit(result.status ?? 1);
    created = true;
    break;
  }
  if (!created) {
    console.error('Python 3 is required to set up the API. Install Python 3 and rerun npm run setup.');
    process.exit(1);
  }
}
const venvPython = resolve(venv, windows ? 'Scripts/python.exe' : 'bin/python');
run(venvPython, ['-m', 'pip', 'install', '-r', 'api/requirements.txt']);
console.log('Setup complete.');
