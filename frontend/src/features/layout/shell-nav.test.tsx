import { render, screen } from '@testing-library/react';
import { LayoutDashboard, MessageCircle } from 'lucide-react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import { ThemeProvider } from '@/lib/theme-provider';
import Shell from './shell';

const nav = [
  { to: '/', label: 'Overview', icon: LayoutDashboard },
  { to: '/ask', label: 'Ask Atlas', icon: MessageCircle },
];

function renderAt(path: string) {
  render(
    <ThemeProvider>
      <MemoryRouter initialEntries={[path]}>
        <Shell user={null} onSignOut={() => {}} nav={nav}>
          <p>page</p>
        </Shell>
      </MemoryRouter>
    </ThemeProvider>,
  );
}

describe('Shell nav', () => {
  it('marks the root Overview link active only on / itself', () => {
    renderAt('/ask');
    expect(screen.getByRole('link', { name: /Overview/ })).not.toHaveAttribute('aria-current');
    expect(screen.getByRole('link', { name: /Ask Atlas/ })).toHaveAttribute('aria-current', 'page');
  });

  it('marks Overview active on /', () => {
    renderAt('/');
    expect(screen.getByRole('link', { name: /Overview/ })).toHaveAttribute('aria-current', 'page');
  });
});
