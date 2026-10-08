// src/ui/tokens.test.ts
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';

// Path-based: happy-dom swaps the global URL, so `new URL(..., import.meta.url)` breaks here.
const css = readFileSync(join(import.meta.dirname, '../index.css'), 'utf8');

function block(selector: string): string {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const match = css.match(new RegExp(`${escaped}\\s*\\{([^}]*)\\}`));
  return match?.[1] ?? '';
}

const LIGHT = [
  'background',
  'foreground',
  'card',
  'card-foreground',
  'card-2',
  'popover',
  'popover-foreground',
  'primary',
  'primary-foreground',
  'primary-text',
  'secondary',
  'secondary-foreground',
  'muted',
  'muted-foreground',
  'muted-2',
  'accent',
  'accent-foreground',
  'destructive',
  'destructive-foreground',
  'border',
  'input',
  'ring',
  'canvas',
  'surface',
  'ink',
  'body',
  'positive',
  'negative',
  'warning',
  'glass',
  'glass-heavy',
  'glass-edge',
  'glass-shadow',
  'glass-spec',
  'wash',
];

describe('design tokens (DESIGN.md contract)', () => {
  it.each(LIGHT)('light theme defines --%s', (name) => {
    expect(block(':root')).toContain(`--${name}:`);
  });

  it.each(LIGHT.filter((n) => n !== 'primary-foreground'))('dark theme defines --%s', (name) => {
    expect(block('.dark')).toContain(`--${name}:`);
  });

  it('primary is the DESIGN.md clay #b45536', () => {
    expect(block(':root')).toMatch(/--primary:\s*15 53\.8% 45\.9%;/);
  });

  it('dark text/links use primary-on-dark #d97a57', () => {
    expect(block('.dark')).toMatch(/--primary-text:\s*16 63\.1% 59\.6%;/);
  });

  it('falls back to solid surfaces for reduced transparency', () => {
    expect(css).toContain('@media (prefers-reduced-transparency: reduce)');
  });
});
