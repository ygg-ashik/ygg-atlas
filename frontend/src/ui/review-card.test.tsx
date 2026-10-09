// src/ui/review-card.test.tsx
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

const reduced = vi.hoisted(() => ({ value: false }));
vi.mock('motion/react', async (importOriginal) => ({
  ...(await importOriginal<object>()),
  useReducedMotion: () => reduced.value,
}));

import { ReviewCard } from './review-card';

const LINES = [
  { kind: 'context', text: 'group marketing' },
  { kind: 'add', text: 'grant allow demo/order/*' },
] as const;

describe('ReviewCard', () => {
  afterEach(() => {
    reduced.value = false;
  });

  it('shows the diff, the audit action and Apply/Dismiss while open', async () => {
    const onApply = vi.fn();
    const onDismiss = vi.fn();
    render(
      <ReviewCard
        lines={LINES}
        status="open"
        auditAction="grant.create"
        onApply={onApply}
        onDismiss={onDismiss}
      />,
    );
    const card = screen.getByRole('region', { name: 'Proposed change' });
    expect(card).toHaveTextContent('needs your approval');
    expect(screen.getByText('grant.create')).toHaveClass('font-mono');
    await userEvent.click(screen.getByRole('button', { name: 'Apply' }));
    await userEvent.click(screen.getByRole('button', { name: 'Dismiss' }));
    expect(onApply).toHaveBeenCalledOnce();
    expect(onDismiss).toHaveBeenCalledOnce();
  });

  it('morphs Apply to its done label in place and disables it', () => {
    render(
      <ReviewCard
        lines={LINES}
        status="applied"
        auditAction="grant.create"
        onApply={() => {}}
        onDismiss={() => {}}
      />,
    );
    const button = screen.getByRole('button', { name: '✓ Applied' });
    expect(button).toBeDisabled();
    expect(screen.queryByRole('button', { name: 'Dismiss' })).toBeNull();
    expect(screen.getByRole('region')).toHaveTextContent('in the audit log');
  });

  it('states a 409 as fact and offers Retry', () => {
    render(<ReviewCard lines={LINES} status="conflict" auditAction="x" onApply={() => {}} />);
    expect(screen.getByRole('alert')).toHaveTextContent('nothing was written');
    expect(screen.getByRole('button', { name: 'Retry' })).toBeEnabled();
  });

  it('is busy while applying', () => {
    render(<ReviewCard lines={LINES} status="applying" auditAction="x" onApply={() => {}} />);
    const button = screen.getByRole('button', { name: 'Apply' });
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute('aria-busy', 'true');
  });

  it('uses the reduced-motion cross-fade (no blur) when motion is reduced', () => {
    reduced.value = true;
    const { container } = render(
      <ReviewCard lines={LINES} status="open" auditAction="x" onApply={() => {}} />,
    );
    const hidden = container.querySelector('[data-morph-part="to"]') as HTMLElement;
    expect(hidden.style.filter).toBe('');
    expect(hidden.style.opacity).toBe('0');
  });
});
