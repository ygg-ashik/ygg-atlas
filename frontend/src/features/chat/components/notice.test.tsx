import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { Notice } from './notice';

describe('Notice', () => {
  it('blocked states the reason plainly', () => {
    render(<Notice kind="blocked" message="Daily message limit reached." />);
    expect(screen.getByRole('status')).toHaveTextContent('Daily message limit reached.');
  });

  it('error offers retry', async () => {
    const onRetry = vi.fn();
    render(<Notice kind="error" message="Connection lost." onRetry={onRetry} />);
    await userEvent.click(screen.getByRole('button', { name: /retry/i }));
    expect(onRetry).toHaveBeenCalledOnce();
  });

  it('stale warning names the source and age', () => {
    render(<Notice kind="stale" message="DeepSales last synced 26h ago" />);
    expect(screen.getByRole('status')).toHaveTextContent('DeepSales last synced 26h ago');
    expect(screen.getByRole('status')).toHaveTextContent('Recent changes may be missing');
  });
});
