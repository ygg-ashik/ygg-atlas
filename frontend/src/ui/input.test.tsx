// src/ui/input.test.tsx
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { Input } from './input';

describe('Input', () => {
  it('is a solid text field that accepts typing', async () => {
    render(<Input aria-label="Name" />);
    const input = screen.getByRole('textbox', { name: 'Name' });
    expect(input).toHaveClass('bg-card', 'rounded-md', 'focus-visible:ring-primary/15');
    await userEvent.type(input, 'Eval runner');
    expect(input).toHaveValue('Eval runner');
  });

  it('has a mono variant and an invalid state', () => {
    render(<Input aria-label="Path" mono invalid />);
    const input = screen.getByRole('textbox', { name: 'Path' });
    expect(input).toHaveClass('font-mono');
    expect(input).toHaveAttribute('aria-invalid', 'true');
  });
});
