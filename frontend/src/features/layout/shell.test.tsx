// src/features/layout/shell.test.tsx
import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { location, renderShell } from './test-shell';

const sidebar = () => screen.getByRole('complementary');

describe('Shell', () => {
  it('renders a floating heavy-glass sidebar with nav, threads slot and content', () => {
    renderShell('/ask');
    expect(sidebar()).toHaveClass('glass', 'glass-heavy', 'rounded-shell');
    expect(within(sidebar()).getByRole('link', { name: /Ask Atlas/ })).toHaveAttribute(
      'aria-current',
      'page',
    );
    expect(within(sidebar()).getByText('threads-slot')).toBeInTheDocument();
    expect(screen.getByRole('main')).toHaveTextContent('page-content');
  });

  it('keeps settings and admin out of the app sidebar', () => {
    renderShell('/ask');
    expect(within(sidebar()).queryByRole('group')).not.toBeInTheDocument();
    expect(within(sidebar()).queryByRole('link', { name: /Users|My access/ })).toBeNull();
  });

  it('opens the same sidebar content as a drawer from the small-screen menu button', async () => {
    renderShell('/ask');
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Open navigation' }));
    const drawer = await screen.findByRole('dialog');
    expect(within(drawer).getByRole('link', { name: /Metrics/ })).toBeInTheDocument();
    expect(within(drawer).getByText('threads-slot')).toBeInTheDocument();
  });

  it('closes the drawer when a nav link is followed', async () => {
    renderShell('/ask');
    await userEvent.click(screen.getByRole('button', { name: 'Open navigation' }));
    const drawer = await screen.findByRole('dialog');
    await userEvent.click(within(drawer).getByRole('link', { name: /Metrics/ }));
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
  });

  it('closes the drawer on Escape', async () => {
    renderShell('/ask');
    await userEvent.click(screen.getByRole('button', { name: 'Open navigation' }));
    await screen.findByRole('dialog');
    await userEvent.keyboard('{Escape}');
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
  });
});

describe('Settings rail', () => {
  it('swaps the sidebar in place: back, title, You and Organization', () => {
    renderShell('/settings/admin/users');
    const side = sidebar();
    expect(within(side).getByRole('button', { name: /Back to Atlas/ })).toBeInTheDocument();
    expect(within(side).getByRole('heading', { name: 'Settings' })).toBeInTheDocument();
    const you = within(side).getByRole('group', { name: 'You' });
    expect(
      within(you)
        .getAllByRole('link')
        .map((l) => l.getAttribute('href')),
    ).toEqual(['/settings', '/settings/access']);
    expect(within(side).getByRole('group', { name: 'Organization' })).toBeInTheDocument();
    expect(within(side).getByRole('link', { name: /Users/ })).toHaveAttribute(
      'aria-current',
      'page',
    );
    expect(within(side).getByRole('link', { name: /Access requests/ })).toHaveTextContent(
      '3 requests to decide',
    );
    expect(within(side).queryByText('threads-slot')).not.toBeInTheDocument();
    expect(within(side).getByText('sara@yougotagift.com')).toBeInTheDocument();
  });

  it('lights General only on /settings itself', () => {
    renderShell('/settings/access');
    expect(within(sidebar()).getByRole('link', { name: /General/ })).not.toHaveAttribute(
      'aria-current',
    );
  });

  it('Back to Atlas returns to the last page outside Settings', async () => {
    renderShell('/metrics');
    fireEvent.keyDown(window, { key: ',', metaKey: true });
    await waitFor(() => expect(location.current).toBe('/settings'));
    await userEvent.click(within(sidebar()).getByRole('button', { name: /Back to Atlas/ }));
    expect(location.current).toBe('/metrics');
  });

  it('Escape leaves Settings', async () => {
    renderShell('/ask');
    fireEvent.keyDown(window, { key: ',', ctrlKey: true });
    await waitFor(() => expect(location.current).toBe('/settings'));
    fireEvent.keyDown(document.body, { key: 'Escape' });
    expect(location.current).toBe('/ask');
  });

  it('Escape in a field or an open menu stays in Settings', async () => {
    renderShell('/settings/admin/users');
    fireEvent.keyDown(screen.getByRole('textbox', { name: 'page field' }), { key: 'Escape' });
    expect(location.current).toBe('/settings/admin/users');
    await userEvent.click(screen.getByRole('button', { name: 'Open navigation' }));
    await screen.findByRole('dialog');
    fireEvent.keyDown(document.body, { key: 'Escape' });
    expect(location.current).toBe('/settings/admin/users');
  });

  it('Escape outside Settings does nothing', () => {
    renderShell('/metrics');
    fireEvent.keyDown(document.body, { key: 'Escape' });
    expect(location.current).toBe('/metrics');
  });

  it('a deep link into Settings goes back to Overview', async () => {
    renderShell('/settings/access');
    await userEvent.click(within(sidebar()).getByRole('button', { name: /Back to Atlas/ }));
    expect(location.current).toBe('/');
  });
});
