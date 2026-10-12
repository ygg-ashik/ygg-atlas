// src/ui/theme-switch.test.tsx
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { ThemeSwitch } from './theme-switch';

describe('ThemeSwitch', () => {
  it('is a labelled radio group with the current theme checked', () => {
    render(<ThemeSwitch value="dark" onChange={() => {}} />);
    const group = screen.getByRole('radiogroup', { name: 'Theme' });
    expect(group).toBeInTheDocument();
    expect(screen.getByRole('radio', { name: 'Dark' })).toHaveAttribute('aria-checked', 'true');
    expect(screen.getByRole('radio', { name: 'Light' })).toHaveAttribute('aria-checked', 'false');
  });

  it('reports the chosen theme', async () => {
    const onChange = vi.fn();
    render(<ThemeSwitch value="light" onChange={onChange} />);
    await userEvent.click(screen.getByRole('radio', { name: 'System' }));
    expect(onChange).toHaveBeenCalledWith('system');
  });
});
