import { useQuery } from '@tanstack/react-query';
import { type GroupStanding } from '../access';
import {
  CANDIDATE_QUERY_MAX,
  CANDIDATE_QUERY_MIN,
  createGroup,
  deleteGroup,
  fetchGroupDetail,
  listGroups,
  listMemberCandidates,
  listMembers,
  putMember,
  removeMember,
  updateGroup,
  type GroupCreate,
  type GroupUpdate,
} from '../admin-groups';
import { queryKeys } from '../query-keys';
import { ADMIN_WRITE, useAccessMutation } from './use-access-mutation';

export function useGroups({ enabled = true }: { enabled?: boolean } = {}) {
  return useQuery({ queryKey: queryKeys.groupList, queryFn: listGroups, enabled });
}

export function useGroupDetail(groupId: string | null) {
  return useQuery({
    queryKey: queryKeys.groupDetail(groupId ?? ''),
    queryFn: () => fetchGroupDetail(groupId as string),
    enabled: !!groupId,
  });
}

export function useGroupMembers(groupId: string | null) {
  return useQuery({
    queryKey: queryKeys.groupMembers(groupId ?? ''),
    queryFn: () => listMembers(groupId as string),
    enabled: !!groupId,
  });
}

/** Colleagues who could join `groupId`, for a search of 3..100 characters
 * (idle otherwise). A 403 is not retried: the viewer may not add members. */
export function useMemberCandidates(groupId: string, q: string, enabled = true) {
  const search = q.trim();
  const valid = search.length >= CANDIDATE_QUERY_MIN && search.length <= CANDIDATE_QUERY_MAX;
  return useQuery({
    queryKey: queryKeys.memberCandidates(groupId, search),
    queryFn: () => listMemberCandidates(groupId, search),
    enabled: enabled && valid,
    retry: false,
  });
}

export function useCreateGroup() {
  return useAccessMutation({
    mutationFn: (body: GroupCreate) => createGroup(body),
    ...ADMIN_WRITE,
  });
}

export interface UpdateGroupVars {
  groupId: string;
  update: GroupUpdate;
}

export function useUpdateGroup() {
  return useAccessMutation({
    mutationFn: ({ groupId, update }: UpdateGroupVars) => updateGroup(groupId, update),
    ...ADMIN_WRITE,
  });
}

export function useDeleteGroup() {
  return useAccessMutation({
    mutationFn: (groupId: string) => deleteGroup(groupId),
    ...ADMIN_WRITE,
  });
}

export interface MemberVars {
  groupId: string;
  userId: string;
  standing?: GroupStanding;
}

export function usePutMember() {
  return useAccessMutation({
    mutationFn: ({ groupId, userId, standing }: MemberVars) => putMember(groupId, userId, standing),
    ...ADMIN_WRITE,
  });
}

export function useRemoveMember() {
  return useAccessMutation({
    mutationFn: ({ groupId, userId }: MemberVars) => removeMember(groupId, userId),
    ...ADMIN_WRITE,
  });
}
