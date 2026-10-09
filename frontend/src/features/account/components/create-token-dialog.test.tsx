import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { createQueryWrapper } from '@/api/hooks/test-query-wrapper';
import { httpError } from '@/api/test-support';
import { type TokenCreate, type TokenCreated } from '@/api/tokens';
import { Button } from '@/ui';
import { CreateTokenDialog, expiryChoices } from './create-token-dialog';

const createMyToken = vi.hoisted(() => vi.fn<(body: TokenCreate) => Promise<TokenCreated>>());
// The real token client is spread in; its axios instance pulls in the Firebase SDK.
vi.mock('@/lib/firebase', () => ({ auth: {}, googleProvider: {} }));
vi.mock('@/api/tokens', async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  createMyToken,
}));

const SECRET = 'atl_pat_4d1e9b0c72a64f1e8b5d3a9e07c2f816';
const CREATED: TokenCreated = {
  id: 't-new',
  kind: 'pat',
  name: 'Eval runner',
  prefix: 'atl_pat_4d1e',
  user_id: 'u1',
  client_id: null,
  created_at: '2026-10-09T09:00:00Z',
  expires_at: '2027-01-07T09:00:00Z',
  last_used_at: null,
  revoked_at: null,
  revoked_reason: null,
  token: SECRET,
};

function Host({ maxDays = 365, defaultDays = 90 }: { maxDays?: number; defaultDays?: number }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <Button onClick={() => setOpen(true)}>New token</Button>
      <CreateTokenDialog
        open={open}
        onOpenChange={setOpen}
        pat={{ default_days: defaultDays, max_days: maxDays }}
      />
    </>
  );
}

function renderDialog(props: { maxDays?: number; defaultDays?: number } = {}) {
  const { wrapper: Wrapper } = createQueryWrapper();
  render(
    <Wrapper>
      <Host {...props} />
    </Wrapper>,
  );
  const user = userEvent.setup({ delay: null });
  return user;
}

async function openForm(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole('button', { name: 'New token' }));
  return screen.findByRole('dialog', { name: 'New personal token' });
}

describe('expiryChoices', () => {
  it('offers only lifetimes up to max_days, always including the default', () => {
    expect(expiryChoices({ default_days: 90, max_days: 365 })).toEqual([30, 90, 180, 365]);
    expect(expiryChoices({ default_days: 60, max_days: 90 })).toEqual([30, 60, 90]);
    expect(expiryChoices({ default_days: 7, max_days: 14 })).toEqual([7, 14]);
  });

  it('clamps a default above the maximum to the maximum', () => {
    expect(expiryChoices({ default_days: 400, max_days: 200 })).toEqual([30, 90, 180, 200]);
  });
});

describe('CreateTokenDialog', () => {
  beforeEach(() => {
    createMyToken.mockReset().mockResolvedValue(CREATED);
  });

  it('defaults to default_days and never offers more than max_days', async () => {
    const user = renderDialog({ maxDays: 180, defaultDays: 90 });
    const dialog = await openForm(user);
    const expiry = within(dialog).getByRole('radiogroup', { name: 'Expires' });
    const options = within(expiry)
      .getAllByRole('radio')
      .map((r) => r.textContent);
    expect(options).toEqual(['30 days', '90 days', '180 days']);
    expect(within(expiry).getByRole('radio', { name: '90 days' })).toHaveAttribute(
      'aria-checked',
      'true',
    );
  });

  it('needs a name before it creates anything', async () => {
    const user = renderDialog();
    const dialog = await openForm(user);
    await user.click(within(dialog).getByRole('button', { name: 'Create token' }));
    expect(within(dialog).getByText(/Give it a name you'll recognise/)).toBeInTheDocument();
    expect(createMyToken).not.toHaveBeenCalled();
  });

  it('creates with the chosen expiry and shows the secret once', async () => {
    const user = renderDialog();
    const dialog = await openForm(user);
    await user.type(within(dialog).getByRole('textbox', { name: 'Name' }), 'Eval runner');
    await user.click(within(dialog).getByRole('radio', { name: '180 days' }));
    await user.click(within(dialog).getByRole('button', { name: 'Create token' }));
    expect(createMyToken).toHaveBeenCalledWith({ name: 'Eval runner', expires_in_days: 180 });
    const reveal = await screen.findByRole('dialog', { name: 'Copy your token' });
    expect(within(reveal).getByText(SECRET)).toBeInTheDocument();
    expect(within(reveal).getByText(/Shown once/)).toBeInTheDocument();
  });

  it('Done drops the secret: reopening shows a blank form, never the old token', async () => {
    const user = renderDialog();
    const dialog = await openForm(user);
    await user.type(within(dialog).getByRole('textbox', { name: 'Name' }), 'Eval runner');
    await user.click(within(dialog).getByRole('button', { name: 'Create token' }));
    const reveal = await screen.findByRole('dialog', { name: 'Copy your token' });
    await user.click(within(reveal).getByRole('button', { name: 'Done' }));
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    expect(screen.queryByText(SECRET)).not.toBeInTheDocument();
    const again = await openForm(user);
    expect(within(again).getByRole('textbox', { name: 'Name' })).toHaveValue('');
    expect(screen.queryByText(SECRET)).not.toBeInTheDocument();
  });

  it('closing the reveal any other way also drops the secret', async () => {
    const user = renderDialog();
    const dialog = await openForm(user);
    await user.type(within(dialog).getByRole('textbox', { name: 'Name' }), 'Eval runner');
    await user.click(within(dialog).getByRole('button', { name: 'Create token' }));
    await screen.findByRole('dialog', { name: 'Copy your token' });
    await user.keyboard('{Escape}');
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    await openForm(user);
    expect(screen.queryByText(SECRET)).not.toBeInTheDocument();
  });

  it('nothing closes the dialog while the create is in flight', async () => {
    let finish: (t: TokenCreated) => void = () => undefined;
    createMyToken.mockReturnValue(new Promise<TokenCreated>((resolve) => (finish = resolve)));
    const user = renderDialog();
    const dialog = await openForm(user);
    await user.type(within(dialog).getByRole('textbox', { name: 'Name' }), 'Eval runner');
    await user.click(within(dialog).getByRole('button', { name: 'Create token' }));
    expect(within(dialog).getByRole('button', { name: 'Cancel' })).toBeDisabled();
    await user.keyboard('{Escape}');
    await user.click(within(dialog).getByRole('button', { name: 'Close' }));
    expect(screen.getByRole('dialog', { name: 'New personal token' })).toBeInTheDocument();
    finish(CREATED);
    const reveal = await screen.findByRole('dialog', { name: 'Copy your token' });
    expect(within(reveal).getByText(SECRET)).toBeInTheDocument();
  });

  it("shows the backend's sentence when the create is refused", async () => {
    createMyToken.mockRejectedValue(httpError(403, { detail: 'This needs tokens:create.' }));
    const user = renderDialog();
    const dialog = await openForm(user);
    await user.type(within(dialog).getByRole('textbox', { name: 'Name' }), 'Eval runner');
    await user.click(within(dialog).getByRole('button', { name: 'Create token' }));
    expect(await within(dialog).findByText('This needs tokens:create.')).toBeInTheDocument();
    expect(screen.queryByRole('dialog', { name: 'Copy your token' })).not.toBeInTheDocument();
  });
});
