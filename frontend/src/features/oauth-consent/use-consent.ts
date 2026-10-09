import { useCallback, useEffect, useRef, useState } from 'react';
import {
  ConsentApiError,
  getConsentPrompt,
  submitConsent,
  type ConsentDecision,
  type ConsentPrompt,
} from './consent-api';
import type { ConsentSession } from './consent-page';

export type ConsentState =
  | { kind: 'missing-txn' }
  | { kind: 'sign-in' }
  | { kind: 'loading' }
  | { kind: 'expired' }
  | { kind: 'blocked'; message: string } // 403 refusal code → our own copy, never the body
  | { kind: 'ineligible'; prompt: ConsentPrompt }
  | { kind: 'ready'; prompt: ConsentPrompt }
  | { kind: 'done'; decision: ConsentDecision }
  | { kind: 'error'; message: string };

const GENERIC_ERROR = 'Something went wrong on our side. Start again from your MCP client.';
const RATE_LIMITED = 'Too many attempts. Wait a minute, then start again from your MCP client.';
const BAD_REDIRECT =
  "Atlas couldn't confirm where to send this approval, so it stopped. Start again from your MCP client.";

const BLOCKED_FALLBACK = "This account can't approve MCP access. Contact an Atlas admin.";

/** Maps a 403's refusal code to fixed copy. Unknown or missing codes get the fallback. */
function blockedMessage(reason: string | null): string {
  switch (reason) {
    case 'user_disabled':
      return 'Your Atlas access is disabled. Contact an Atlas admin.';
    case 'not_company_account':
      return 'Atlas only accepts @yougotagift.com Google accounts.';
    case 'service_account':
      return 'Service accounts use tokens, not sign-in. Sign in with your own Google account.';
    default:
      return BLOCKED_FALLBACK;
  }
}

function stateFromError(error: unknown, prompt: ConsentPrompt | null): ConsentState {
  const e = error instanceof ConsentApiError ? error : new ConsentApiError(null, null);
  if (e.status === 401) return { kind: 'sign-in' };
  if (e.status === 404) return { kind: 'expired' };
  if (e.status === 403 && e.reason === 'no_mcp_use' && prompt)
    return { kind: 'ineligible', prompt };
  if (e.status === 403) return { kind: 'blocked', message: blockedMessage(e.reason) };
  if (e.status === 429) return { kind: 'error', message: RATE_LIMITED };
  return { kind: 'error', message: GENERIC_ERROR };
}

/** Defence in depth: only follow a redirect to the client's registered redirect URI. */
function isRegisteredRedirect(redirectTo: string, registered: string): boolean {
  try {
    const target = new URL(redirectTo);
    const expected = new URL(registered);
    return (
      (target.protocol === 'http:' || target.protocol === 'https:') &&
      target.origin === expected.origin &&
      target.pathname === expected.pathname
    );
  } catch {
    return false;
  }
}

interface Fetched {
  key: string;
  state: ConsentState;
}

/** Drives /oauth/consent: session → prompt → decision → redirect back to the MCP client. */
export function useConsent(
  txn: string | null,
  session: ConsentSession,
): {
  state: ConsentState;
  decide: (d: ConsentDecision) => Promise<void>;
  submitting: boolean;
  /** Sign in (again), then re-check the request: a 401 can come with a stale local session. */
  signIn: () => Promise<void>;
} {
  const { email, isLoading, signIn: sessionSignIn } = session;
  const [attempt, setAttempt] = useState(0);
  const key = `${txn ?? ''}\n${email ?? ''}\n${attempt}`;
  const [fetched, setFetched] = useState<Fetched | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const inFlight = useRef(false);

  useEffect(() => {
    if (!txn || isLoading || !email) return;
    let cancelled = false;
    getConsentPrompt(txn).then(
      (prompt) => {
        if (cancelled) return;
        setFetched({ key, state: { kind: prompt.eligible ? 'ready' : 'ineligible', prompt } });
      },
      (error: unknown) => {
        if (!cancelled) setFetched({ key, state: stateFromError(error, null) });
      },
    );
    return () => {
      cancelled = true;
    };
  }, [txn, email, isLoading, key]);

  let state: ConsentState;
  if (!txn) state = { kind: 'missing-txn' };
  else if (isLoading) state = { kind: 'loading' };
  else if (!email) state = { kind: 'sign-in' };
  else state = fetched?.key === key ? fetched.state : { kind: 'loading' };

  const ready = state.kind === 'ready' ? state.prompt : null;

  const decide = useCallback(
    async (decision: ConsentDecision) => {
      if (!txn || !ready || inFlight.current) return;
      inFlight.current = true;
      setSubmitting(true);
      try {
        const { redirect_to } = await submitConsent(txn, decision);
        if (!isRegisteredRedirect(redirect_to, ready.redirect_uri)) {
          setFetched({ key, state: { kind: 'error', message: BAD_REDIRECT } });
          return;
        }
        setFetched({ key, state: { kind: 'done', decision } });
        window.location.assign(redirect_to);
      } catch (error) {
        setFetched({ key, state: stateFromError(error, ready) });
      } finally {
        inFlight.current = false;
        setSubmitting(false);
      }
    },
    [txn, ready, key],
  );

  const signIn = useCallback(async () => {
    await sessionSignIn();
    setAttempt((n) => n + 1);
  }, [sessionSignIn]);

  return { state, decide, submitting, signIn };
}
