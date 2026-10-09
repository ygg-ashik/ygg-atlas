import { useQuery } from '@tanstack/react-query';
import {
  createGrant,
  listGrants,
  revokeGrant,
  type GrantCreate,
  type SubjectType,
} from '../admin-groups';
import { queryKeys } from '../query-keys';
import { ADMIN_WRITE, useAccessMutation } from './use-access-mutation';

export interface GrantSubject {
  subjectType: SubjectType;
  subjectId: string;
}

/** Direct grants of one group or user. */
export function useGrants(subject: GrantSubject | null) {
  return useQuery({
    queryKey: queryKeys.grantList(subject?.subjectType ?? 'group', subject?.subjectId ?? ''),
    queryFn: () => {
      const { subjectType, subjectId } = subject as GrantSubject;
      return listGrants(subjectType, subjectId);
    },
    enabled: !!subject,
  });
}

export function useCreateGrant() {
  return useAccessMutation({
    mutationFn: (body: GrantCreate) => createGrant(body),
    ...ADMIN_WRITE,
  });
}

export function useRevokeGrant() {
  return useAccessMutation({
    mutationFn: (grantId: string) => revokeGrant(grantId),
    ...ADMIN_WRITE,
  });
}
