// src/ui/role-pill.test.tsx
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { RolePill } from './role-pill';

describe('RolePill', () => {
  it('shows the role name with a decorative clay diamond', () => {
    render(<RolePill role="manager" />);
    const pill = screen.getByText('manager');
    expect(pill).toHaveClass('rounded-full', 'bg-card-2', 'text-ink');
    expect(pill.querySelector('b')).toHaveAttribute('aria-hidden');
  });
});
