import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import type { ArtifactBlock } from '@/api/chat';
import { ArtifactCard } from './artifact-card';
import { ArtifactPanel } from './artifact-panel';

const artifact: ArtifactBlock = {
  kind: 'artifact',
  id: 'metric_breakdown:revenue:1',
  artifact_type: 'breakdown',
  title: 'Revenue: breakdown',
  unit: 'AED',
  columns: ['Label', 'Value'],
  rows: [
    ['b2b', 1000],
    ['b2c', 500],
  ],
  provenance: {
    tool: 'metric_breakdown',
    source: 'demo',
    metric_id: 'revenue',
    metric_name: 'Revenue',
    executed_at: '2026-10-08T00:00:00Z',
  },
};

describe('ArtifactPanel', () => {
  it('says how many rows a fully suppressed breakdown hid, with no table', () => {
    render(
      <ArtifactPanel artifact={{ ...artifact, rows: [], suppressed_rows: 4 }} onClose={vi.fn()} />,
    );
    expect(screen.getByText('4 rows hidden by name masking')).toBeInTheDocument();
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Export CSV/ })).not.toBeInTheDocument();
  });

  it('states what the bucketed Others row covers', () => {
    render(
      <ArtifactPanel
        artifact={{ ...artifact, others_covers: 'remaining fetched rows' }}
        onClose={vi.fn()}
      />,
    );
    expect(screen.getByText('Others = remaining fetched rows')).toBeInTheDocument();
  });

  it('adds no masking caption to an unmasked artifact', () => {
    render(<ArtifactPanel artifact={artifact} onClose={vi.fn()} />);
    expect(screen.queryByText(/hidden by name masking|Others =/)).not.toBeInTheDocument();
  });

  it('shows title, provenance, chart bars and a tabular table', () => {
    render(<ArtifactPanel artifact={artifact} onClose={vi.fn()} />);
    expect(screen.getByRole('heading', { name: 'Revenue: breakdown' })).toHaveClass('font-serif');
    expect(screen.getByText(/demo/)).toBeInTheDocument();
    expect(screen.getAllByTestId('artifact-bar')).toHaveLength(2);
    expect(screen.getByRole('table')).toHaveClass('tabular');
  });

  it('exports CSV and closes', async () => {
    const onClose = vi.fn();
    const createObjectURL = vi.fn(() => 'blob:x');
    Object.assign(URL, { createObjectURL, revokeObjectURL: vi.fn() });
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
    render(<ArtifactPanel artifact={artifact} onClose={onClose} />);
    await userEvent.click(screen.getByRole('button', { name: /Export CSV/ }));
    expect(createObjectURL).toHaveBeenCalledOnce();
    expect(click).toHaveBeenCalledOnce();
    await userEvent.click(screen.getByRole('button', { name: 'Close artifact' }));
    expect(onClose).toHaveBeenCalledOnce();
    click.mockRestore();
  });
});

describe('ArtifactCard', () => {
  it('says rows were hidden instead of promising a chart for a suppressed breakdown', () => {
    render(
      <ArtifactCard artifact={{ ...artifact, rows: [], suppressed_rows: 3 }} onOpen={vi.fn()} />,
    );
    expect(screen.getByText('3 rows hidden by name masking')).toBeInTheDocument();
    expect(screen.queryByText(/Chart \+ table/)).not.toBeInTheDocument();
  });

  it('opens the artifact', async () => {
    const onOpen = vi.fn();
    render(<ArtifactCard artifact={artifact} onOpen={onOpen} />);
    await userEvent.click(screen.getByRole('button', { name: /Revenue: breakdown/ }));
    expect(onOpen).toHaveBeenCalledOnce();
  });
});
