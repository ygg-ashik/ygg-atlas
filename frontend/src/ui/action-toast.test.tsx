// src/ui/action-toast.test.tsx
import { act, fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { actionToast } from './action-toast';
import { Toaster } from './toaster';

describe('actionToast', () => {
  it('shows a sticky warning toast whose Retry runs the action', async () => {
    const onAction = vi.fn();
    render(<Toaster />);
    act(() => {
      actionToast('Access changed while this request was running; retry.', { onAction });
    });
    const msg = await screen.findByText('Access changed while this request was running; retry.');
    expect(msg.closest('[data-type]')).toHaveAttribute('data-type', 'warning');
    // Sonner's swipe handler needs pointer capture, which happy-dom lacks: click directly.
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    expect(onAction).toHaveBeenCalledOnce();
  });
});
