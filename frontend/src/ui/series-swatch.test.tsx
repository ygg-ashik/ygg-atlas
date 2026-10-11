// src/ui/series-swatch.test.tsx
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { SeriesSwatch, seriesFill } from './series-swatch';

describe('series hatch', () => {
  it('second series adds the hatch pattern to the accent fill', () => {
    expect(seriesFill('primary')).toBe('bg-primary-text');
    expect(seriesFill('secondary')).toBe('bg-primary-text series-hatch');
  });

  it('legend swatch uses the same pattern and is decorative', () => {
    render(<SeriesSwatch series="secondary">deny</SeriesSwatch>);
    const swatch = screen.getByText('deny').querySelector('[data-series]');
    expect(swatch).toHaveAttribute('aria-hidden');
    expect(swatch).toHaveClass('series-hatch');
  });
});
