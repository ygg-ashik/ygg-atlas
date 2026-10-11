import { useQuery } from '@tanstack/react-query';
import { queryKeys } from '../query-keys';
import { AUTH_METHODS_DISABLED, fetchAuthMethods, type AuthMethods } from '../tokens';

/** Which credential methods this deployment offers (phase 4). A 404, a
 * failure, or no answer yet all read as "both disabled": the UI never
 * promises a method the server has not confirmed. */
export function useAuthMethods(): { methods: AuthMethods; isLoading: boolean } {
  const query = useQuery({
    queryKey: queryKeys.authMethods,
    queryFn: fetchAuthMethods,
    staleTime: 10 * 60_000,
  });
  return {
    methods: query.isSuccess ? query.data : AUTH_METHODS_DISABLED,
    isLoading: query.isPending,
  };
}
