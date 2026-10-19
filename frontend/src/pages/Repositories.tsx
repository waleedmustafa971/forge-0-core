import { formatDate } from '../format';
import { useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { api } from '../api/client';
import type { Repository, ScanResult } from '../api/types';
import { IconChevron, IconFile, IconFolder } from '../components/icons';
import { StartInvestigation } from '../components/StartInvestigation';
import { Card, Empty, Spinner } from '../components/ui';
import { useAsync } from '../hooks';

interface TreeNode {
  name: string;
  path: string;
  children: TreeNode[];
  isFile: boolean;
}

function buildTree(paths: string[]): TreeNode[] {
  const root: TreeNode = { name: '', path: '', children: [], isFile: false };
  for (const path of paths) {
    let node = root;
    path.split('/').forEach((part, i, parts) => {
      const isFile = i === parts.length - 1;
      let child = node.children.find((c) => c.name === part);
      if (!child) {
        child = { name: part, path: parts.slice(0, i + 1).join('/'), children: [], isFile };
        node.children.push(child);
      }
      node = child;
    });
  }
  const sort = (nodes: TreeNode[]) => {
    nodes.sort((a, b) => Number(a.isFile) - Number(b.isFile) || a.name.localeCompare(b.name));
    nodes.forEach((n) => sort(n.children));
  };
  sort(root.children);
  return root.children;
}

function Tree({
  nodes,
  depth,
  selected,
  onSelect,
  open,
  toggle,
}: {
  nodes: TreeNode[];
  depth: number;
  selected: string | null;
  onSelect: (path: string) => void;
  open: Set<string>;
  toggle: (path: string) => void;
}) {
  return (
    <>
      {nodes.map((node) => (
        <div key={node.path}>
          <div
            className={`tree-item ${selected === node.path ? 'selected' : ''}`}
            style={{ paddingLeft: 12 + depth * 14 }}
            onClick={() => (node.isFile ? onSelect(node.path) : toggle(node.path))}
          >
            {node.isFile ? (
              <IconFile />
            ) : (
              <IconChevron style={{ transform: open.has(node.path) ? 'rotate(90deg)' : undefined, transition: 'transform 120ms' }} />
            )}
            {!node.isFile && <IconFolder />}
            <span>{node.name}</span>
          </div>
          {!node.isFile && open.has(node.path) && (
            <Tree nodes={node.children} depth={depth + 1} selected={selected} onSelect={onSelect} open={open} toggle={toggle} />
          )}
        </div>
      ))}
    </>
  );
}

function ImportForm({ onImported }: { onImported: (repo: Repository) => void }) {
  const [type, setType] = useState<'git' | 'local'>('git');
  const [value, setValue] = useState('');
  const [name, setName] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      const repo = await api.importRepository(
        type === 'git'
          ? { source_type: 'git', url: value, name: name || undefined }
          : { source_type: 'local', path: value, name: name || undefined },
      );
      setValue('');
      setName('');
      onImported(repo);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="stack-sm">
      <div className="row">
        <button className={`btn sm ${type === 'git' ? '' : 'ghost'}`} onClick={() => setType('git')}>
          Git URL
        </button>
        <button className={`btn sm ${type === 'local' ? '' : 'ghost'}`} onClick={() => setType('local')}>
          Local path
        </button>
      </div>
      <input
        className="input mono"
        placeholder={type === 'git' ? 'https://github.com/org/repo.git' : 'D:\\path\\inside\\an\\allowed\\root'}
        value={value}
        onChange={(e) => setValue(e.target.value)}
      />
      <input className="input" placeholder="Display name (optional)" value={name} onChange={(e) => setName(e.target.value)} />
      <span className="hint">
        Imports are copied into a FORGE-0 snapshot; the original is never modified. Clones run with hooks disabled.
      </span>
      {error && <div className="alert red small">{error}</div>}
      <button className="btn primary" onClick={submit} disabled={busy || !value}>
        {busy ? 'Importing…' : 'Import repository'}
      </button>
    </div>
  );
}

function ScanPanel({ repo, onScanned }: { repo: Repository; onScanned: (s: ScanResult) => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const scan = repo.last_scan;
  const run = async () => {
    setBusy(true);
    setError(null);
    try {
      onScanned(await api.scan(repo.id));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Card
      title="Test suite"
      actions={
        <button className="btn sm" onClick={run} disabled={busy}>
          {busy && <Spinner />} {busy ? 'Running in sandbox…' : scan ? 'Re-run' : 'Run in sandbox'}
        </button>
      }
      flush
    >
      {error && <div className="alert red small" style={{ margin: 12 }}>{error}</div>}
      {!scan ? (
        <Empty>Run the suite in the isolated sandbox to see which tests fail.</Empty>
      ) : (
        <>
          <div className="row small muted" style={{ padding: '10px 16px' }}>
            <span className="badge green">{scan.passed} passed</span>
            <span className="badge red">{scan.failed} failed</span>
            <span>{scan.duration_ms} ms · {scan.image}</span>
            <span className="spacer" />
            <span>{formatDate(scan.scanned_at)}</span>
          </div>
          <table className="table">
            <tbody>
              {scan.tests.map((t) => (
                <tr key={t.name}>
                  <td style={{ width: 24 }}>
                    <span className="dot" style={{ color: t.status === 'passed' ? 'var(--green)' : t.status === 'failed' ? 'var(--red)' : 'var(--text-faint)' }} />
                  </td>
                  <td>
                    <div className="small">{t.name}</div>
                    {t.status === 'failed' && t.error && <div className="mono faint small">{t.error.split('\n')[0]}</div>}
                  </td>
                  <td className="mono faint small">{t.file}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </Card>
  );
}

export default function Repositories() {
  const { repoId } = useParams();
  const navigate = useNavigate();
  const repos = useAsync(() => api.repositories(), []);
  const selected = repos.data?.find((r) => r.id === repoId) ?? repos.data?.[0] ?? null;
  const tree = useAsync(() => (selected ? api.tree(selected.id) : Promise.resolve(null)), [selected?.id]);
  const [filePath, setFilePath] = useState<string | null>(null);
  const file = useAsync(
    () => (selected && filePath ? api.file(selected.id, filePath) : Promise.resolve(null)),
    [selected?.id, filePath],
  );
  const [open, setOpen] = useState<Set<string>>(new Set(['src', 'test']));
  const [starting, setStarting] = useState(false);
  const nodes = useMemo(() => buildTree(tree.data?.files.map((f) => f.path) ?? []), [tree.data]);
  const toggle = (path: string) =>
    setOpen((prev) => {
      const next = new Set(prev);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    });

  return (
    <div className="stack fade-in">
      <div className="page-header">
        <div>
          <h1>Repository Explorer</h1>
          <p>Import a Git repository, browse its source, and run its test suite inside the sandbox.</p>
        </div>
        {selected && (
          <button className="btn primary" onClick={() => setStarting(true)}>
            Investigate {selected.name}
          </button>
        )}
      </div>

      <div className="grid grid-explorer">
        <div className="stack">
          <Card title="Repositories" flush>
            {repos.loading ? (
              <Empty>
                <Spinner />
              </Empty>
            ) : !repos.data?.length ? (
              <Empty>No repositories yet.</Empty>
            ) : (
              <div className="tree">
                {repos.data.map((r) => (
                  <div
                    key={r.id}
                    className={`tree-item ${selected?.id === r.id ? 'selected' : ''}`}
                    onClick={() => {
                      setFilePath(null);
                      navigate(`/repositories/${r.id}`);
                    }}
                  >
                    <span>{r.name}</span>
                    <span className="spacer" />
                    <span className="badge outline">{r.source_type}</span>
                  </div>
                ))}
              </div>
            )}
          </Card>
          <Card title="Import">
            <ImportForm
              onImported={(repo) => {
                void repos.refresh();
                navigate(`/repositories/${repo.id}`);
              }}
            />
          </Card>
        </div>

        {selected ? (
          <div className="stack">
            <Card title={selected.name} actions={<span className="mono faint small">{selected.commit_sha?.slice(0, 10) ?? 'snapshot'}</span>}>
              <dl className="kv">
                <dt>Source</dt>
                <dd className="mono small">{selected.source}</dd>
                <dt>Languages</dt>
                <dd>
                  <div className="row wrap">
                    {Object.entries(selected.profile.languages).map(([lang, n]) => (
                      <span className="badge outline" key={lang}>
                        {lang} · {n}
                      </span>
                    ))}
                  </div>
                </dd>
                <dt>Frameworks</dt>
                <dd>{selected.profile.frameworks.join(', ') || '—'}</dd>
                <dt>Runtime</dt>
                <dd>
                  {selected.profile.runtime.runtime} · runner <code>{selected.profile.runtime.runner ?? 'none'}</code> · image{' '}
                  <code>{selected.profile.runtime.image ?? '—'}</code>
                </dd>
                <dt>Tests</dt>
                <dd>
                  {selected.profile.test_files.length} test files · {selected.profile.source_files.length} source files
                </dd>
              </dl>
            </Card>

            <div className="grid grid-files">
              <Card title="Source tree" flush>
                <div className="tree">
                  <Tree nodes={nodes} depth={0} selected={filePath} onSelect={setFilePath} open={open} toggle={toggle} />
                </div>
              </Card>
              <Card title={filePath ?? 'File'} flush>
                {!filePath ? (
                  <Empty>Select a file to view it.</Empty>
                ) : file.loading ? (
                  <Empty>
                    <Spinner />
                  </Empty>
                ) : file.data?.binary ? (
                  <Empty>Binary file</Empty>
                ) : (
                  <pre className="code" style={{ border: 'none', maxHeight: 640, borderRadius: 0 }}>
                    {file.data?.content}
                  </pre>
                )}
              </Card>
            </div>

            <ScanPanel
              repo={selected}
              onScanned={(scan) =>
                repos.setData((prev) => prev?.map((r) => (r.id === selected.id ? { ...r, last_scan: scan } : r)) ?? prev)
              }
            />
          </div>
        ) : (
          <Empty>Import a repository to get started.</Empty>
        )}
      </div>

      {starting && repos.data && selected && (
        <StartInvestigation repositories={repos.data} initialRepoId={selected.id} onClose={() => setStarting(false)} />
      )}
    </div>
  );
}
