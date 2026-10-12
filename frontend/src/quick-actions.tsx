// src/quick-actions.tsx
// App-level composition of the ⌘K quick actions (DESIGN.md › Quick actions):
// tasks that run in place over the current page and reuse the account and admin
// features' own dialogs. Which actions exist comes from `/me/access` through the
// same rules as the routes; the API still refuses anything the token can't do.
import { useCallback, useEffect, useMemo, useState } from 'react';
import { useLocation } from 'react-router-dom';
import { ArrowLeftRight, Inbox, KeyRound, KeySquare, ShieldCheck } from 'lucide-react';
import { type AccessRequest } from '@/api/access-requests';
import { useRequestQueue } from '@/api/hooks/use-access-requests';
import { useAuthMethods } from '@/api/hooks/use-auth-methods';
import { type MyAccessView } from '@/api/hooks/use-my-access';
import { useAdminTokens } from '@/api/hooks/use-tokens';
import { type Token } from '@/api/tokens';
import { useTheme } from '@/lib/theme-provider';
import { type OpenRequestAccess } from '@/lib/request-access';
import { type RequestPrefill } from '@/lib/routes';
import { THEME_CHOICES, toast } from '@/ui';
import { AccessPeek, CreateTokenDialog, RequestAccessDialog } from '@/features/account';
import { ApproveRequestDialog, RevokeTokenDialog } from '@/features/admin';
import { allows } from '@/features/auth';
import { CommandPalette, type PaletteLink, type QuickAction } from '@/features/command';
import { ACCESS } from './navigation';

/** The quick dialog on screen, with what it acts on. */
type Open =
  | { kind: 'token' }
  | { kind: 'request'; prefill: RequestPrefill }
  | { kind: 'access' }
  | { kind: 'approve'; request: AccessRequest }
  | { kind: 'revoke'; token: Token };

/** Each list offers its first entry up front; the rest appear once you type. */
const firstOnly = (i: number) => i > 0;

function themeActions(current: string, setTheme: (t: 'light' | 'dark' | 'system') => void) {
  return THEME_CHOICES.filter((t) => t.value !== current).map((t, i): QuickAction => ({
    id: `theme:${t.value}`,
    label: `Theme: ${t.label}`,
    icon: t.icon,
    keywords: ['theme', 'appearance', 'mode'],
    onlyWhenSearching: firstOnly(i),
    run: () => {
      setTheme(t.value);
      toast(`Theme: ${t.label}`);
    },
  }));
}

/** Someone else's pending requests only: nobody decides their own. */
function approveActions(
  view: MyAccessView,
  requests: readonly AccessRequest[],
  set: (o: Open) => void,
) {
  const me = view.access?.user_id;
  const tag = view.capabilities.some((c) => c.startsWith('admin:')) ? 'admin' : 'manager';
  return requests
    .filter((r) => r.status === 'pending' && r.requester && r.requester.user_id !== me)
    .map((r, i): QuickAction => ({
      id: `approve:${r.id}`,
      label: `Approve request · ${r.requester?.display_name || r.requester?.email} · ${r.target_label || r.target}`,
      icon: Inbox,
      keywords: ['approve', 'request', r.kind, r.target],
      onlyWhenSearching: firstOnly(i),
      tag,
      run: () => set({ kind: 'approve', request: r }),
    }));
}

function revokeActions(tokens: readonly Token[], set: (o: Open) => void) {
  return tokens
    .filter((t) => !t.revoked_at)
    .map((t, i): QuickAction => ({
      id: `revoke:${t.id}`,
      label: `Revoke token ${t.prefix}… · ${t.name}`,
      icon: KeySquare,
      keywords: ['revoke', 'token', t.user_id, t.kind],
      onlyWhenSearching: firstOnly(i),
      tag: 'admin',
      run: () => set({ kind: 'revoke', token: t }),
    }));
}

/** The viewer's own tasks: a token (with tokens:create), a request, the access peek. */
function selfActions(set: (o: Open) => void, canCreateToken: boolean): QuickAction[] {
  const token: QuickAction = {
    id: 'token',
    label: 'New token',
    icon: KeyRound,
    keywords: ['personal access token', 'pat', 'mcp', 'claude code'],
    run: () => set({ kind: 'token' }),
  };
  return [
    ...(canCreateToken ? [token] : []),
    {
      id: 'request',
      label: 'Request access',
      icon: ArrowLeftRight,
      keywords: ['group', 'role', 'resource', 'permission'],
      run: () => set({ kind: 'request', prefill: {} }),
    },
    {
      id: 'access',
      label: 'My access',
      icon: ShieldCheck,
      keywords: ['permissions', 'groups', 'role', 'what can i see'],
      run: () => set({ kind: 'access' }),
    },
  ];
}

/** The open dialog when it is of `kind`, else null. */
function only<K extends Open['kind']>(open: Open | null, kind: K) {
  return open?.kind === kind ? (open as Extract<Open, { kind: K }>) : null;
}

/** Which quick dialog is open. It lives in AppShell so the chat (denials, first
 * run) can open the request dialog through `lib/request-access`. */
export function useQuickDialogs() {
  const [open, setOpen] = useState<Open | null>(null);
  const close = useCallback(() => setOpen(null), []);
  // Following a link out of a dialog (Open full page, Track it) closes it.
  const { key } = useLocation();
  useEffect(close, [key, close]);
  const requestAccess = useCallback<OpenRequestAccess>(
    (prefill = {}) => setOpen({ kind: 'request', prefill }),
    [],
  );
  return { open, setOpen, close, requestAccess };
}

interface ViewerProps {
  view: MyAccessView;
}

/** ⌘K with the viewer's quick actions. It owns its open state, so opening it
 * re-renders only the palette; approvals and tokens load only while it is open. */
export function QuickPalette({
  view,
  pages,
  onRun,
}: ViewerProps & { pages: readonly PaletteLink[]; onRun: (dialog: Open) => void }) {
  const [paletteOpen, setPaletteOpen] = useState(false);
  const { theme, setTheme } = useTheme();
  const { methods } = useAuthMethods();
  const ready = view.status === 'ready';
  const canApprove = allows(view, ACCESS.requests);
  const canRevoke = allows(view, ACCESS.tokens);
  const canCreateToken = view.can('tokens:create') && methods.pat.enabled;
  const queue = useRequestQueue('pending', { enabled: paletteOpen && canApprove });
  const tokens = useAdminTokens({}, paletteOpen && canRevoke);
  const actions = useMemo(
    () => [
      ...themeActions(theme, setTheme),
      ...(ready ? selfActions(onRun, canCreateToken) : []),
      ...(canApprove ? approveActions(view, queue.items, onRun) : []),
      ...(canRevoke ? revokeActions(tokens.data ?? [], onRun) : []),
    ],
    [
      theme,
      setTheme,
      ready,
      onRun,
      canCreateToken,
      canApprove,
      view,
      queue.items,
      canRevoke,
      tokens.data,
    ],
  );
  return <CommandPalette pages={pages} actions={actions} onOpenChange={setPaletteOpen} />;
}

/** The dialogs quick actions open, each reused from its feature. Approve and
 * revoke render only for the capabilities that offered them. */
export function QuickDialogs({
  view,
  open,
  close,
}: ViewerProps & { open: Open | null; close: () => void }) {
  const { methods } = useAuthMethods();
  const canCreateToken = view.can('tokens:create') && methods.pat.enabled;
  const onOpenChange = (next: boolean) => {
    if (!next) close();
  };
  const request = only(open, 'request');
  const approve = allows(view, ACCESS.requests) ? only(open, 'approve') : null;
  const revoke = allows(view, ACCESS.tokens) ? only(open, 'revoke') : null;
  return (
    <>
      <RequestAccessDialog
        open={request !== null}
        onOpenChange={onOpenChange}
        prefill={request?.prefill}
      />
      {canCreateToken && (
        <CreateTokenDialog
          open={open?.kind === 'token'}
          onOpenChange={onOpenChange}
          pat={methods.pat}
        />
      )}
      <AccessPeek open={open?.kind === 'access'} onOpenChange={onOpenChange} />
      <ApproveRequestDialog target={approve?.request ?? null} onClose={close} />
      <RevokeTokenDialog target={revoke?.token ?? null} onClose={close} />
    </>
  );
}
