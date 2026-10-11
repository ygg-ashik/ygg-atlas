// src/ui/user-chip.test.tsx
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { UserChip } from './user-chip';

describe('UserChip', () => {
  it('shows avatar initials, name, truncated email and role', () => {
    render(<UserChip name="Ashik Babu" email="ashik@yougotagift.com" role={<span>admin</span>} />);
    expect(screen.getByText('AB')).toBeInTheDocument();
    expect(screen.getByText('Ashik Babu')).toBeInTheDocument();
    expect(screen.getByText('ashik@yougotagift.com')).toHaveClass('truncate');
    expect(screen.getByText('admin')).toBeInTheDocument();
  });

  it('falls back to the email for initials when the name is empty', () => {
    render(<UserChip name="" email="lina@yougotagift.com" />);
    expect(screen.getByText('L')).toBeInTheDocument();
  });
});
