import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { StepsBlock } from './steps-block';

describe('StepsBlock', () => {
  it('while working: shows each step with its mono tool id', () => {
    render(
      <StepsBlock
        live
        steps={[
          { tool: 'search_atlas', status: 'done' },
          { tool: 'query_metric', status: 'running' },
        ]}
      />,
    );
    expect(screen.getByText('Working · 2 steps')).toBeInTheDocument();
    expect(screen.getByText('Querying a governed metric')).toBeInTheDocument();
    expect(screen.getByText('query_metric')).toHaveClass('font-mono');
  });

  it('when finished: collapses to "Worked for Ns" and expands on click', async () => {
    render(<StepsBlock steps={[{ tool: 'query_metric', status: 'done' }]} durationMs={4200} />);
    const toggle = screen.getByRole('button', { name: /Worked for 4s · 1 step/ });
    expect(toggle).toHaveAttribute('aria-expanded', 'false');
    await userEvent.click(toggle);
    expect(toggle).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByText('Querying a governed metric')).toBeVisible();
  });

  it('history without timing says how many atlas steps were used', () => {
    render(
      <StepsBlock
        steps={[
          { tool: 'a', status: 'done' },
          { tool: 'b', status: 'done' },
        ]}
      />,
    );
    expect(screen.getByRole('button', { name: /Used 2 atlas steps/ })).toBeInTheDocument();
  });

  it('renders nothing without steps', () => {
    const { container } = render(<StepsBlock steps={[]} />);
    expect(container).toBeEmptyDOMElement();
  });
});
