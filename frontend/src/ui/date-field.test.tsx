// src/ui/date-field.test.tsx
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState } from 'react';
import { describe, expect, it } from 'vitest';
import { DateField, isDateFlagged, isIsoDate } from './date-field';

function Expiry({ initial = '' }: { initial?: string }) {
  const [v, setV] = useState(initial);
  return (
    <>
      <DateField aria-label="Expiry date (UTC)" value={v} onChange={(e) => setV(e.target.value)} />
      <button type="button">next</button>
    </>
  );
}

describe('DateField', () => {
  it('validates real UTC calendar dates only', () => {
    expect(isIsoDate('2027-01-07')).toBe(true);
    expect(isIsoDate('2027-02-30')).toBe(false);
    expect(isIsoDate('07/01/2027')).toBe(false);
    expect(isIsoDate('')).toBe(false);
  });

  it('judges a value only when complete or left', () => {
    expect(isDateFlagged('2027-0', false)).toBe(false);
    expect(isDateFlagged('2027-0', true)).toBe(true);
    expect(isDateFlagged('2027-13-01', false)).toBe(true);
    expect(isDateFlagged('', true)).toBe(false);
  });

  it('is a mono field that never flags mid-typing', async () => {
    render(<Expiry />);
    const input = screen.getByRole('textbox', { name: 'Expiry date (UTC)' });
    expect(input).toHaveClass('font-mono', 'w-[150px]');
    expect(input).toHaveAttribute('placeholder', 'YYYY-MM-DD');
    await userEvent.type(input, '2027-0');
    expect(input).not.toHaveAttribute('aria-invalid');
    await userEvent.type(input, '1-07');
    expect(input).not.toHaveAttribute('aria-invalid');
  });

  it('flags an unfinished date on blur and a complete bad date at once', async () => {
    render(<Expiry />);
    const input = screen.getByRole('textbox', { name: 'Expiry date (UTC)' });
    await userEvent.type(input, '2027-1');
    await userEvent.tab();
    expect(input).toHaveAttribute('aria-invalid', 'true');
    await userEvent.click(input);
    expect(input).not.toHaveAttribute('aria-invalid');
    await userEvent.type(input, '3-01');
    expect(input).toHaveAttribute('aria-invalid', 'true');
  });
});
