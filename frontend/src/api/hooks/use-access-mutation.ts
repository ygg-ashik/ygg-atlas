import { useMutation, useQueryClient, type QueryKey } from '@tanstack/react-query';
import { describeMutationError, handleMutationError } from '../mutation-errors';
import { queryKeys } from '../query-keys';

/** Every view an access-model write can change: all admin views and the
 * caller's own access (counts, groups, capabilities). */
export const ACCESS_VIEWS: readonly QueryKey[] = [queryKeys.admin, queryKeys.myAccess];

export interface AccessMutationOptions<TData, TVars> {
  mutationFn: (vars: TVars) => Promise<TData>;
  /** Query families to refetch after success. */
  invalidates: readonly QueryKey[];
  /** 0 for responses that carry a secret, so it never lingers in the cache. */
  gcTime?: number;
  /** Offer Retry on a 409: set only for writes through AccessAdmin's write lock,
   * whose 409 is the stale-actor "access changed" case (see MutationErrorOptions). */
  retryOn409?: boolean;
}

/** Writes through AccessAdmin (`_write`): a 409 there is usually the stale-actor check. */
export const ADMIN_WRITE = { invalidates: ACCESS_VIEWS, retryOn409: true } as const;

/** A write with the shared error policy: any 409 ⇒ `['me','access']` is
 * refetched, and with `retryOn409` `errorInfo.retry` is set (action toast with
 * Retry); 403 and the rest ⇒ the backend's sentence in `errorInfo.message`. */
export function useAccessMutation<TData, TVars>({
  mutationFn,
  invalidates,
  gcTime,
  retryOn409 = false,
}: AccessMutationOptions<TData, TVars>) {
  const qc = useQueryClient();
  const mutation = useMutation({
    mutationFn,
    gcTime,
    onSuccess: () => Promise.all(invalidates.map((queryKey) => qc.invalidateQueries({ queryKey }))),
    onError: (error) => {
      handleMutationError(qc, error, { retryOn409 });
    },
  });
  const errorInfo = mutation.error ? describeMutationError(mutation.error, { retryOn409 }) : null;
  return { ...mutation, errorInfo };
}
