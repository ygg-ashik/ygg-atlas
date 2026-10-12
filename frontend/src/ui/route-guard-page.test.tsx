// src/ui/route-guard-page.test.tsx
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { RouteGuardPage } from './route-guard-page';

describe('RouteGuardPage', () => {
  it('states the missing capability, why, and the next steps', () => {
    render(
      <RouteGuardPage
        capability="admin:users"
        route="/settings/admin/users"
        role="viewer"
        actions={<button type="button">Go to My access</button>}
      />,
    );
    const page = screen.getByRole('region', { name: 'This area needs admin:users' });
    expect(page).toHaveTextContent('Your role (viewer)');
    expect(page).toHaveTextContent('/settings/admin/users stays closed');
    expect(page).toHaveTextContent('Nothing you type can widen it.');
    expect(screen.getByText('scope · from your Google sign-in')).toBeInTheDocument();
    expect(screen.getByText('role · viewer')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Go to My access' })).toBeInTheDocument();
  });
});
