import { describe, expect, it } from 'vitest';
import { parseUnifiedDiff } from './diff';

const DIFF = `--- a/src/domain/status.ts
+++ b/src/domain/status.ts
@@ -18,5 +18,5 @@
   if (from === to) return true;
   const allowed = allowedTransitions(from);
-  return allowed.length === 0 || allowed.includes(to);
+  return allowed.includes(to);
 }
--- /dev/null
+++ b/src/lib/keyedMutex.ts
@@ -0,0 +1,2 @@
+export class KeyedMutex {
+}
`;

describe('parseUnifiedDiff', () => {
  it('splits files and tracks line numbers', () => {
    const files = parseUnifiedDiff(DIFF);
    expect(files.map((f) => f.path)).toEqual(['src/domain/status.ts', 'src/lib/keyedMutex.ts']);
    const [status] = files;
    const del = status.lines.find((l) => l.kind === 'del');
    const add = status.lines.find((l) => l.kind === 'add');
    expect(del).toMatchObject({ oldNo: 20, newNo: null, text: '  return allowed.length === 0 || allowed.includes(to);' });
    expect(add).toMatchObject({ oldNo: null, newNo: 20, text: '  return allowed.includes(to);' });
  });

  it('handles newly created files', () => {
    const created = parseUnifiedDiff(DIFF)[1];
    expect(created.lines.filter((l) => l.kind === 'add').map((l) => l.newNo)).toEqual([1, 2]);
  });

  it('returns nothing for an empty diff', () => {
    expect(parseUnifiedDiff('')).toEqual([]);
  });
});
