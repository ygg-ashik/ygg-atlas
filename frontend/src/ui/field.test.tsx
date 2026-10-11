// src/ui/field.test.tsx
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { Field, FieldError } from './field';
import { Input } from './input';

describe('Field', () => {
  it('labels its control and links the hint', () => {
    render(
      <Field label="Name" hint="Shown when revoking">
        <Input />
      </Field>,
    );
    const input = screen.getByRole('textbox', { name: 'Name' });
    expect(input).toHaveAccessibleDescription('Shown when revoking');
    expect(input).not.toHaveAttribute('aria-invalid');
  });

  it('shows an inline error and marks the control invalid', () => {
    render(
      <Field label="Name" error="Give it a name you'll recognise.">
        <Input id="tok-name" />
      </Field>,
    );
    const input = screen.getByRole('textbox', { name: 'Name' });
    expect(input).toHaveAttribute('id', 'tok-name');
    expect(input).toHaveAttribute('aria-invalid', 'true');
    expect(input).toHaveAccessibleDescription("Give it a name you'll recognise.");
  });

  it('FieldError renders the negative message with a decorative glyph', () => {
    render(<FieldError>Add a short note.</FieldError>);
    const err = screen.getByText('Add a short note.');
    expect(err).toHaveClass('text-negative');
    expect(err.querySelector('[aria-hidden]')).toHaveTextContent('!');
  });
});
