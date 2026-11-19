import { spawnSync } from 'node:child_process';
import { existsSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const python = resolve(root, 'api/.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');
let failed = false;
if (!existsSync(python)) {
  console.error('API tests need the project Python environment. Install Python 3, then run npm run setup.');
  failed = true;
} else {
  const result = spawnSync(python, ['-m', 'pytest', 'api'], { cwd: root, stdio: 'inherit' });
  if (result.error) throw result.error;
  if (result.status !== 0) failed = true;
}
const web = spawnSync(process.execPath, ['--test', 'web/tests/smoke.test.mjs'], { cwd: root, stdio: 'inherit' });
if (web.error) throw web.error;
if (web.status !== 0) failed = true;
process.exit(failed ? 1 : 0);
