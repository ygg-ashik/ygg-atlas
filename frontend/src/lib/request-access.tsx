// src/lib/request-access.tsx
// Lets any feature open the request-access dialog without importing the
// account feature: App.tsx provides the opener, features call it. Without a
// provider (tests, the consent page) callers fall back to the request page link.
import { createContext, useContext } from 'react';
import { type RequestPrefill } from './routes';

/** Opens the request-access dialog, prefilled. */
export type OpenRequestAccess = (prefill?: RequestPrefill) => void;

const RequestAccessContext = createContext<OpenRequestAccess | null>(null);

export const RequestAccessProvider = RequestAccessContext.Provider;

/** The opener App.tsx provides, or null where no dialog host is mounted. */
export function useRequestAccess(): OpenRequestAccess | null {
  return useContext(RequestAccessContext);
}
