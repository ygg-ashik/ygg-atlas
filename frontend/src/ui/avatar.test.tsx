// src/ui/avatar.test.tsx
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { Avatar, initials } from './avatar';

describe('Avatar', () => {
  it('derives up to two initials', () => {
    expect(initials('Sara Mansour')).toBe('SM');
    expect(initials('ana-maria de souza')).toBe('AM');
    expect(initials('omar')).toBe('O');
  });

  it('is decorative beside a name, labelled when alone', () => {
    const { container } = render(<Avatar name="Sara Mansour" />);
    expect(container.firstChild).toHaveAttribute('aria-hidden', 'true');
    expect(container.firstChild).toHaveTextContent('SM');
    render(<Avatar name="Sara Mansour" label="Sara Mansour" size="lg" />);
    expect(screen.getByRole('img', { name: 'Sara Mansour' })).toHaveClass('h-12');
  });

  it('service identities are a rounded square with a glyph', () => {
    const { container } = render(<Avatar name="eval-runner" kind="service" />);
    expect(container.firstChild).toHaveAttribute('data-kind', 'service');
    expect(container.firstChild).toHaveClass('rounded-[10px]', 'bg-card-2');
    expect(container.querySelector('svg')).not.toBeNull();
  });
});
