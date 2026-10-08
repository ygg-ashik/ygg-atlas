import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { ClarifyBlock } from './clarify-block';

const block = {
  kind: 'clarify' as const,
  question: 'Which revenue do you mean?',
  options: [
    { label: 'Corporate revenue', metric_id: 'b2b_revenue' },
    { label: 'All revenue', metric_id: 'revenue' },
  ],
};

describe('ClarifyBlock', () => {
  it('sends the chosen option and marks it selected', async () => {
    const onChoose = vi.fn();
    render(<ClarifyBlock block={block} active onChoose={onChoose} />);
    expect(screen.getByRole('group', { name: 'Which revenue do you mean?' })).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Corporate revenue' }));
    expect(onChoose).toHaveBeenCalledWith('Corporate revenue');
    expect(screen.getByRole('button', { name: 'Corporate revenue' })).toHaveAttribute(
      'data-selected',
      'true',
    );
  });

  it('is inert once the conversation moved on', () => {
    render(<ClarifyBlock block={block} active={false} onChoose={vi.fn()} />);
    expect(screen.getByRole('button', { name: 'All revenue' })).toBeDisabled();
  });
});
