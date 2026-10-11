// Audit views (admin:audit): the access change log, the atlas decision log and
// the deny summary. Shapes: phase 5 (B4) — `Page[ChangeOut]`, `Page[AuditDecisionOut]`,
// `AuditSummaryOut`.
import { api } from './axios-instance';
import { type Page } from './cursor';
import { compactParams } from './params';

/** Who made a change; null for CLI and bootstrap rows. */
export interface ActorRef {
  display_name: string;
  email: string;
}

/** `ChangeOut`: one `rbac_changes` row. */
export interface Change {
  id: string;
  actor_user_id: string | null;
  via: string;
  action: string;
  object_type: string;
  object_id: string;
  before: Record<string, unknown> | null;
  after: Record<string, unknown> | null;
  at: string;
  actor: ActorRef | null;
}

/** `GET /admin/rbac-changes` filters; `since`/`until` are ISO-8601 times. */
export interface ChangeFilters {
  actor_user_id?: string;
  object_type?: string;
  action?: string;
  object_id?: string;
  since?: string;
  until?: string;
}

export interface AuditUser {
  user_id: string;
  email: string;
  display_name: string;
}

export type DecisionVerdict = 'allow' | 'deny';

/** `AuditDecisionOut`: one atlas tool call and its policy decision. */
export interface AuditDecision {
  id: string;
  user: AuditUser;
  auth_method: string | null;
  surface: string;
  tool: string;
  arguments: Record<string, unknown> | null;
  decision: DecisionVerdict;
  deny_reason: string | null;
  success: boolean;
  error: string | null;
  duration_ms: number | null;
  created_at: string;
}

/** `GET /admin/audit/decisions` filters. */
export interface DecisionFilters {
  user_id?: string;
  decision?: DecisionVerdict;
  surface?: string;
  tool?: string;
  auth_method?: string;
  since?: string;
  until?: string;
}

export type SummaryDays = 7 | 30;

export interface DayCount {
  /** ISO date, UTC. */
  date: string;
  allow: number;
  deny: number;
}

export interface ReasonCount {
  reason: string;
  count: number;
}

export interface UserCount {
  user_id: string;
  display_name: string;
  count: number;
}

/** `AuditSummaryOut`. */
export interface AuditSummary {
  days: number;
  per_day: DayCount[];
  top_deny_reasons: ReasonCount[];
  top_denied_users: UserCount[];
}

export interface LogPageRequest<F> {
  filters?: F;
  cursor?: string;
  limit?: number;
}

export async function listChanges({
  filters = {},
  cursor,
  limit,
}: LogPageRequest<ChangeFilters> = {}) {
  const params = compactParams({ ...filters, cursor, limit });
  const { data } = await api.get<Page<Change>>('/admin/rbac-changes', { params });
  return data;
}

export async function listDecisions({
  filters = {},
  cursor,
  limit,
}: LogPageRequest<DecisionFilters> = {}) {
  const params = compactParams({ ...filters, cursor, limit });
  const { data } = await api.get<Page<AuditDecision>>('/admin/audit/decisions', { params });
  return data;
}

export async function fetchAuditSummary(days: SummaryDays): Promise<AuditSummary> {
  const { data } = await api.get<AuditSummary>('/admin/audit/summary', { params: { days } });
  return data;
}
