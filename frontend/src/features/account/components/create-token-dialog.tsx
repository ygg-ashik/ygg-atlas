import { useState } from 'react';
import { useCreateMyToken } from '@/api/hooks/use-tokens';
import { type AuthMethods, type TokenCreated } from '@/api/tokens';
import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
  Field,
  FieldError,
  Input,
  Notice,
  SecretReveal,
  SegmentedControl,
} from '@/ui';

type PatMethod = Pick<AuthMethods['pat'], 'default_days' | 'max_days'>;

const PRESETS = [30, 90, 180, 365];
const NAME_MAX = 100;
const DAY_MS = 86_400_000;

/** Lifetimes the form offers: the presets up to `max_days`, plus the default
 * (clamped to the maximum) and the maximum itself. The backend refuses more. */
export function expiryChoices({ default_days, max_days }: PatMethod): number[] {
  const fallback = Math.min(default_days, max_days);
  const days = new Set(PRESETS.filter((d) => d <= max_days));
  days.add(fallback);
  if (max_days < PRESETS[PRESETS.length - 1]!) days.add(max_days);
  return [...days].filter((d) => d > 0).sort((a, b) => a - b);
}

const expiryDate = (days: number) =>
  new Date(Date.now() + days * DAY_MS).toISOString().slice(0, 10);

interface CreateTokenDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  pat: PatMethod;
}

/** New personal token (screen 4): name and lifetime, then the secret exactly
 * once. Closing the reveal resets the mutation, so the secret leaves memory.
 * While the create is in flight nothing closes the dialog (Escape, outside
 * click, ✕, Cancel): a token minted after close would never be shown. */
export function CreateTokenDialog({ open, onOpenChange, pat }: CreateTokenDialogProps) {
  const create = useCreateMyToken();
  const close = (next: boolean) => {
    if (next) return onOpenChange(true);
    if (create.isPending) return;
    create.reset();
    onOpenChange(false);
  };
  const created = create.data;
  return (
    <Dialog open={open} onOpenChange={close}>
      <DialogContent>
        {created ? (
          <Reveal token={created} onDone={() => close(false)} />
        ) : (
          <TokenForm
            pat={pat}
            busy={create.isPending}
            error={create.errorInfo?.message ?? null}
            onCancel={() => close(false)}
            onSubmit={(body) => create.mutate(body)}
          />
        )}
      </DialogContent>
    </Dialog>
  );
}

interface TokenFormProps {
  pat: PatMethod;
  busy: boolean;
  error: string | null;
  onCancel: () => void;
  onSubmit: (body: { name: string; expires_in_days: number }) => void;
}

function TokenForm({ pat, busy, error, onCancel, onSubmit }: TokenFormProps) {
  const choices = expiryChoices(pat);
  const [name, setName] = useState('');
  const [days, setDays] = useState(String(Math.min(pat.default_days, pat.max_days)));
  const [nameError, setNameError] = useState(false);
  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = name.trim();
    if (!trimmed) return setNameError(true);
    onSubmit({ name: trimmed, expires_in_days: Number(days) });
  };
  return (
    <form onSubmit={submit} noValidate className="grid gap-3.5">
      <div>
        <DialogTitle>New personal token</DialogTitle>
        <DialogDescription className="mt-1">
          It acts as you over MCP and the API, with exactly your access. You&apos;ll see it once.
        </DialogDescription>
      </div>
      <Field
        label="Name"
        error={nameError ? "Give it a name you'll recognise when revoking it." : undefined}
      >
        <Input
          value={name}
          maxLength={NAME_MAX}
          placeholder="e.g. Claude Code · laptop"
          onChange={(e) => {
            setName(e.target.value);
            setNameError(false);
          }}
        />
      </Field>
      <div className="grid gap-1.5">
        <span className="text-label font-medium text-ink">Expires</span>
        <SegmentedControl
          kind="radio"
          label="Expires"
          value={days}
          onChange={setDays}
          options={choices.map((d) => ({ value: String(d), label: `${d} days` }))}
          className="justify-self-start"
        />
        <p className="text-xs tabular-nums text-muted-foreground">
          Expires {expiryDate(Number(days))} · tokens can&apos;t outlive your role
        </p>
      </div>
      {error && (
        <div role="alert">
          <FieldError>{error}</FieldError>
        </div>
      )}
      <div className="mt-1.5 flex justify-end gap-2">
        <Button type="button" variant="pill" disabled={busy} onClick={onCancel}>
          Cancel
        </Button>
        <Button type="submit" disabled={busy} aria-busy={busy}>
          Create token
        </Button>
      </div>
    </form>
  );
}

function Reveal({ token, onDone }: { token: TokenCreated; onDone: () => void }) {
  return (
    <div className="grid gap-3.5">
      <div>
        <DialogTitle>Copy your token</DialogTitle>
        <DialogDescription className="mt-1 tabular-nums">
          {token.name} · expires {token.expires_at.slice(0, 10)}
        </DialogDescription>
      </div>
      <SecretReveal label="Personal token" value={token.token}>
        <Notice tone="warning" icon="!">
          <b className="font-medium text-ink">Shown once.</b> Atlas stores only a hash, so this is
          the only time you can copy it. Lost it? Revoke it and create a new one.
        </Notice>
      </SecretReveal>
      <div className="flex justify-end">
        <Button onClick={onDone}>Done</Button>
      </div>
    </div>
  );
}
