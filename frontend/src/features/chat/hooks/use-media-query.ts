import { useCallback, useSyncExternalStore } from 'react';

const supported = () => typeof window !== 'undefined' && typeof window.matchMedia === 'function';

/** Live `matchMedia` result; `fallback` where matchMedia is unavailable (tests, SSR). */
export function useMediaQuery(query: string, fallback: boolean): boolean {
  const subscribe = useCallback(
    (onChange: () => void) => {
      if (!supported()) return () => {};
      const mql = window.matchMedia(query);
      mql.addEventListener('change', onChange);
      return () => mql.removeEventListener('change', onChange);
    },
    [query],
  );
  const snapshot = () => (supported() ? window.matchMedia(query).matches : fallback);
  return useSyncExternalStore(subscribe, snapshot, () => fallback);
}
