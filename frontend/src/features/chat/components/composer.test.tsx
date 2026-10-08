import { act, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { Composer } from './composer';

const base = {
  value: '',
  onChange: vi.fn(),
  onSend: vi.fn(),
  onStop: vi.fn(),
  isStreaming: false,
  disabled: false,
};

describe('Composer', () => {
  afterEach(() => vi.useRealTimers());

  it('sends on Enter (not Shift+Enter) when there is text', () => {
    const onSend = vi.fn();
    render(<Composer {...base} value="revenue?" onSend={onSend} />);
    const box = screen.getByRole('textbox');
    fireEvent.keyDown(box, { key: 'Enter', shiftKey: true });
    expect(onSend).not.toHaveBeenCalled();
    fireEvent.keyDown(box, { key: 'Enter' });
    expect(onSend).toHaveBeenCalledOnce();
  });

  it('morphs send into stop while streaming and shows the elapsed timer', () => {
    vi.useFakeTimers();
    const onStop = vi.fn();
    render(<Composer {...base} isStreaming startedAt={Date.now()} onStop={onStop} />);
    const stop = screen.getByRole('button', { name: 'Stop generating' });
    expect(stop).toHaveAttribute('data-streaming', 'true');
    act(() => vi.advanceTimersByTime(3_000));
    expect(screen.getByText('3s')).toHaveClass('font-mono');
    fireEvent.click(stop);
    expect(onStop).toHaveBeenCalledOnce();
  });

  it('is glass with the specular highlight', () => {
    render(<Composer {...base} />);
    expect(screen.getByRole('textbox').closest('form')).toHaveClass(
      'glass',
      'glass-specular',
      'rounded-glass',
    );
  });
});
