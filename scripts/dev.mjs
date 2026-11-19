import { spawn, spawnSync } from 'node:child_process';
import { existsSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const windows = process.platform === 'win32';
const npm = windows ? (process.env.ComSpec || 'cmd.exe') : 'npm';
const webModules = ['next', 'react', 'react-dom', 'tailwindcss', '@tailwindcss/postcss'];
if (webModules.some((name) => !existsSync(resolve(root, 'web/node_modules', name))) || !existsSync(resolve(root, 'api/.venv'))) {
  const setup = spawnSync(process.execPath, [resolve(root, 'scripts/setup.mjs')], { cwd: root, stdio: 'inherit' });
  if (setup.status !== 0) process.exit(setup.status ?? 1);
}

const apiPython = resolve(root, 'api/.venv', windows ? 'Scripts/python.exe' : 'bin/python');
console.log('Running database migrations before starting the app…');
const migration = spawnSync(apiPython, ['-m', 'alembic', 'upgrade', 'head'], {
  cwd: resolve(root, 'api'),
  stdio: 'inherit',
});
if (migration.error) {
  console.error(`Database migration command failed to start: ${migration.error.message}`);
  process.exit(1);
}
if (migration.status !== 0) {
  console.error(`Database migrations failed (exit code ${migration.status ?? 'unknown'}). The app was not started.`);
  process.exit(migration.status ?? 1);
}

console.log('Database migrations completed. Starting services.');
console.log('Web: http://localhost:3000\nAPI: http://127.0.0.1:8000');
const children = [
  spawn(npm, windows ? ['/d', '/s', '/c', 'npm.cmd --prefix web run dev'] : ['--prefix', 'web', 'run', 'dev'], { cwd: root, stdio: 'inherit' }),
  spawn(apiPython, ['-m', 'uvicorn', 'main:app', '--reload', '--host', process.env.API_HOST || '127.0.0.1', '--port', process.env.API_PORT || '8000'], { cwd: resolve(root, 'api'), stdio: 'inherit' }),
  spawn(apiPython, ['-m', 'app.jobs.worker'], { cwd: resolve(root, 'api'), stdio: 'inherit' }),
];
let stopping = false;
function stop(code = 0) {
  if (stopping) return;
  stopping = true;
  for (const child of children) if (!child.killed) child.kill('SIGTERM');
  process.exitCode = code;
}
for (const child of children) child.on('exit', (code) => { if (!stopping) stop(code ?? 1); });
process.on('SIGINT', () => stop());
process.on('SIGTERM', () => stop());
