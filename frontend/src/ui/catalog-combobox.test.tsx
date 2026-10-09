// src/ui/catalog-combobox.test.tsx
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { type CatalogOption, CatalogCombobox } from './catalog-combobox';

const OPTIONS: CatalogOption[] = [
  { value: 'demo/*', label: 'Commerce', kind: 'source' },
  { value: 'demo/order/*', label: 'Orders', kind: 'entity' },
  { value: 'demo/order/revenue', label: 'Revenue', kind: 'metric' },
];

function setup() {
  const onValueChange = vi.fn();
  render(
    <CatalogCombobox label="Target" options={OPTIONS} value="" onValueChange={onValueChange} />,
  );
  return { onValueChange, input: screen.getByRole('combobox', { name: 'Target' }) };
}

describe('CatalogCombobox', () => {
  it('is a mono combobox that opens a glass list on focus', async () => {
    const { input } = setup();
    expect(input).toHaveClass('font-mono');
    expect(input).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByRole('listbox')).toBeNull();
    await userEvent.click(input);
    expect(input).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByRole('listbox')).toHaveClass('glass', 'rounded-shell');
    expect(screen.getAllByRole('option')).toHaveLength(3);
  });

  it('filters by path or name and picks with the keyboard', async () => {
    const { input, onValueChange } = setup();
    await userEvent.type(input, 'revenue');
    expect(screen.getAllByRole('option')).toHaveLength(1);
    await userEvent.keyboard('{Enter}');
    expect(onValueChange).toHaveBeenCalledWith('demo/order/revenue');
    expect(input).toHaveValue('demo/order/revenue');
    expect(screen.queryByRole('listbox')).toBeNull();
  });

  it('picks with the mouse and closes on Escape', async () => {
    const { input, onValueChange } = setup();
    await userEvent.type(input, 'Orders');
    await userEvent.click(screen.getByRole('option', { name: /Orders/ }));
    expect(onValueChange).toHaveBeenCalledWith('demo/order/*');
    await userEvent.type(input, 'x');
    expect(screen.getByRole('listbox')).toBeInTheDocument();
    await userEvent.keyboard('{Escape}');
    expect(screen.queryByRole('listbox')).toBeNull();
  });

  it('says so when nothing matches', async () => {
    const { input } = setup();
    await userEvent.type(input, 'zzz');
    expect(screen.getByText('No catalog path matches')).toBeInTheDocument();
  });
});

describe('CatalogCombobox value sync', () => {
  it('restores the chosen path on blur and follows new values from the parent', async () => {
    const { rerender } = render(
      <CatalogCombobox label="Target" options={OPTIONS} value="demo/*" onValueChange={() => {}} />,
    );
    const input = screen.getByRole('combobox', { name: 'Target' });
    expect(input).toHaveValue('demo/*');
    await userEvent.type(input, 'abc');
    expect(input).toHaveValue('demo/*abc');
    await userEvent.tab();
    expect(input).toHaveValue('demo/*');
    rerender(
      <CatalogCombobox label="Target" options={OPTIONS} value="" onValueChange={() => {}} />,
    );
    expect(input).toHaveValue('');
  });
});
