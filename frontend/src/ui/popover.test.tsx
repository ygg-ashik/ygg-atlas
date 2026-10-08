// src/ui/popover.test.tsx
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { Popover, PopoverContent, PopoverTrigger } from './popover';

describe('Popover', () => {
  it('materializes glass content from its trigger', async () => {
    render(
      <Popover>
        <PopoverTrigger>corporate_revenue</PopoverTrigger>
        <PopoverContent>Sum of paid B2B orders</PopoverContent>
      </Popover>,
    );
    await userEvent.click(screen.getByText('corporate_revenue'));
    const content = await screen.findByText('Sum of paid B2B orders');
    expect(content).toHaveClass('glass', 'rounded-feature');
  });
});
