import { useState } from 'react';
import { Navigate } from 'react-router-dom';
import { motion, useReducedMotion } from 'motion/react';
import { Loader2 } from 'lucide-react';
import { BrandMark, Button, Glass, materialize, springDefault, withReducedMotion } from '@/ui';
import { useAuth } from './auth-context';

/* eslint-disable no-restricted-syntax -- official Google "G" brand colors, not design tokens */
const GoogleMark = () => (
  <svg viewBox="0 0 24 24" className="h-3.5 w-3.5" aria-hidden="true">
    <path
      fill="#4285F4"
      d="M23.5 12.27c0-.85-.08-1.66-.22-2.45H12v4.64h6.45a5.52 5.52 0 0 1-2.39 3.62v3h3.87c2.26-2.09 3.57-5.16 3.57-8.81z"
    />
    <path
      fill="#34A853"
      d="M12 24c3.24 0 5.96-1.07 7.93-2.91l-3.87-3c-1.07.72-2.44 1.14-4.06 1.14-3.12 0-5.77-2.11-6.71-4.95H1.29v3.1A11.99 11.99 0 0 0 12 24z"
    />
    <path
      fill="#FBBC05"
      d="M5.29 14.28a7.2 7.2 0 0 1 0-4.56v-3.1H1.29a12 12 0 0 0 0 10.76l4-3.1z"
    />
    <path
      fill="#EA4335"
      d="M12 4.77c1.76 0 3.34.6 4.58 1.79l3.44-3.44A11.97 11.97 0 0 0 12 0 11.99 11.99 0 0 0 1.29 6.62l4 3.1C6.23 6.88 8.88 4.77 12 4.77z"
    />
  </svg>
);
/* eslint-enable no-restricted-syntax */

/** Firebase error codes → a plain next step (DESIGN.md › sign-in-panel). Null = not an error. */
function signInErrorMessage(error: unknown): string | null {
  const code = error instanceof Error ? error.message : '';
  if (/popup-closed|cancelled-popup|user-cancelled/i.test(code)) return null;
  if (/popup-blocked/i.test(code))
    return 'Your browser blocked the sign-in window. Allow pop-ups and try again.';
  if (/unauthorized-domain/i.test(code)) {
    return "This address isn't approved for Google sign-in. Ask an Atlas admin to add it.";
  }
  return "Sign-in didn't complete. Check your connection and try again.";
}

/** /login: the sign-in panel, one glass surface on the canvas wash. */
export default function LoginPage() {
  const { isAuthenticated, isLoading, signInWithGoogle } = useAuth();
  const reduced = useReducedMotion();
  const [error, setError] = useState<string | null>(null);
  const [signingIn, setSigningIn] = useState(false);

  if (!isLoading && isAuthenticated) return <Navigate to="/" replace />;

  const handleSignIn = async () => {
    setError(null);
    setSigningIn(true);
    try {
      await signInWithGoogle();
    } catch (e) {
      setError(signInErrorMessage(e));
    } finally {
      setSigningIn(false);
    }
  };

  return (
    <main className="flex min-h-screen items-center justify-center px-4 py-10">
      <motion.div
        className="w-full max-w-[380px]"
        initial={materialize.initial}
        animate={materialize.animate}
        transition={withReducedMotion(springDefault, reduced)}
      >
        <Glass specular className="rounded-feature px-8 pb-7 pt-9 text-center">
          <BrandMark size="display" className="justify-center" />
          <h1 className="mt-7 font-serif text-title text-ink">Welcome back</h1>
          <p className="mx-auto mt-2 max-w-[34ch] text-balance text-sm text-body">
            Ask about revenue, orders and funnels. Every number shows where it came from.
          </p>

          <Button
            size="lg"
            className="mt-7 h-11 w-full"
            onClick={() => void handleSignIn()}
            disabled={signingIn || isLoading}
          >
            {signingIn ? (
              <Loader2 className="animate-spin" />
            ) : (
              <span className="grid size-5 place-items-center rounded-full bg-white">
                <GoogleMark />
              </span>
            )}
            Continue with Google
          </Button>

          {error && (
            <p role="alert" className="mt-3 text-label text-negative">
              {error}
            </p>
          )}

          <p className="mt-6 text-balance text-caption text-muted-foreground">
            @yougotagift.com Google accounts only · sessions last 24 hours
          </p>
        </Glass>
      </motion.div>
    </main>
  );
}
