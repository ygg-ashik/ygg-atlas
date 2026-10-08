// src/ui/glass.test.tsx
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { Glass } from './glass';

describe('Glass', () => {
  it('renders the chrome material by default', () => {
    render(<Glass data-testid="g">x</Glass>);
    const el = screen.getByTestId('g');
    expect(el).toHaveClass('glass');
    expect(el).not.toHaveClass('glass-heavy');
    expect(el.tagName).toBe('DIV');
  });

  it('supports the heavy variant and a semantic element', () => {
    render(
      <Glass as="aside" variant="heavy" data-testid="g">
        x
      </Glass>,
    );
    const el = screen.getByTestId('g');
    expect(el).toHaveClass('glass', 'glass-heavy');
    expect(el.tagName).toBe('ASIDE');
  });

  it('tracks the pointer for the specular highlight only when enabled', () => {
    render(
      <Glass specular data-testid="g">
        x
      </Glass>,
    );
    const el = screen.getByTestId('g');
    expect(el).toHaveClass('glass-specular');
    fireEvent.pointerMove(el, { clientX: 40, clientY: 12 });
    expect(el.style.getPropertyValue('--spec-x')).toBe('40px');
    expect(el.style.getPropertyValue('--spec-y')).toBe('12px');
  });

  it('does not set specular vars when disabled', () => {
    render(<Glass data-testid="g">x</Glass>);
    const el = screen.getByTestId('g');
    fireEvent.pointerMove(el, { clientX: 40, clientY: 12 });
    expect(el.style.getPropertyValue('--spec-x')).toBe('');
  });
});
