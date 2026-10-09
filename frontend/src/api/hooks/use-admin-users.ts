import { keepPreviousData, useQuery } from '@tanstack/react-query';
import {
  fetchEffectiveAccess,
  fetchUserDetail,
  listUsers,
  updateUser,
  type UserFilters,
  type UserUpdate,
} from '../admin-users';
import { queryKeys } from '../query-keys';
import { ADMIN_WRITE, useAccessMutation } from './use-access-mutation';
import { type CursorListOptions, useCursorList } from './use-cursor-list';

export const USER_PAGE_SIZE = 50;

/** `GET /admin/users`, keyset-paged by email; "Load more" calls `fetchNextPage`. */
export function useAdminUsers(filters: UserFilters = {}, options: CursorListOptions = {}) {
  return useCursorList(
    queryKeys.userList(filters),
    (cursor) => listUsers({ filters, cursor, limit: USER_PAGE_SIZE }),
    options,
  );
}

export function useUserDetail(userId: string | null) {
  return useQuery({
    queryKey: queryKeys.userDetail(userId ?? ''),
    queryFn: () => fetchUserDetail(userId as string),
    enabled: !!userId,
  });
}

/** The target's effective access, and its decision for `resource` when given. */
export function useEffectiveAccess(userId: string | null, resource: string | null = null) {
  return useQuery({
    queryKey: queryKeys.userAccess(userId ?? '', resource),
    queryFn: () => fetchEffectiveAccess(userId as string, resource ?? undefined),
    enabled: !!userId,
    placeholderData: keepPreviousData,
  });
}

export interface UpdateUserVars {
  userId: string;
  update: UserUpdate;
}

export function useUpdateUser() {
  return useAccessMutation({
    mutationFn: ({ userId, update }: UpdateUserVars) => updateUser(userId, update),
    ...ADMIN_WRITE,
  });
}
