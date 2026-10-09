// src/ui/secret-reveal.test.tsx
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { SecretReveal } from './secret-reveal';

const TOKEN = 'atl_pat_4d1e9b0c72a64f1e8b5d3a9e07c2f816';

describe('SecretReveal', () => {
  it('shows the secret once and copies it exactly once', async () => {
    const copy = vi.fn().mockResolvedValue(undefined);
    const onCopied = vi.fn();
    render(
      <SecretReveal value={TOKEN} label="Personal token" copy={copy} onCopied={onCopied}>
        <p>Shown once.</p>
      </SecretReveal>,
    );
    expect(screen.getByRole('group', { name: 'Personal token' })).toHaveTextContent(TOKEN);
    expect(screen.getByText('Shown once.')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Copy' }));
    const done = screen.getByRole('button', { name: 'Copied' });
    await userEvent.click(done);
    expect(copy).toHaveBeenCalledOnce();
    expect(copy).toHaveBeenCalledWith(TOKEN);
    expect(onCopied).toHaveBeenCalledOnce();
    expect(screen.getByRole('status')).toHaveTextContent('Copied to clipboard');
  });

  it('concealed takes no value: only the public hint and a mask', () => {
    const { container } = render(
      <SecretReveal concealed label="Personal token" maskedHint="atl_pat_4d1e" />,
    );
    expect(container).not.toHaveTextContent(TOKEN);
    expect(screen.getByRole('group', { name: 'Personal token' })).toHaveTextContent(
      /^atl_pat_4d1e•+$/,
    );
    expect(screen.getByText(/^atl_pat_4d1e•+$/)).toHaveAttribute('data-concealed', 'true');
    expect(screen.queryByRole('button')).toBeNull();
  });

  it('states a clipboard failure and lets the user try again', async () => {
    const copy = vi.fn().mockRejectedValueOnce(new Error('denied')).mockResolvedValue(undefined);
    render(<SecretReveal value={TOKEN} label="Personal token" copy={copy} />);
    await userEvent.click(screen.getByRole('button', { name: 'Copy' }));
    expect(screen.getByRole('alert')).toHaveTextContent("Couldn't copy");
    await userEvent.click(screen.getByRole('button', { name: 'Copy' }));
    expect(screen.queryByRole('alert')).toBeNull();
    expect(copy).toHaveBeenCalledTimes(2);
  });
});
