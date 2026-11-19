import { spawnSync } from 'node:child_process';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const email = process.argv[2];
if (!email) {
  console.error('Usage: npm run dummy-credits -- test@example.com');
  process.exit(2);
}
const windows = process.platform === 'win32';
const python = resolve(root, 'api/.venv', windows ? 'Scripts/python.exe' : 'bin/python');
const result = spawnSync(python, ['-m', 'app.db.dummy_credit', email], {
  cwd: resolve(root, 'api'),
  stdio: 'inherit',
});
if (result.error) throw result.error;
process.exit(result.status ?? 1);
