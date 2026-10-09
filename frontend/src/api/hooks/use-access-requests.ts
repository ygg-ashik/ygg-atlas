import { useQuery } from '@tanstack/react-query';
import {
  approveRequest,
  cancelRequest,
  createRequest,
  declineRequest,
  fetchRequestOptions,
  listDecidableRequests,
  listMyRequests,
  type AccessRequestCreate,
  type RequestDecision,
  type RequestStatusFilter,
} from '../access-requests';
import { queryKeys } from '../query-keys';
import { ADMIN_WRITE, useAccessMutation } from './use-access-mutation';
import { useCursorList } from './use-cursor-list';

export const REQUEST_PAGE_SIZE = 50;

export function useMyRequests() {
  return useQuery({ queryKey: queryKeys.myRequestList, queryFn: listMyRequests });
}

/** Groups that hold `resource` and their managers' names; idle until a resource is chosen. */
export function useRequestOptions(resource: string | null) {
  return useQuery({
    queryKey: queryKeys.requestOptions(resource ?? ''),
    queryFn: () => fetchRequestOptions(resource as string),
    enabled: !!resource,
  });
}

/** Creating or cancelling changes no access: the caller's requests, badge count,
 * and the requester's `pending_requests` on admin user views refresh. Their 409s
 * ("already asked", "already decided") are final, so no Retry is offered. */
const OWN_REQUEST_VIEWS = [queryKeys.myRequests, queryKeys.myAccess, queryKeys.users];

export function useCreateRequest() {
  return useAccessMutation({
    mutationFn: (body: AccessRequestCreate) => createRequest(body),
    invalidates: OWN_REQUEST_VIEWS,
  });
}

export function useCancelRequest() {
  return useAccessMutation({
    mutationFn: (requestId: string) => cancelRequest(requestId),
    invalidates: OWN_REQUEST_VIEWS,
  });
}

export interface RequestQueueOptions {
  enabled?: boolean;
  /** Only this requester's requests (still inside the caller's decide scope). */
  userId?: string;
}

/** The decision queue (requests the caller may decide), newest first. */
export function useRequestQueue(
  status: RequestStatusFilter = 'pending',
  { enabled = true, userId }: RequestQueueOptions = {},
) {
  return useCursorList(
    queryKeys.requestQueueList(status, userId ?? null),
    (cursor) =>
      listDecidableRequests({ status, user_id: userId, cursor, limit: REQUEST_PAGE_SIZE }),
    { enabled },
  );
}

export interface DecideVars {
  requestId: string;
  decision?: RequestDecision;
}

/** Approval changes access (a member, role or grant), so every access view
 * refreshes (`['admin']` covers the queue and user detail). Decisions run under
 * AccessAdmin's write lock, so a 409 may be the stale-actor case: Retry offered. */
export function useApproveRequest() {
  return useAccessMutation({
    mutationFn: ({ requestId, decision }: DecideVars) => approveRequest(requestId, decision),
    ...ADMIN_WRITE,
  });
}

/** Decline changes no access: the queue, the pending badge and the requester's
 * `pending_requests` on user views refresh. */
export function useDeclineRequest() {
  return useAccessMutation({
    mutationFn: ({ requestId, decision }: DecideVars) =>
      declineRequest(requestId, { note: decision?.note }),
    invalidates: [queryKeys.requestQueue, queryKeys.users, queryKeys.myAccess],
    retryOn409: true,
  });
}
