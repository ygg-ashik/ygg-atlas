// Firebase app — Auth ONLY. ygg-atlas uses no Firestore/Storage; all data
// flows through the backend API with the Firebase ID token as the credential.
import { initializeApp } from 'firebase/app';
import { getAuth, GoogleAuthProvider } from 'firebase/auth';

// With VITE_AUTH_DISABLED (dev bypass) Firebase is never actually used, but the
// SDK still initializes at import time — placeholders keep that from throwing.
const devBypass = import.meta.env.VITE_AUTH_DISABLED === 'true';

const firebaseConfig = {
  apiKey: import.meta.env.VITE_FIREBASE_API_KEY ?? (devBypass ? 'dev-placeholder' : undefined),
  authDomain: import.meta.env.VITE_FIREBASE_AUTH_DOMAIN,
  projectId: import.meta.env.VITE_FIREBASE_PROJECT_ID ?? (devBypass ? 'dev' : undefined),
  appId: import.meta.env.VITE_FIREBASE_APP_ID ?? (devBypass ? 'dev' : undefined),
};

const app = initializeApp(firebaseConfig);

export const auth = getAuth(app);

/** Google provider pre-scoped to the company workspace. The `hd` hint filters
 * the account picker; the hard domain check lives in the auth feature. */
export const googleProvider = new GoogleAuthProvider();
googleProvider.setCustomParameters({ hd: 'yougotagift.com', prompt: 'select_account' });

export default app;
