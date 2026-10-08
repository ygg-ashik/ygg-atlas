import { useState } from 'react';
import { Navigate } from 'react-router-dom';
import { Loader2, Orbit } from 'lucide-react';
import { Button } from '@/ui';
import { useAuth } from './auth-context';

/* eslint-disable no-restricted-syntax -- official Google "G" brand colors, not design tokens */
const GoogleMark = () => (
  <svg viewBox="0 0 24 24" className="h-4 w-4" aria-hidden="true">
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

export default function LoginPage() {
  const { isAuthenticated, isLoading, signInWithGoogle } = useAuth();
  const [error, setError] = useState<string | null>(null);
  const [signingIn, setSigningIn] = useState(false);

  if (!isLoading && isAuthenticated) return <Navigate to="/" replace />;

  const handleSignIn = async () => {
    setError(null);
    setSigningIn(true);
    try {
      await signInWithGoogle();
    } catch (e) {
      const message = e instanceof Error ? e.message : 'Sign-in failed. Please try again.';
      // Popup dismissed by the user is not an error worth surfacing loudly.
      setError(/popup-closed|cancelled/i.test(message) ? null : message);
    } finally {
      setSigningIn(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-background px-4">
      <div className="w-full max-w-sm rounded-xl border bg-card p-8 shadow-sm">
        <div className="mb-8 flex flex-col items-center text-center">
          <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-xl bg-primary text-primary-foreground">
            <Orbit className="h-6 w-6" />
          </div>
          <h1 className="text-xl font-semibold tracking-tight">Atlas</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            YouGotAGift data intelligence. Ask about revenue, orders, funnels — every number carries
            provenance.
          </p>
        </div>

        <Button
          variant="outline"
          className="w-full"
          onClick={() => void handleSignIn()}
          disabled={signingIn || isLoading}
        >
          {signingIn ? <Loader2 className="h-4 w-4 animate-spin" /> : <GoogleMark />}
          Continue with Google
        </Button>

        {error && (
          <p role="alert" className="mt-3 text-center text-xs text-destructive">
            {error}
          </p>
        )}

        <p className="mt-6 text-center text-[11px] text-muted-foreground">
          Restricted to @yougotagift.com accounts. Sessions expire after 24 hours.
        </p>
      </div>
    </div>
  );
}
