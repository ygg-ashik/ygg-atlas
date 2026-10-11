import { useQuery } from '@tanstack/react-query';
import { useMemo } from 'react';
import { fetchMyAccess, type MeAccess } from '../access';
import { queryKeys } from '../query-keys';

/** `unavailable`: the last fetch failed (403, 5xx, network); treated as no access. */
export type MyAccessStatus = 'loading' | 'ready' | 'unavailable';

/** The caller's access as the UI may use it. It fails closed: until a
 * successful answer, and whenever the last fetch failed, there are no
 * capabilities and every check is false. The UI never decides access; this
 * only chooses what to show, and the API refuses the rest. */
export interface MyAccessView {
  status: MyAccessStatus;
  access: MeAccess | null;
  capabilities: readonly string[];
  isManager: boolean;
  pendingRequests: number;
  pendingApprovals: number;
  can: (capability: string) => boolean;
  canAny: (...capabilities: string[]) => boolean;
  refetch: () => void;
}

const NONE: readonly string[] = [];

function statusOf(access: MeAccess | null, isError: boolean): MyAccessStatus {
  if (access) return 'ready';
  return isError ? 'unavailable' : 'loading';
}

export function useMyAccess(): MyAccessView {
  const query = useQuery({
    queryKey: queryKeys.myAccess,
    queryFn: fetchMyAccess,
    staleTime: 30_000,
  });
  const { data, isError, isPending, refetch } = query;
  return useMemo(() => {
    // A failed refetch keeps stale `data` in TanStack Query; ignore it (fail closed).
    const access = isError || isPending ? null : (data ?? null);
    const status = statusOf(access, isError);
    const capabilities = access?.capabilities ?? NONE;
    const held = new Set(capabilities);
    return {
      status,
      access,
      capabilities,
      isManager: access?.is_manager ?? false,
      pendingRequests: access?.pending_requests ?? 0,
      pendingApprovals: access?.pending_approvals ?? 0,
      can: (capability) => held.has(capability),
      canAny: (...wanted) => wanted.some((c) => held.has(c)),
      refetch: () => void refetch(),
    };
  }, [data, isError, isPending, refetch]);
}
