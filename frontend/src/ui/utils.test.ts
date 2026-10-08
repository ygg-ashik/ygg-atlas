import { describe, expect, it } from 'vitest';
import { cn } from './utils';

describe('cn (tailwind-merge aware of DESIGN.md scales)', () => {
  it('treats DESIGN.md type sizes as font sizes, not text colors', () => {
    expect(cn('text-primary-foreground', 'text-label')).toBe('text-primary-foreground text-label');
    expect(cn('text-caption', 'text-answer')).toBe('text-answer');
  });

  it('merges DESIGN.md radii with the default radius scale', () => {
    expect(cn('rounded-full', 'rounded-glass')).toBe('rounded-glass');
  });
});
