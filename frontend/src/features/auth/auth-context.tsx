import { createContext, useCallback, useContext, useEffect, useState } from 'react';
import {
  onAuthStateChanged,
  signInWithPopup,
  signOut as firebaseSignOut,
  type User as FirebaseUser,
} from 'firebase/auth';
import { auth, googleProvider } from '@/lib/firebase';

const ALLOWED_DOMAIN = 'yougotagift.com';
const SESSION_MAX_AGE_MS = 24 * 60 * 60 * 1000; // force daily login

/** Dev-only bypass, mirrors the backend's AUTH_DISABLED. Never set in production. */
export const AUTH_DISABLED = import.meta.env.VITE_AUTH_DISABLED === 'true';

export interface AtlasUser {
  uid: string;
  email: string;
  name: string;
  avatar: string;
}

interface AuthContextType {
  user: AtlasUser | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  signInWithGoogle: () => Promise<void>;
  signOut: () => Promise<void>;
}

const AuthContext = createContext<AuthContextType | null>(null);

function isAllowedDomain(email: string): boolean {
  return email.split('@')[1] === ALLOWED_DOMAIN;
}

function isSessionExpired(firebaseUser: FirebaseUser): boolean {
  const lastSignInTime = firebaseUser.metadata?.lastSignInTime;
  if (!lastSignInTime) return false;
  return Date.now() - new Date(lastSignInTime).getTime() > SESSION_MAX_AGE_MS;
}

function toAtlasUser(firebaseUser: FirebaseUser): AtlasUser {
  return {
    uid: firebaseUser.uid,
    email: firebaseUser.email ?? '',
    name: firebaseUser.displayName ?? 'User',
    avatar: firebaseUser.photoURL ?? '',
  };
}

const DEV_USER: AtlasUser = {
  uid: 'dev-user',
  email: `dev@${ALLOWED_DOMAIN}`,
  name: 'Dev User',
  avatar: '',
};

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<AtlasUser | null>(AUTH_DISABLED ? DEV_USER : null);
  const [isLoading, setIsLoading] = useState(!AUTH_DISABLED);

  useEffect(() => {
    if (AUTH_DISABLED) return;
    const unsubscribe = onAuthStateChanged(auth, async (firebaseUser) => {
      if (!firebaseUser) {
        setUser(null);
        setIsLoading(false);
        return;
      }
      // Domain lock + 24h expiry apply to persisted sessions too.
      if (!isAllowedDomain(firebaseUser.email ?? '') || isSessionExpired(firebaseUser)) {
        await firebaseSignOut(auth);
        setUser(null);
        setIsLoading(false);
        return;
      }
      setUser(toAtlasUser(firebaseUser));
      setIsLoading(false);
    });

    // Enforce the 24h limit while the app stays open.
    const checkInterval = setInterval(() => {
      const current = auth.currentUser;
      if (current && isSessionExpired(current)) {
        void firebaseSignOut(auth);
        setUser(null);
      }
    }, 60_000);

    return () => {
      unsubscribe();
      clearInterval(checkInterval);
    };
  }, []);

  const signInWithGoogle = useCallback(async () => {
    if (AUTH_DISABLED) return;
    const credential = await signInWithPopup(auth, googleProvider);
    const email = credential.user.email ?? '';
    if (!isAllowedDomain(email)) {
      await firebaseSignOut(auth);
      throw new Error(`Access is limited to @${ALLOWED_DOMAIN} accounts.`);
    }
    setUser(toAtlasUser(credential.user));
  }, []);

  const signOut = useCallback(async () => {
    if (AUTH_DISABLED) return;
    await firebaseSignOut(auth);
    setUser(null);
  }, []);

  return (
    <AuthContext.Provider
      value={{ user, isAuthenticated: !!user, isLoading, signInWithGoogle, signOut }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextType {
  const context = useContext(AuthContext);
  if (!context) throw new Error('useAuth must be used within an AuthProvider');
  return context;
}
