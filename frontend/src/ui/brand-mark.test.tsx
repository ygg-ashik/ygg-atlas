import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { BrandMark } from './brand-mark';

describe('BrandMark', () => {
  it('names the product with the wordmark and hides the decorative diamond', () => {
    const { container } = render(<BrandMark />);
    expect(screen.getByText('Atlas')).toBeInTheDocument();
    const diamond = container.querySelector('[data-brand-diamond]');
    expect(diamond).toHaveAttribute('aria-hidden', 'true');
    expect(diamond).toHaveClass('bg-primary', 'rotate-45');
  });

  it('scales the diamond with the wordmark at display size', () => {
    const { container } = render(<BrandMark size="display" />);
    expect(screen.getByText('Atlas')).toHaveClass('text-display');
    expect(container.querySelector('[data-brand-diamond]')).toHaveClass('h-3.5', 'w-3.5');
  });
});
