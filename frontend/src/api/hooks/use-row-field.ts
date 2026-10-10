import { useQuery } from '@tanstack/react-query';
import { queryKeys } from '../query-keys';
import {
  deleteUserAttribute,
  listLabelClasses,
  listScopeDimensions,
  listUserAttributes,
  putLabelClass,
  putUserAttribute,
  type LabelClassPut,
} from '../row-field';
import { ADMIN_WRITE, useAccessMutation } from './use-access-mutation';

// Row and field controls (phase 3). Every write runs through AccessAdmin's
// write lock, so a 409 is usually the stale-actor case (Retry).

export function useUserAttributes(userId: string | null) {
  return useQuery({
    queryKey: queryKeys.userAttributes(userId ?? ''),
    queryFn: () => listUserAttributes(userId as string),
    enabled: !!userId,
  });
}

export interface AttributeVars {
  userId: string;
  key: string;
  value?: string;
}

export function usePutUserAttribute() {
  return useAccessMutation({
    mutationFn: ({ userId, key, value = '' }: AttributeVars) =>
      putUserAttribute(userId, key, value),
    ...ADMIN_WRITE,
  });
}

export function useDeleteUserAttribute() {
  return useAccessMutation({
    mutationFn: ({ userId, key }: AttributeVars) => deleteUserAttribute(userId, key),
    ...ADMIN_WRITE,
  });
}

export function useLabelClasses(enabled = true) {
  return useQuery({ queryKey: queryKeys.labelClasses, queryFn: listLabelClasses, enabled });
}

export interface LabelClassVars {
  labelClass: string;
  body: LabelClassPut;
}

export function usePutLabelClass() {
  return useAccessMutation({
    mutationFn: ({ labelClass, body }: LabelClassVars) => putLabelClass(labelClass, body),
    ...ADMIN_WRITE,
  });
}

/** Declared row-scope dimensions of the enabled plugins (admin:groups or
 * admin:users). They change only on deploy. */
export function useScopeDimensions(enabled = true) {
  return useQuery({
    queryKey: queryKeys.scopeDimensions,
    queryFn: listScopeDimensions,
    staleTime: 30 * 60_000,
    enabled,
  });
}
