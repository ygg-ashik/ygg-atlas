import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fetchAuditSummary, listChanges, listDecisions } from './audit';
import { answerWith, http } from './test-api-mock';

vi.mock('./axios-instance', async () => (await import('./test-api-mock')).apiMock);

describe('audit client', () => {
  beforeEach(() => answerWith({ items: [], next_cursor: 'n' }));

  it('pages the change log with filters', async () => {
    const page = await listChanges({
      filters: { object_type: 'grant', action: '', since: '2026-10-01T00:00:00Z' },
      cursor: 'c',
      limit: 100,
    });
    expect(page.next_cursor).toBe('n');
    expect(http.get).toHaveBeenCalledWith('/admin/rbac-changes', {
      params: { object_type: 'grant', since: '2026-10-01T00:00:00Z', cursor: 'c', limit: 100 },
    });
  });

  it('pages the decision log with filters', async () => {
    await listDecisions({ filters: { decision: 'deny', surface: 'mcp' } });
    expect(http.get).toHaveBeenCalledWith('/admin/audit/decisions', {
      params: { decision: 'deny', surface: 'mcp' },
    });
  });

  it('reads the summary for 7 or 30 days', async () => {
    await fetchAuditSummary(30);
    expect(http.get).toHaveBeenCalledWith('/admin/audit/summary', { params: { days: 30 } });
  });
});
