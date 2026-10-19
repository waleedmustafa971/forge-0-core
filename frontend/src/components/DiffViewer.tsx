import { parseUnifiedDiff } from '../diff';

export function DiffViewer({ diff }: { diff: string }) {
  const files = parseUnifiedDiff(diff);
  if (!files.length) return <div className="empty small">No diff</div>;
  return (
    <div className="stack-sm">
      {files.map((file) => (
        <div className="diff" key={file.path}>
          <div className="diff-file">{file.path}</div>
          {file.lines.map((line, i) => (
            <div className={`diff-line ${line.kind}`} key={i}>
              <span className="ln">{line.oldNo ?? ''}</span>
              <span className="ln">{line.newNo ?? ''}</span>
              <span className="tx">
                {line.kind === 'add' ? '+ ' : line.kind === 'del' ? '- ' : line.kind === 'ctx' ? '  ' : ''}
                {line.text}
              </span>
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}
