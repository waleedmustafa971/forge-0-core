interface DiffLine {
  kind: 'add' | 'del' | 'ctx' | 'hunk';
  text: string;
  oldNo: number | null;
  newNo: number | null;
}

interface DiffFile {
  path: string;
  lines: DiffLine[];
}

export function parseUnifiedDiff(diff: string): DiffFile[] {
  const files: DiffFile[] = [];
  let current: DiffFile | null = null;
  let oldNo = 0;
  let newNo = 0;
  for (const raw of diff.split('\n')) {
    if (raw.startsWith('--- ')) continue;
    if (raw.startsWith('+++ ')) {
      current = { path: raw.slice(4).replace(/^b\//, ''), lines: [] };
      files.push(current);
      continue;
    }
    if (!current) continue;
    const hunk = /^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@/.exec(raw);
    if (hunk) {
      oldNo = Number(hunk[1]);
      newNo = Number(hunk[2]);
      current.lines.push({ kind: 'hunk', text: raw, oldNo: null, newNo: null });
    } else if (raw.startsWith('+')) {
      current.lines.push({ kind: 'add', text: raw.slice(1), oldNo: null, newNo: newNo++ });
    } else if (raw.startsWith('-')) {
      current.lines.push({ kind: 'del', text: raw.slice(1), oldNo: oldNo++, newNo: null });
    } else if (raw.startsWith(' ') || raw === '') {
      if (raw === '' && current.lines.length === 0) continue;
      current.lines.push({ kind: 'ctx', text: raw.slice(1), oldNo: oldNo++, newNo: newNo++ });
    }
  }
  return files;
}
