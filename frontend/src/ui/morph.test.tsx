// src/ui/morph.test.tsx
import { render } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

const reduced = vi.hoisted(() => ({ value: false }));
vi.mock('motion/react', async (importOriginal) => ({
  ...(await importOriginal<object>()),
  useReducedMotion: () => reduced.value,
}));

import { Morph } from './morph';

const part = (c: HTMLElement, p: string) =>
  c.querySelector(`[data-morph-part="${p}"]`) as HTMLElement;

describe('Morph', () => {
  afterEach(() => {
    reduced.value = false;
  });

  it('shows the from label and hides the to label from assistive tech', () => {
    const { container } = render(<Morph done={false} from="Copy" to="✓ Copied" />);
    expect(container.querySelector('[data-morph]')).toHaveAttribute('data-morph', 'idle');
    expect(part(container, 'from')).toHaveAttribute('aria-hidden', 'false');
    expect(part(container, 'to')).toHaveAttribute('aria-hidden', 'true');
    expect(part(container, 'to').style.filter).toContain('blur(3px)');
  });

  it('swaps in place when done', () => {
    const { container } = render(<Morph done from="Copy" to="✓ Copied" />);
    expect(container.querySelector('[data-morph]')).toHaveAttribute('data-morph', 'done');
    expect(part(container, 'to')).toHaveAttribute('aria-hidden', 'false');
    expect(part(container, 'from')).toHaveAttribute('aria-hidden', 'true');
  });

  it('reduced motion is a plain cross-fade: no blur, no scale', () => {
    reduced.value = true;
    const { container } = render(<Morph done={false} from="Copy" to="✓ Copied" />);
    const hidden = part(container, 'to');
    expect(hidden.style.opacity).toBe('0');
    expect(hidden.style.filter).toBe('');
    expect(hidden.style.transform).toBe('');
  });
});
