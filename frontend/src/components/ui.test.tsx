import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { DiffViewer } from './DiffViewer';
import { ConfidenceBar, ProviderBadge, StatusBadge, VerdictBadge } from './ui';

describe('ui primitives', () => {
  it('labels simulated providers explicitly', () => {
    render(<ProviderBadge provider="mock" model="mock-scripted-v1" simulated />);
    expect(screen.getByText('MOCK · scripted')).toBeInTheDocument();
  });

  it('shows the real model for live providers', () => {
    render(<ProviderBadge provider="meta" model="muse-spark-1.3" simulated={false} />);
    expect(screen.getByText('meta · muse-spark-1.3')).toBeInTheDocument();
  });

  it('renders status and verdict badges', () => {
    render(
      <>
        <StatusBadge status="running" />
        <VerdictBadge verdict="no_verified_fix" />
      </>,
    );
    expect(screen.getByText('running')).toBeInTheDocument();
    expect(screen.getByText('no verified fix')).toHaveClass('red');
  });

  it('sizes the confidence bar from the value', () => {
    const { container } = render(<ConfidenceBar value={0.42} status="supported" />);
    const fill = container.querySelector('.confidence > div') as HTMLElement;
    expect(fill.style.width).toBe('42%');
  });

  it('renders diff lines with add/remove classes', () => {
    const { container } = render(
      <DiffViewer diff={'--- a/x.ts\n+++ b/x.ts\n@@ -1,1 +1,1 @@\n-old\n+new\n'} />,
    );
    expect(container.querySelector('.diff-line.del')?.textContent).toContain('old');
    expect(container.querySelector('.diff-line.add')?.textContent).toContain('new');
  });
});
