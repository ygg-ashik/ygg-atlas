// src/features/command/command-palette.test.tsx
import { fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { CommandPalette } from './command-palette';
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
  { label: 'My access', to: '/account' },
];
let pages = PAGES;

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
              <CommandPalette pages={pages} />
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
  });

  it('opens with ⌘K and jumps to a metric', async () => {
    setup();
    fireEvent.keyDown(window, { key: 'k', metaKey: true });
    const input = await screen.findByPlaceholderText(/Search metrics, threads/);
    await userEvent.type(input, 'reven');
    await userEvent.click(await screen.findByText('Revenue'));
    expect(path).toBe('/metrics#metric-revenue');
  });

  it('offers to ask the typed question', async () => {
    setup();
    fireEvent.keyDown(window, { key: 'k', ctrlKey: true });
    const input = await screen.findByPlaceholderText(/Search metrics, threads/);
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
    expect(screen.queryByPlaceholderText(/Search metrics, threads/)).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: /Search/ }));
    expect(await screen.findByPlaceholderText(/Search metrics, threads/)).toBeInTheDocument();
  });

  it('offers exactly the pages it is given, so admin pages stay out for a viewer', async () => {
    setup();
    fireEvent.keyDown(window, { key: 'k', metaKey: true });
    const input = await screen.findByPlaceholderText(/Search metrics, threads/);
    await userEvent.type(input, 'users');
    expect(screen.queryByRole('option', { name: 'Users' })).not.toBeInTheDocument();
  });

  it('jumps to an admin page when the composed pages include it', async () => {
    pages = [...PAGES, { label: 'Users', to: '/admin/users' }];
    setup();
    fireEvent.keyDown(window, { key: 'k', metaKey: true });
    const input = await screen.findByPlaceholderText(/Search metrics, threads/);
    await userEvent.type(input, 'users');
    await userEvent.click(await screen.findByRole('option', { name: 'Users' }));
    expect(path).toBe('/admin/users');
  });
});
