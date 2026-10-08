// src/ui/button.test.tsx
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { Button } from './button';

describe('Button (DESIGN.md variants)', () => {
  it('primary is a clay pill with press feedback', () => {
    render(<Button>Approve</Button>);
    const b = screen.getByRole('button', { name: 'Approve' });
    expect(b).toHaveClass(
      'rounded-full',
      'bg-primary',
      'text-primary-foreground',
      'active:scale-[.97]',
    );
  });

  it('pill shows selected state via data-selected', () => {
    render(
      <Button variant="pill" data-selected="true">
        Last quarter
      </Button>,
    );
    const b = screen.getByRole('button', { name: 'Last quarter' });
    expect(b).toHaveClass('data-[selected=true]:bg-primary');
    expect(b).toHaveAttribute('data-selected', 'true');
  });

  it('send is a 36px circle', () => {
    render(<Button variant="send" size="send" aria-label="Send" />);
    expect(screen.getByRole('button', { name: 'Send' })).toHaveClass('h-9', 'w-9', 'rounded-full');
  });

  it('keeps legacy variants working (outline, destructive, ghost)', () => {
    render(
      <>
        <Button variant="outline">o</Button>
        <Button variant="destructive">d</Button>
        <Button variant="ghost">g</Button>
      </>,
    );
    expect(screen.getByRole('button', { name: 'd' })).toHaveClass('bg-destructive');
  });
});
