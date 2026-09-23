import axios from 'axios';
import { auth } from '@/lib/firebase';

/** Backend origin. Empty string means same-origin: the Vite dev proxy or the
 * nginx container forwards /api to the backend. */
export const backendUrl = import.meta.env.VITE_BACKEND_URL
  ? import.meta.env.VITE_BACKEND_URL.replace(/\/+$/, '')
  : '';

/** Standard axios instance for the ygg-atlas backend (REST, non-streaming). */
export const api = axios.create({
  baseURL: `${backendUrl}/api/v1`,
  headers: {
    'Content-Type': 'application/json',
  },
});

// Attach the Firebase ID token on every request. Scope is derived from this
// token server-side — never from anything the user typed.
api.interceptors.request.use(async (config) => {
  if (import.meta.env.VITE_AUTH_DISABLED === 'true') return config;
  const user = auth.currentUser;
  if (user) {
    try {
      const token = await user.getIdToken();
      config.headers.Authorization = `Bearer ${token}`;
    } catch (error) {
      console.error('Error fetching Firebase ID token:', error);
    }
  }
  return config;
});
