// src/ui/empty-state.test.tsx
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { EmptyState } from './empty-state';

describe('EmptyState', () => {
  it('shows a serif heading, a sentence and one action', () => {
    render(
      <EmptyState
        icon="✓"
        title="No pending requests"
        actions={<button type="button">Clear</button>}
      >
        You&apos;re all caught up.
      </EmptyState>,
    );
    expect(screen.getByRole('heading', { name: 'No pending requests' })).toHaveClass('font-serif');
    expect(screen.getByText("You're all caught up.")).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Clear' })).toBeInTheDocument();
    expect(screen.getByText('✓')).toHaveAttribute('aria-hidden');
  });
});
