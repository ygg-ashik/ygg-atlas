// src/ui/filter-bar.test.tsx
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState } from 'react';
import { describe, expect, it } from 'vitest';
import { FilterBar } from './filter-bar';
import { Select } from './select';

function Bar() {
  const [q, setQ] = useState('');
  return (
    <FilterBar
      label="Filter users"
      search={{ value: q, onChange: setQ, placeholder: 'Search name or email', label: 'Search' }}
      summary={`${q.length} chars`}
    >
      <Select aria-label="Role">
        <option>Role: any</option>
      </Select>
    </FilterBar>
  );
}

describe('FilterBar', () => {
  it('is a search landmark with a controlled search box, filters and a summary', async () => {
    render(<Bar />);
    expect(screen.getByRole('search', { name: 'Filter users' })).toBeInTheDocument();
    expect(screen.getByRole('combobox', { name: 'Role' })).toBeInTheDocument();
    const box = screen.getByRole('searchbox', { name: 'Search' });
    await userEvent.type(box, 'sara');
    expect(box).toHaveValue('sara');
    expect(screen.getByText('4 chars')).toHaveClass('tabular-nums');
  });
});
