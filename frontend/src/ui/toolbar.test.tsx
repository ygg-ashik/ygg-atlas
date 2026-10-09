// src/ui/toolbar.test.tsx
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { Toolbar } from './toolbar';

describe('Toolbar', () => {
  it('renders a floating glass capsule with a serif title and actions', () => {
    render(
      <Toolbar title="Q3 revenue review">
        <button type="button">Search</button>
      </Toolbar>,
    );
    const heading = screen.getByRole('heading', { name: 'Q3 revenue review' });
    expect(heading).toHaveClass('font-serif');
    const bar = heading.closest('header');
    expect(bar).toHaveClass('glass', 'glass-specular', 'rounded-glass');
    expect(screen.getByRole('button', { name: 'Search' })).toBeInTheDocument();
  });

  it('shows an optional mono route label that hides below 1000px', () => {
    render(<Toolbar title="Users" route="/admin/users" />);
    const route = screen.getByText('/admin/users');
    expect(route).toHaveAttribute('data-route-label');
    expect(route).toHaveClass('font-mono', 'max-[999px]:hidden');
  });
});
