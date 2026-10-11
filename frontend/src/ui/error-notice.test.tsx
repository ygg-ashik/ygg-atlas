// src/ui/error-notice.test.tsx
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { ErrorNotice } from './error-notice';

describe('ErrorNotice', () => {
  it('states the failure as an alert and retries', async () => {
    const onRetry = vi.fn();
    render(
      <ErrorNotice title="Couldn't load users" onRetry={onRetry}>
        Nothing changed.
      </ErrorNotice>,
    );
    expect(screen.getByRole('alert')).toHaveTextContent("Couldn't load usersNothing changed.");
    await userEvent.click(screen.getByRole('button', { name: 'Retry' }));
    expect(onRetry).toHaveBeenCalledOnce();
  });

  it('morphs Retry to Loading and blocks repeats while retrying', () => {
    render(<ErrorNotice title="Couldn't load users" onRetry={() => {}} retrying />);
    const b = screen.getByRole('button', { name: 'Loading' });
    expect(b).toBeDisabled();
    expect(b.querySelector('[data-morph]')).toHaveAttribute('data-morph', 'done');
  });
});
