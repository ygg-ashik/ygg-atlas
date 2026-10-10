import { useState, type ReactNode } from 'react';
import { useSearchParams } from 'react-router-dom';
import { motion, useReducedMotion } from 'motion/react';
import { Loader2, TriangleAlert } from 'lucide-react';
import { BrandMark, Button, Glass, materialize, springDefault, withReducedMotion } from '@/ui';
import type { ConsentPrompt } from './consent-api';
import { useConsent, type ConsentState } from './use-consent';

/** What the page needs from the auth feature; App.tsx composes it in (features stay decoupled). */
export interface ConsentSession {
  email: string | null; // null = not signed in
  isLoading: boolean;
  signIn: () => Promise<void>;
}

const START_AGAIN = 'Start again from your MCP client.';
const REQUEST_ACCESS_HREF = '/account/requests/new?kind=role';

/** One centered glass panel on the canvas wash (DESIGN.md › consent-panel). */
function ConsentPanel({ children }: { children: ReactNode }) {
  const reduced = useReducedMotion();
  return (
    <main className="flex min-h-screen items-center justify-center px-4 py-10">
      {/* React 19 hoists this into <head>: the txn in the URL never leaves as a Referer. */}
      <meta name="referrer" content="no-referrer" />
      <motion.div
        className="w-full max-w-[420px]"
        initial={materialize.initial}
        animate={materialize.animate}
        transition={withReducedMotion(springDefault, reduced)}
      >
        <Glass specular className="rounded-feature px-8 pb-7 pt-9 text-center">
          <BrandMark size="display" className="justify-center" />
          {children}
        </Glass>
      </motion.div>
    </main>
  );
}

function Notice({ title, children }: { title: string; children: ReactNode }) {
  return (
    <>
      <h1 className="mt-7 text-balance font-serif text-title text-ink">{title}</h1>
      <div className="mx-auto mt-2 max-w-[36ch] text-balance text-sm text-body">{children}</div>
    </>
  );
}

function signInErrorMessage(error: unknown): string | null {
  const text = error instanceof Error ? error.message : '';
  if (/popup-closed|cancelled-popup|user-cancelled/i.test(text)) return null;
  if (/popup-blocked/i.test(text)) {
    return 'Your browser blocked the sign-in window. Allow pop-ups and try again.';
  }
  if (/limited to @/i.test(text)) return 'Use your @yougotagift.com Google account and try again.';
  return "Sign-in didn't complete. Check your connection and try again.";
}

function SignInView({ signIn, isLoading }: { signIn: () => Promise<void>; isLoading: boolean }) {
  const [error, setError] = useState<string | null>(null);
  const [signingIn, setSigningIn] = useState(false);
  const handle = async () => {
    setError(null);
    setSigningIn(true);
    try {
      await signIn();
    } catch (e) {
      setError(signInErrorMessage(e));
    } finally {
      setSigningIn(false);
    }
  };
  return (
    <>
      <Notice title="Sign in to continue">
        An app is asking to connect to Atlas. Sign in to review the request.
      </Notice>
      <Button
        size="lg"
        className="mt-7 h-11 w-full"
        onClick={() => void handle()}
        disabled={signingIn || isLoading}
      >
        {signingIn && <Loader2 className="animate-spin" aria-hidden="true" />}
        Continue with Google
      </Button>
      {error && (
        <p role="alert" className="mt-3 text-label text-negative">
          {error}
        </p>
      )}
      <p className="mt-6 text-balance text-caption text-muted-foreground">
        @yougotagift.com Google accounts only
      </p>
    </>
  );
}

function RedirectNotice({ prompt }: { prompt: ConsentPrompt }) {
  if (!prompt.loopback) {
    return (
      <p className="mt-5 text-label text-body">
        Atlas will send the approval to{' '}
        <span className="font-mono text-ink">{prompt.redirect_host}</span>.
      </p>
    );
  }
  return (
    <>
      <p className="mt-5 text-label text-body">
        Approval goes to <span className="font-mono text-ink">{prompt.redirect_host}</span>
      </p>
      <div
        role="note"
        className="mt-3 flex gap-2 rounded-md border border-warning/40 bg-warning/10 px-3 py-2.5 text-left text-label text-ink"
      >
        <TriangleAlert className="mt-0.5 size-4 shrink-0 text-warning" aria-hidden="true" />
        <span>
          This app runs on your computer. Approve only if you just started this from Claude Code or
          another app on this machine.
        </span>
      </div>
    </>
  );
}

interface ReadyViewProps {
  prompt: ConsentPrompt;
  submitting: boolean;
  decide: (d: 'approve' | 'deny') => Promise<void>;
}

function ReadyView({ prompt, submitting, decide }: ReadyViewProps) {
  return (
    <>
      <h1 className="mt-7 text-balance font-serif text-title text-ink">
        <strong className="font-semibold">{prompt.client_name}</strong> wants to access Atlas
      </h1>
      <p className="mt-2 text-sm text-body">
        as <span className="font-medium text-ink">{prompt.user_email}</span>
      </p>
      <RedirectNotice prompt={prompt} />
      <div className="mt-5 text-left text-label text-body">
        <p className="font-medium text-ink">If you approve, this app can:</p>
        <ul className="mt-1.5 list-disc space-y-1 pl-5">
          <li>query the data you&apos;re permitted to see in Atlas,</li>
          <li>under your current role and groups, never more than you can see.</li>
        </ul>
        <p className="mt-1.5">You can disconnect it at any time.</p>
      </div>
      <div className="mt-7 flex gap-3">
        <Button
          variant="secondary"
          size="lg"
          className="h-11 flex-1"
          disabled={submitting}
          onClick={() => void decide('deny')}
        >
          Deny
        </Button>
        <Button
          size="lg"
          className="h-11 flex-1"
          disabled={submitting}
          aria-busy={submitting}
          onClick={() => void decide('approve')}
        >
          Approve
        </Button>
      </div>
    </>
  );
}

function IneligibleView() {
  return (
    <Notice title="MCP access needed">
      <p>Your role doesn&apos;t include MCP access yet.</p>
      <p className="mt-4">
        <a href={REQUEST_ACCESS_HREF} className="text-primary-text underline underline-offset-4">
          Request access
        </a>
      </p>
    </Notice>
  );
}

type Decide = ReadyViewProps['decide'];

function StateView(props: { state: ConsentState; submitting: boolean; decide: Decide }) {
  const { state } = props;
  switch (state.kind) {
    case 'missing-txn':
      return (
        <Notice title="Link incomplete">This sign-in link is incomplete. {START_AGAIN}</Notice>
      );
    case 'loading':
      return (
        <p role="status" className="mt-7 text-label text-muted-foreground">
          Checking the request…
        </p>
      );
    case 'expired':
      return (
        <Notice title="Request expired">
          This request expired or was already used. {START_AGAIN}
        </Notice>
      );
    case 'blocked':
      return <Notice title="Can't continue">{state.message}</Notice>;
    case 'ineligible':
      return <IneligibleView />;
    case 'ready':
      return (
        <ReadyView prompt={state.prompt} submitting={props.submitting} decide={props.decide} />
      );
    case 'done':
      return (
        <Notice title={state.decision === 'approve' ? 'Approved' : 'Denied'}>
          <span role="status">
            {state.decision === 'approve'
              ? 'Authentication successful. Return to Claude Code.'
              : 'Request denied. You can close this tab.'}
          </span>
        </Notice>
      );
    case 'error':
      return (
        <Notice title="Can't continue">
          <span role="alert">{state.message}</span>
        </Notice>
      );
    case 'sign-in':
      return null;
  }
}

/** /oauth/consent: approve or deny an MCP client's request to act as the signed-in user. */
export function ConsentPage({ session }: { session: ConsentSession }) {
  const [params] = useSearchParams();
  const { state, decide, submitting, signIn } = useConsent(params.get('txn'), session);
  return (
    <ConsentPanel>
      {state.kind === 'sign-in' ? (
        <SignInView signIn={signIn} isLoading={session.isLoading} />
      ) : (
        <StateView state={state} submitting={submitting} decide={decide} />
      )}
    </ConsentPanel>
  );
}
