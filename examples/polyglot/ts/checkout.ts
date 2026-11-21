import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

export function checkout(role: string): boolean {
  const auth = fileURLToPath(new URL('../python/auth.py', import.meta.url));
  const response = execFileSync(
    process.env.SMARTCI_PYTHON ?? 'python3',
    [auth, role],
    { encoding: 'utf8', timeout: 5000, maxBuffer: 65536 },
  );
  const token: unknown = JSON.parse(response);
  return typeof token === 'object' && token !== null && 'role' in token
    && (token.role === 'buyer' || token.role === 'admin');
}
