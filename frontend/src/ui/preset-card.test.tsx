// src/ui/preset-card.test.tsx
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { PresetCard } from './preset-card';

describe('PresetCard (Higgsfield-style preset)', () => {
  it('is a button with title, description and a preview that plays on hover', async () => {
    const onSelect = vi.fn();
    render(
      <PresetCard
        title="Revenue review"
        description="Trend, drivers"
        preview="line"
        onSelect={onSelect}
      />,
    );
    const card = screen.getByRole('button', { name: /Revenue review/ });
    expect(card).toHaveClass('group', 'rounded-feature');
    expect(card.querySelector('[data-preview="line"]')).not.toBeNull();
    await userEvent.click(card);
    expect(onSelect).toHaveBeenCalledOnce();
  });

  it.each(['line', 'bars', 'funnel'] as const)('renders the %s preview', (preview) => {
    render(<PresetCard title="t" preview={preview} onSelect={() => {}} />);
    expect(document.querySelector(`[data-preview="${preview}"]`)).not.toBeNull();
  });

  it('line preview is visible at rest and draws on to full strength on hover', () => {
    render(<PresetCard title="t" preview="line" onSelect={() => {}} />);
    const rest = document.querySelector('[data-line="rest"]');
    expect(rest).not.toBeNull();
    // Fully drawn (no dash offset) but faint, so the card never looks empty.
    expect(rest).toHaveAttribute('stroke-opacity', '0.25');
    expect(rest?.getAttribute('class')).not.toMatch(/dashoffset/);
    const play = document.querySelector('[data-line="play"]');
    expect(play?.getAttribute('class')).toMatch(/group-hover:\[stroke-dashoffset:0\]/);
    expect(play?.getAttribute('d')).toBe(rest?.getAttribute('d'));
  });
});
