// src/ui/textarea.test.tsx
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { Textarea } from './textarea';

describe('Textarea', () => {
  it('is a resizable multi-line field', async () => {
    render(<Textarea aria-label="Why do you need it?" />);
    const area = screen.getByRole('textbox', { name: 'Why do you need it?' });
    expect(area).toHaveClass('min-h-[84px]', 'resize-y');
    await userEvent.type(area, 'Q4 redesign');
    expect(area).toHaveValue('Q4 redesign');
  });
});
