import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { MarkdownMessage } from './markdown-message';

describe('MarkdownMessage', () => {
  it('renders complete markdown with bold and inline code', () => {
    render(<MarkdownMessage text="Revenue was **AED 1.2M** (`revenue_total`)." />);
    expect(screen.getByText('AED 1.2M').tagName).toMatch(/STRONG|SPAN/);
    expect(screen.getByText('revenue_total')).toBeInTheDocument();
  });

  it.each([
    ['unclosed bold', 'Revenue was **AED 1.2'],
    ['unclosed code', 'See `revenue_tot'],
    ['incomplete link', 'See [the dashboard](https://exa'],
  ])('never shows raw markdown syntax while streaming (%s)', (_name, text) => {
    const { container } = render(<MarkdownMessage text={text} streaming />);
    expect(container.textContent).not.toMatch(/\*\*|`|\]\(/);
  });

  it('renders external links in a new tab and neutralizes others', () => {
    render(<MarkdownMessage text="[docs](https://example.com) and [x](javascript:alert(1))" />);
    const link = screen.getByRole('link', { name: 'docs' });
    expect(link).toHaveAttribute('target', '_blank');
    expect(link).toHaveAttribute('rel', expect.stringContaining('noopener'));
    expect(screen.queryByRole('link', { name: 'x' })).toBeNull();
  });

  it('wraps GFM tables in a horizontal scroller', () => {
    const { container } = render(<MarkdownMessage text={'| a | b |\n| - | - |\n| 1 | 2 |'} />);
    expect(container.querySelector('table')).not.toBeNull();
  });

  it('keeps the DESIGN.md type scale (streamdown must not merge custom sizes away)', () => {
    const { container } = render(<MarkdownMessage text="## Revenue" />);
    const prose = container.firstElementChild;
    expect(prose).toHaveClass('text-answer', 'text-body', '[&_h2]:text-title', '[&_th]:text-label');
  });
});
