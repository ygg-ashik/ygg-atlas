// src/features/layout/shell.test.tsx
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { MessageCircle } from 'lucide-react';
import { describe, expect, it } from 'vitest';
import { ThemeProvider } from '@/lib/theme-provider';
import Shell from './shell';

const nav = [{ to: '/ask', label: 'Ask Atlas', icon: MessageCircle }];

describe('Shell', () => {
  it('renders a floating heavy-glass sidebar with nav, threads slot and content', () => {
    render(
      <ThemeProvider>
        <MemoryRouter initialEntries={['/ask']}>
          <Shell user={null} onSignOut={() => {}} nav={nav} threads={<p>threads-slot</p>}>
            <p>page-content</p>
          </Shell>
        </MemoryRouter>
      </ThemeProvider>,
    );
    const sidebar = screen.getByRole('complementary');
    expect(sidebar).toHaveClass('glass', 'glass-heavy', 'rounded-shell');
    expect(screen.getByRole('link', { name: /Ask Atlas/ })).toHaveAttribute('aria-current', 'page');
    expect(screen.getByText('threads-slot')).toBeInTheDocument();
    expect(screen.getByRole('main')).toHaveTextContent('page-content');
  });
});
