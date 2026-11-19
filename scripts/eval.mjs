import { spawnSync } from 'node:child_process';
import { existsSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const python = resolve(root, 'api/.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');
if (!existsSync(python)) {
  console.error('Evaluation needs the project Python environment. Run npm run setup first.');
  process.exit(1);
}
const args = ['-m', 'evals', ...process.argv.slice(2)];
const result = spawnSync(python, args, { cwd: resolve(root, 'api'), stdio: 'inherit' });
if (result.error) throw result.error;
process.exit(result.status ?? 1);
