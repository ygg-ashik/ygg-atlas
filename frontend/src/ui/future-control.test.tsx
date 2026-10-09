// src/ui/future-control.test.tsx
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { FutureControl } from './future-control';

describe('FutureControl', () => {
  it('shows a disabled, inert preview with what it waits for', () => {
    const { container } = render(
      <FutureControl label="Row scope">
        <button type="button">+ dimension</button>
      </FutureControl>,
    );
    expect(container.firstChild).toHaveAttribute('aria-disabled', 'true');
    expect(container.querySelector('[data-future-preview]')).toHaveAttribute('inert');
    expect(screen.getByText('Arrives with row and field controls')).toBeInTheDocument();
    expect(screen.getByText('Row scope')).toBeInTheDocument();
  });
});
