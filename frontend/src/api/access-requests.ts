// Access requests: the caller's own (/me/requests*) and the decision queue
// (/admin/requests*). Shapes: backend app/access/schemas.py (phase 5, B3).
import { api } from './axios-instance';
import { type Page } from './cursor';
import { compactParams, seg } from './params';

export type RequestKind = 'group' | 'role' | 'resource';
export type RequestStatus = 'pending' | 'approved' | 'declined' | 'cancelled';
/** The queue filter: one status, `decided` (approved or declined; P5-D23),
 * or every status. */
export type RequestStatusFilter = RequestStatus | 'decided' | 'all';

export interface Requester {
  user_id: string;
  email: string;
  display_name: string;
  role: string;
}

/** `user_id` is null when the request was decided from the CLI. */
export interface Decider {
  user_id: string | null;
  display_name: string;
}

/** `AccessRequestOut`; `requester` is embedded on admin views only. */
export interface AccessRequest {
  id: string;
  kind: RequestKind;
  target: string;
  target_label: string;
  note: string;
  status: RequestStatus;
  created_at: string;
  decided_by: Decider | null;
  decided_at: string | null;
  decision_note: string;
  requester?: Requester | null;
}

export interface AccessRequestCreate {
  kind: RequestKind;
  target: string;
  note: string;
}

/** `RequestDecision`. For a resource approval, leave `expires_at` out for the
 * 90-day default, send `null` for no expiry, or a future ISO time. It must be
 * left out for group and role requests (the backend answers 422). */
export interface RequestDecision {
  note?: string;
  expires_at?: string | null;
}

export interface RequestGroupOption {
  id: string;
  name: string;
  /** Managers' display names, never emails. */
  managers: string[];
}

export interface RequestOptions {
  resource: string;
  groups: RequestGroupOption[];
  can_request_resource: boolean;
}

export interface RequestQueueRequest {
  status?: RequestStatusFilter;
  /** One requester's requests, still inside the caller's decide scope (P5-D24). */
  user_id?: string;
  cursor?: string;
  limit?: number;
}

export async function listMyRequests(): Promise<AccessRequest[]> {
  const { data } = await api.get<AccessRequest[]>('/me/requests');
  return data;
}

export async function fetchRequestOptions(resource: string): Promise<RequestOptions> {
  const { data } = await api.get<RequestOptions>('/me/requests/options', {
    params: { resource },
  });
  return data;
}

export async function createRequest(body: AccessRequestCreate): Promise<AccessRequest> {
  const { data } = await api.post<AccessRequest>('/me/requests', body);
  return data;
}

export async function cancelRequest(requestId: string): Promise<AccessRequest> {
  const { data } = await api.post<AccessRequest>(`/me/requests/${seg(requestId)}/cancel`);
  return data;
}

/** Requests the caller may decide, newest first (the backend defaults to pending). */
export async function listDecidableRequests({
  status,
  user_id,
  cursor,
  limit,
}: RequestQueueRequest = {}) {
  const params = compactParams({ status, user_id, cursor, limit });
  const { data } = await api.get<Page<AccessRequest>>('/admin/requests', { params });
  return data;
}

export async function approveRequest(
  requestId: string,
  decision: RequestDecision = {},
): Promise<AccessRequest> {
  const { data } = await api.post<AccessRequest>(
    `/admin/requests/${seg(requestId)}/approve`,
    decision,
  );
  return data;
}

export async function declineRequest(
  requestId: string,
  decision: Pick<RequestDecision, 'note'> = {},
): Promise<AccessRequest> {
  const { data } = await api.post<AccessRequest>(
    `/admin/requests/${seg(requestId)}/decline`,
    decision,
  );
  return data;
}
