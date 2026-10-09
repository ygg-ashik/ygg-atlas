import { useQuery } from '@tanstack/react-query';
import { type GroupStanding } from '../access';
import {
  createGroup,
  deleteGroup,
  fetchGroupDetail,
  listGroups,
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
