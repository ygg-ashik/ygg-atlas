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
});
