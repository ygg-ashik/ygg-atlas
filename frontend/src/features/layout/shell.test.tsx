// src/features/layout/shell.test.tsx
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { Library, MessageCircle } from 'lucide-react';
import { describe, expect, it } from 'vitest';
import { ThemeProvider } from '@/lib/theme-provider';
import Shell from './shell';

const nav = [
  { to: '/ask', label: 'Ask Atlas', icon: MessageCircle },
  { to: '/metrics', label: 'Metrics', icon: Library },
];

function renderShell() {
  return render(
    <ThemeProvider>
      <MemoryRouter initialEntries={['/ask']}>
        <Routes>
          <Route
            path="*"
            element={
              <Shell user={null} onSignOut={() => {}} nav={nav} threads={<p>threads-slot</p>}>
                <p>page-content</p>
              </Shell>
            }
          />
        </Routes>
      </MemoryRouter>
    </ThemeProvider>,
  );
}

describe('Shell', () => {
  it('renders a floating heavy-glass sidebar with nav, threads slot and content', () => {
    renderShell();
    const sidebar = screen.getByRole('complementary');
    expect(sidebar).toHaveClass('glass', 'glass-heavy', 'rounded-shell');
    expect(within(sidebar).getByRole('link', { name: /Ask Atlas/ })).toHaveAttribute(
      'aria-current',
      'page',
    );
    expect(within(sidebar).getByText('threads-slot')).toBeInTheDocument();
    expect(screen.getByRole('main')).toHaveTextContent('page-content');
  });

  it('opens the same sidebar content as a drawer from the small-screen menu button', async () => {
    renderShell();
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Open navigation' }));
    const drawer = await screen.findByRole('dialog');
    expect(within(drawer).getByRole('link', { name: /Ask Atlas/ })).toBeInTheDocument();
    expect(within(drawer).getByRole('link', { name: /Metrics/ })).toBeInTheDocument();
    expect(within(drawer).getByText('threads-slot')).toBeInTheDocument();
  });

  it('closes the drawer when a nav link is followed', async () => {
    renderShell();
    await userEvent.click(screen.getByRole('button', { name: 'Open navigation' }));
    const drawer = await screen.findByRole('dialog');
    await userEvent.click(within(drawer).getByRole('link', { name: /Metrics/ }));
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
  });

  it('closes the drawer on Escape', async () => {
    renderShell();
    await userEvent.click(screen.getByRole('button', { name: 'Open navigation' }));
    await screen.findByRole('dialog');
    await userEvent.keyboard('{Escape}');
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
  });
});
