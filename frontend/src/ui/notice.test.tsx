// src/ui/notice.test.tsx
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { Notice } from './notice';

describe('Notice', () => {
  it('states a fact with a decorative icon on a solid card', () => {
    render(
      <Notice icon="!" title="Remove the group's subgroups first." role="status">
        marketing still has 2 subgroups.
      </Notice>,
    );
    const n = screen.getByRole('status');
    expect(n).toHaveAttribute('data-tone', 'neutral');
    expect(n).toHaveClass('bg-card', 'rounded-card');
    expect(n).toHaveTextContent("Remove the group's subgroups first.");
    expect(n.querySelector('[aria-hidden]')).toHaveTextContent('!');
  });

  it('has an amber warning tone and an action slot', () => {
    render(
      <Notice tone="warning" icon="!" action={<button type="button">Refresh</button>}>
        Shown once.
      </Notice>,
    );
    expect(screen.getByText('Shown once.').closest('[data-tone]')).toHaveClass('bg-warning/10');
    expect(screen.getByRole('button', { name: 'Refresh' })).toBeInTheDocument();
  });
});
