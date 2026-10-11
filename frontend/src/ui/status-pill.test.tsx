// src/ui/status-pill.test.tsx
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { StandingPill, StatusPill } from './status-pill';

describe('StatusPill', () => {
  it('always carries text next to a decorative dot', () => {
    render(<StatusPill tone="positive">active</StatusPill>);
    const pill = screen.getByText('active');
    expect(pill).toHaveAttribute('data-tone', 'positive');
    expect(pill).toHaveClass('text-positive', 'rounded-full');
    const dot = pill.querySelector('[data-dot]');
    expect(dot).toHaveAttribute('aria-hidden');
    expect(dot).toHaveAttribute('data-dot', 'round');
  });

  it('marks a deny with a diamond dot', () => {
    render(
      <StatusPill tone="negative" diamond>
        deny
      </StatusPill>,
    );
    const dot = screen.getByText('deny').querySelector('[data-dot]');
    expect(dot).toHaveAttribute('data-dot', 'diamond');
    expect(dot).toHaveClass('rotate-45');
  });

  it('standing pill is the accent tone for managers and muted for members', () => {
    render(
      <>
        <StandingPill standing="manager" />
        <StandingPill standing="member" />
      </>,
    );
    expect(screen.getByText('manager')).toHaveAttribute('data-tone', 'accent');
    expect(screen.getByText('member')).toHaveAttribute('data-tone', 'muted');
  });
});
