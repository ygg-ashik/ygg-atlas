// src/ui/sidebar-section-header.test.tsx
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { SidebarSectionHeader } from './sidebar-section-header';

describe('SidebarSectionHeader', () => {
  it('labels a nav group as an uppercase micro-heading', () => {
    render(
      <nav aria-labelledby="sec-admin">
        <SidebarSectionHeader id="sec-admin">Admin</SidebarSectionHeader>
      </nav>,
    );
    expect(screen.getByRole('heading', { name: 'Admin' })).toHaveClass('uppercase');
    expect(screen.getByRole('navigation', { name: 'Admin' })).toBeInTheDocument();
  });
});
