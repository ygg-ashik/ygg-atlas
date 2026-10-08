import { render } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ThemeProvider } from './theme-provider';

const root = () => document.documentElement;

afterEach(() => {
  vi.unstubAllGlobals();
  localStorage.clear();
  root().classList.remove('light', 'dark');
});

describe('ThemeProvider', () => {
  it('starts in light, not the system theme, when nothing is stored', () => {
    // The OS prefers dark; Atlas still opens in light until the user opts in.
    vi.stubGlobal('matchMedia', (query: string) => ({
      matches: query.includes('dark'),
      media: query,
      addEventListener: () => {},
      removeEventListener: () => {},
    }));
    render(<ThemeProvider>x</ThemeProvider>);
    expect(root()).toHaveClass('light');
    expect(root()).not.toHaveClass('dark');
  });

  it('keeps a theme the user chose before', () => {
    localStorage.setItem('ygg-atlas-theme', 'dark');
    render(<ThemeProvider>x</ThemeProvider>);
    expect(root()).toHaveClass('dark');
  });
});
