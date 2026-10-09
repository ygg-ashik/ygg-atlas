// src/ui/count-badge.test.tsx
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { CountBadge } from './count-badge';

describe('CountBadge', () => {
  it('shows a tabular count with a spoken label', () => {
    render(
      <button type="button">
        Access requests <CountBadge count={3} label="pending requests" />
      </button>,
    );
    expect(
      screen.getByRole('button', { name: 'Access requests 3 pending requests' }),
    ).toBeInTheDocument();
    expect(screen.getByText('3', { selector: '[aria-hidden]' }).parentElement).toHaveClass(
      'tabular-nums',
    );
  });

  it('renders nothing at zero and caps at 99+', () => {
    const { container, rerender } = render(<CountBadge count={0} label="pending" />);
    expect(container).toBeEmptyDOMElement();
    rerender(<CountBadge count={140} label="pending" />);
    expect(screen.getByText('99+')).toBeInTheDocument();
    expect(screen.getByText('140 pending')).toHaveClass('sr-only');
  });
});
