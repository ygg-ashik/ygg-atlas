// src/ui/dialog.test.tsx
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { Dialog, DialogContent, DialogDescription, DialogTitle, DialogTrigger } from './dialog';

describe('Dialog (DESIGN.md › dialog)', () => {
  it('opens a solid panel over the scrim, closes on Escape and the close button', async () => {
    render(
      <Dialog>
        <DialogTrigger>New token</DialogTrigger>
        <DialogContent>
          <DialogTitle>New personal token</DialogTitle>
          <DialogDescription>It acts as you over MCP.</DialogDescription>
        </DialogContent>
      </Dialog>,
    );
    await userEvent.click(screen.getByRole('button', { name: 'New token' }));
    const dialog = screen.getByRole('dialog', { name: 'New personal token' });
    expect(dialog).toHaveClass(
      'bg-card',
      'rounded-shell',
      'data-[state=open]:animate-materialize-in',
    );
    expect(dialog).toHaveAccessibleDescription('It acts as you over MCP.');
    expect(screen.getByRole('heading', { name: 'New personal token' })).toHaveClass('font-serif');
    await userEvent.keyboard('{Escape}');
    expect(screen.queryByRole('dialog')).toBeNull();
    await userEvent.click(screen.getByRole('button', { name: 'New token' }));
    await userEvent.click(screen.getByRole('button', { name: 'Close' }));
    expect(screen.queryByRole('dialog')).toBeNull();
  });
});
