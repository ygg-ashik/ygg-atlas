// src/features/command/command-palette.test.tsx
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { KeyRound } from 'lucide-react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { CommandPalette, type QuickAction } from './command-palette';
import { CommandTrigger } from './command-trigger';

vi.mock('@/api/hooks/use-atlas', () => ({
  useMetricsCatalog: () => ({
    data: {
      sources: [
        {
          id: 'demo',
          name: 'Commerce',
          description: '',
          funnels: [],
          metrics: [
            {
              id: 'revenue',
              name: 'Revenue',
              description: '',
              unit: 'AED',
              time_scope: 'range',
              has_breakdown: true,
              entity: 'order',
            },
          ],
        },
      ],
    },
  }),
}));
vi.mock('@/api/hooks/use-chat-sessions', () => ({
  useChatSessions: () => ({
    data: [{ id: 's1', title: 'Q3 review', created_at: '', updated_at: '' }],
  }),
}));

const PAGES = [
  { label: 'Overview', to: '/' },
  { label: 'Ask Atlas', to: '/ask' },
  { label: 'Settings › My access', to: '/settings/access' },
];
let pages = PAGES;
let actions: QuickAction[] = [];
let notified: boolean[] = [];

let path = '';
function Where() {
  const l = useLocation();
  path = l.pathname + l.search + l.hash;
  return null;
}
const setup = () =>
  render(
    <MemoryRouter initialEntries={['/ask']}>
      <Routes>
        <Route
          path="*"
          element={
            <>
              <CommandTrigger />
              <CommandPalette
                pages={pages}
                actions={actions}
                onOpenChange={(o) => notified.push(o)}
              />
              <Where />
            </>
          }
        />
      </Routes>
    </MemoryRouter>,
  );

describe('CommandPalette', () => {
  beforeEach(() => {
    pages = PAGES;
    actions = [];
    notified = [];
  });

  it('opens with ⌘K and jumps to a metric', async () => {
    setup();
    fireEvent.keyDown(window, { key: 'k', metaKey: true });
    const input = await screen.findByPlaceholderText(/Type a task/);
    await userEvent.type(input, 'reven');
    await userEvent.click(await screen.findByText('Revenue'));
    expect(path).toBe('/metrics#metric-revenue');
  });

  it('offers to ask the typed question', async () => {
    setup();
    fireEvent.keyDown(window, { key: 'k', ctrlKey: true });
    const input = await screen.findByPlaceholderText(/Type a task/);
    await userEvent.type(input, 'why did aov drop');
    await userEvent.click(await screen.findByText(/Ask: “why did aov drop”/));
    expect(path).toBe('/ask?q=why%20did%20aov%20drop');
  });

  it('jumps to a thread', async () => {
    setup();
    fireEvent.keyDown(window, { key: 'k', metaKey: true });
    await userEvent.click(await screen.findByText('Q3 review'));
    expect(path).toBe('/ask/s1');
  });

  it('opens from the sidebar trigger', async () => {
    setup();
    expect(screen.queryByPlaceholderText(/Type a task/)).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: /Search/ }));
    expect(await screen.findByPlaceholderText(/Type a task/)).toBeInTheDocument();
  });

  it('offers exactly the pages it is given, so admin pages stay out for a viewer', async () => {
    setup();
    fireEvent.keyDown(window, { key: 'k', metaKey: true });
    const input = await screen.findByPlaceholderText(/Type a task/);
    await userEvent.type(input, 'users');
    expect(screen.queryByRole('option', { name: /Users/ })).not.toBeInTheDocument();
  });

  it('jumps to a settings page when the composed pages include it', async () => {
    pages = [...PAGES, { label: 'Settings › Users', to: '/settings/admin/users' }];
    setup();
    fireEvent.keyDown(window, { key: 'k', metaKey: true });
    const input = await screen.findByPlaceholderText(/Type a task/);
    await userEvent.type(input, 'users');
    await userEvent.click(await screen.findByRole('option', { name: /Settings › Users/ }));
    expect(path).toBe('/settings/admin/users');
  });

  it('orders the groups: Quick actions, Go to, Recent threads, Metrics', async () => {
    actions = [{ id: 'a', label: 'New token', icon: KeyRound, run: vi.fn() }];
    setup();
    fireEvent.keyDown(window, { key: 'k', metaKey: true });
    const palette = await screen.findByRole('dialog');
    const headings = [...palette.querySelectorAll('[cmdk-group-heading]')].map(
      (h) => h.textContent,
    );
    expect(headings).toEqual(['Quick actions', 'Go to', 'Recent threads', 'Metrics']);
  });

  it('runs a quick action in place and closes, staying on the page', async () => {
    const run = vi.fn();
    actions = [{ id: 'a', label: 'New token', icon: KeyRound, tag: 'admin', run }];
    setup();
    fireEvent.keyDown(window, { key: 'k', metaKey: true });
    const option = await screen.findByRole('option', { name: /New token/ });
    expect(option).toHaveTextContent('admin');
    expect(option).toHaveTextContent('do it');
    await userEvent.click(option);
    expect(run).toHaveBeenCalledOnce();
    expect(path).toBe('/ask');
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
  });

  it('keeps search-only actions out until something is typed', async () => {
    actions = [
      { id: 'dark', label: 'Theme: Dark', icon: KeyRound, run: vi.fn() },
      { id: 'sys', label: 'Theme: System', icon: KeyRound, onlyWhenSearching: true, run: vi.fn() },
    ];
    setup();
    fireEvent.keyDown(window, { key: 'k', metaKey: true });
    expect(await screen.findByRole('option', { name: /Theme: Dark/ })).toBeInTheDocument();
    expect(screen.queryByRole('option', { name: /Theme: System/ })).toBeNull();
    await userEvent.type(screen.getByPlaceholderText(/Type a task/), 'theme');
    expect(await screen.findByRole('option', { name: /Theme: System/ })).toBeInTheDocument();
  });

  it('tells the composer when it opens and closes', async () => {
    setup();
    fireEvent.keyDown(window, { key: 'k', metaKey: true });
    await screen.findByRole('dialog');
    fireEvent.keyDown(window, { key: 'k', metaKey: true });
    await waitFor(() => expect(notified.slice(-2)).toEqual([true, false]));
  });
});
