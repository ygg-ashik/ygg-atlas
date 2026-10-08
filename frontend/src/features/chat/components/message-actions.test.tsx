import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { MessageActions } from './message-actions';

const setFeedback = vi.hoisted(() => vi.fn());
vi.mock('@/api/chat', () => ({ setMessageFeedback: setFeedback }));

describe('MessageActions', () => {
  it('copies the answer and morphs copy → check in place', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    // happy-dom exposes navigator.clipboard as a getter, so stub it by definition.
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true });
    render(<MessageActions messageId="m1" text="Revenue was 42" initialRating={null} />);
    await userEvent.click(screen.getByRole('button', { name: 'Copy answer' }));
    expect(writeText).toHaveBeenCalledWith('Revenue was 42');
    expect(screen.getByRole('button', { name: 'Copied' })).toBeInTheDocument();
  });

  it('thumbs down reveals categories and sends feedback', async () => {
    render(<MessageActions messageId="m1" text="x" initialRating={null} />);
    await userEvent.click(screen.getByRole('button', { name: 'Bad answer' }));
    expect(setFeedback).toHaveBeenCalledWith('m1', { rating: 'down' });
    await userEvent.click(screen.getByRole('button', { name: 'Inaccurate' }));
    expect(setFeedback).toHaveBeenCalledWith('m1', { rating: 'down', category: 'inaccurate' });
  });
});
