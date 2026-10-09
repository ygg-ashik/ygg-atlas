import { keepPreviousData, useQuery } from '@tanstack/react-query';
import {
  fetchAuditSummary,
  listChanges,
  listDecisions,
  type ChangeFilters,
  type DecisionFilters,
  type SummaryDays,
} from '../audit';
import { queryKeys } from '../query-keys';
import { useCursorList } from './use-cursor-list';

export const AUDIT_PAGE_SIZE = 100;

/** The access change log; a new filter object is a new list (its own key). */
export function useChanges(filters: ChangeFilters = {}, enabled = true) {
  return useCursorList(
    queryKeys.changes(filters),
    (cursor) => listChanges({ filters, cursor, limit: AUDIT_PAGE_SIZE }),
    { enabled },
  );
}

/** Every atlas tool decision (allow and deny). */
export function useDecisions(filters: DecisionFilters = {}, enabled = true) {
  return useCursorList(
    queryKeys.decisions(filters),
    (cursor) => listDecisions({ filters, cursor, limit: AUDIT_PAGE_SIZE }),
    { enabled },
  );
}

export function useAuditSummary(days: SummaryDays, enabled = true) {
  return useQuery({
    queryKey: queryKeys.auditSummary(days),
    queryFn: () => fetchAuditSummary(days),
    placeholderData: keepPreviousData,
    enabled,
  });
}
