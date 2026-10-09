import { render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { type AuditDecision, type AuditSummary, type Change } from '@/api/audit';
import { createQueryWrapper } from '@/api/hooks/test-query-wrapper';
import { type CredentialEvent } from '@/api/tokens';
import { AuditPage } from './audit-page';
import { diffLines } from './change-diff';
import { fast } from './test-fixtures';

const listChanges = vi.hoisted(() => vi.fn());
const listDecisions = vi.hoisted(() => vi.fn());
const fetchAuditSummary = vi.hoisted(() => vi.fn());
const listCredentialEvents = vi.hoisted(() => vi.fn());
vi.mock('../hooks/use-debounced-value', () => ({ useDebouncedValue: <T,>(value: T) => value }));
vi.mock('@/api/audit', () => ({ listChanges, listDecisions, fetchAuditSummary }));
vi.mock('@/api/tokens', () => ({ listCredentialEvents }));

function change(id: string, overrides: Partial<Change> = {}): Change {
  return {
    id,
    actor_user_id: 'u-ashik',
    via: 'web',
    action: 'user.role',
    object_type: 'user',
    object_id: 'u-yousef',
    before: { role: 'viewer', status: 'active' },
    after: { role: 'analyst', status: 'active' },
    at: '2026-10-09T09:41:00Z',
    actor: { display_name: 'Ashik Babu', email: 'ashik@yougotagift.com' },
    ...overrides,
  };
}

function decision(id: string, overrides: Partial<AuditDecision> = {}): AuditDecision {
  return {
    id,
    user: { user_id: 'u-omar', email: 'omar@yougotagift.com', display_name: 'Omar Khalil' },
    auth_method: 'web',
    surface: 'chat',
    tool: 'query_metric',
    arguments: { metric: 'demo/order/revenue' },
    decision: 'allow',
    deny_reason: null,
    success: true,
    error: null,
    duration_ms: 412,
    created_at: '2026-10-09T09:46:00Z',
    ...overrides,
  };
}

const SUMMARY: AuditSummary = {
  days: 7,
  per_day: [
    { date: '2026-10-08', allow: 536, deny: 22 },
    { date: '2026-10-09', allow: 412, deny: 18 },
  ],
  top_deny_reasons: [{ reason: 'no grant allows it', count: 58 }],
  top_denied_users: [{ user_id: 'u-omar', display_name: 'Omar Khalil', count: 12 }],
};

function renderPage() {
  const { wrapper: Wrapper } = createQueryWrapper();
  render(
    <Wrapper>
      <MemoryRouter initialEntries={['/admin/audit']}>
        <AuditPage />
      </MemoryRouter>
    </Wrapper>,
  );
}

const lastCall = (fn: typeof listChanges) => fn.mock.calls.at(-1)?.[0];
const openTab = async (name: string) => fast().click(screen.getByRole('tab', { name }));

describe('AuditPage', () => {
  beforeEach(() => {
    listChanges.mockReset().mockImplementation(({ cursor }: { cursor?: string }) =>
      Promise.resolve(
        cursor
          ? { items: [change('c3', { action: 'group.create', actor: null })], next_cursor: null }
          : {
              items: [
                change('c1'),
                change('c2', {
                  action: 'member.put',
                  object_type: 'group_member',
                  before: null,
                  after: { standing: 'member' },
                }),
              ],
              next_cursor: 'k1',
            },
      ),
    );
    listDecisions.mockReset().mockResolvedValue({
      items: [
        decision('d1'),
        decision('d2', {
          decision: 'deny',
          deny_reason: 'no grant allows it',
          tool: 'funnel_analyze',
          duration_ms: 34,
        }),
      ],
      next_cursor: null,
    });
    fetchAuditSummary.mockReset().mockResolvedValue(SUMMARY);
    listCredentialEvents.mockReset().mockResolvedValue({ available: false, reason: 'missing' });
  });

  it('opens on Changes with actor, mono action, object and UTC time', async () => {
    renderPage();
    expect(screen.getByRole('heading', { level: 2, name: 'Audit' })).toBeInTheDocument();
    const table = await screen.findByRole('table', { name: 'Access changes' });
    expect(screen.getByRole('tab', { name: 'Changes' })).toHaveAttribute('aria-selected', 'true');
    const action = within(table).getByText('user.role');
    expect(action).toHaveClass('font-mono');
    expect(within(table).getAllByText('Ashik Babu')).toHaveLength(2);
    expect(within(table).getAllByText('09 Oct 09:41')).toHaveLength(2);
    expect(within(table).getAllByText('u-yousef', { exact: false }).length).toBeGreaterThan(0);
    expect(fetchAuditSummary).not.toHaveBeenCalled();
    expect(listDecisions).not.toHaveBeenCalled();
  });

  it('expands a change into a before → after diff', async () => {
    renderPage();
    const table = await screen.findByRole('table', { name: 'Access changes' });
    const [first] = within(table).getAllByRole('button', { name: 'Details' });
    await fast().click(first!);
    expect(first).toHaveAttribute('aria-expanded', 'true');
    const diff = document.querySelector('[data-diff]')!;
    expect(diff).toHaveTextContent('role');
    expect(diff.querySelector('[data-kind="remove"]')).toHaveTextContent('viewer');
    expect(diff.querySelector('[data-kind="add"]')).toHaveTextContent('analyst');
    expect(diff.querySelector('[data-kind="context"]')).toHaveTextContent('active');
  });

  it('change filters go to the API as query keys', async () => {
    renderPage();
    await screen.findByRole('table', { name: 'Access changes' });
    await fast().selectOptions(screen.getByRole('combobox', { name: 'Action' }), 'grant.create');
    await fast().selectOptions(screen.getByRole('combobox', { name: 'Object type' }), 'grant');
    await fast().selectOptions(screen.getByRole('combobox', { name: 'Actor' }), 'u-ashik');
    await fast().type(screen.getByRole('textbox', { name: 'From (UTC)' }), '2026-10-01');
    await fast().type(screen.getByRole('textbox', { name: 'To (UTC)' }), '2026-10-09');
    await waitFor(() =>
      expect(lastCall(listChanges)?.filters).toEqual({
        action: 'grant.create',
        object_type: 'grant',
        actor_user_id: 'u-ashik',
        since: '2026-10-01T00:00:00Z',
        until: '2026-10-10T00:00:00Z',
      }),
    );
  });

  it('a half-typed date is not sent', async () => {
    renderPage();
    await screen.findByRole('table', { name: 'Access changes' });
    await fast().type(screen.getByRole('textbox', { name: 'From (UTC)' }), '2026-1');
    expect(lastCall(listChanges)?.filters).toEqual({});
  });

  it('a reversed date range shows an inline hint and is not sent', async () => {
    renderPage();
    await screen.findByRole('table', { name: 'Access changes' });
    const from = screen.getByRole('textbox', { name: 'From (UTC)' });
    await fast().type(from, '2026-10-09');
    await fast().type(screen.getByRole('textbox', { name: 'To (UTC)' }), '2026-10-01');
    expect(await screen.findByText(/“To” is before “From”/)).toBeInTheDocument();
    expect(from).toHaveAttribute('aria-invalid', 'true');
    expect(from).toHaveAccessibleDescription(/“To” is before “From”/);
    // Neither date is sent while reversed.
    expect(lastCall(listChanges)?.filters).toEqual({});
    expect(listChanges.mock.calls.some(([req]) => 'until' in (req?.filters ?? {}))).toBe(false);
  });

  it('"Load more" follows the keyset cursor and appends', async () => {
    renderPage();
    await fast().click(await screen.findByRole('button', { name: 'Load more' }));
    const table = screen.getByRole('table', { name: 'Access changes' });
    expect(await within(table).findByText('group.create')).toBeInTheDocument();
    expect(lastCall(listChanges)?.cursor).toBe('k1');
    expect(within(table).getByText('CLI · operator')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Load more' })).not.toBeInTheDocument();
  });

  it('an empty, filtered change log offers Clear filters', async () => {
    listChanges.mockResolvedValue({ items: [], next_cursor: null });
    renderPage();
    expect(await screen.findByText('No access changes yet')).toBeInTheDocument();
    await fast().selectOptions(screen.getByRole('combobox', { name: 'Action' }), 'grant.create');
    await fast().click(await screen.findByRole('button', { name: 'Clear filters' }));
    expect(screen.getByRole('combobox', { name: 'Action' })).toHaveValue('');
  });

  it('a failed load is stated with Retry', async () => {
    listChanges.mockRejectedValue(new Error('down'));
    renderPage();
    expect(await screen.findByRole('alert')).toHaveTextContent("Couldn't load the change log");
  });

  it('Decisions: user, surface, mono tool, deny pill with mono reason, duration', async () => {
    renderPage();
    await openTab('Decisions');
    const table = await screen.findByRole('table', { name: 'Tool decisions' });
    expect(within(table).getByText('funnel_analyze')).toHaveClass('font-mono');
    const deny = within(table).getByText('deny');
    expect(deny.closest('[data-tone]')!.querySelector('[data-dot="diamond"]')).not.toBeNull();
    expect(within(table).getByText('no grant allows it')).toHaveClass('font-mono');
    expect(within(table).getByText('34 ms')).toBeInTheDocument();
    expect(within(table).getAllByText('Omar Khalil')).toHaveLength(2);
    expect(within(table).getAllByText('chat')).toHaveLength(2);
  });

  it('arguments only show in a collapsed JSON view', async () => {
    renderPage();
    await openTab('Decisions');
    const table = await screen.findByRole('table', { name: 'Tool decisions' });
    expect(within(table).queryByText(/demo\/order\/revenue/)).not.toBeInTheDocument();
    await fast().click(within(table).getAllByRole('button', { name: 'Details' })[0]!);
    const details = within(table).getByText('Arguments (JSON)').closest('details')!;
    expect(details).not.toHaveAttribute('open');
    expect(details).toHaveTextContent('"metric": "demo/order/revenue"');
  });

  it('Deny only, user and surface filters update the decisions query', async () => {
    renderPage();
    await openTab('Decisions');
    await screen.findByRole('table', { name: 'Tool decisions' });
    await fast().click(screen.getByRole('checkbox', { name: 'Deny only' }));
    await fast().selectOptions(screen.getByRole('combobox', { name: 'Surface' }), 'mcp');
    await fast().selectOptions(screen.getByRole('combobox', { name: 'User' }), 'u-omar');
    await fast().type(screen.getByRole('searchbox', { name: 'Tool' }), 'query_metric');
    await waitFor(() =>
      expect(lastCall(listDecisions)?.filters).toEqual({
        decision: 'deny',
        surface: 'mcp',
        user_id: 'u-omar',
        tool: 'query_metric',
      }),
    );
  });

  it('the sign-in method filter goes to the decisions query as auth_method', async () => {
    renderPage();
    await openTab('Decisions');
    await screen.findByRole('table', { name: 'Tool decisions' });
    await fast().selectOptions(screen.getByRole('combobox', { name: 'Sign-in' }), 'pat');
    await waitFor(() => expect(lastCall(listDecisions)?.filters).toEqual({ auth_method: 'pat' }));
  });

  it('Top denied users falls back to the user id when the name is empty', async () => {
    fetchAuditSummary.mockResolvedValue({
      ...SUMMARY,
      top_denied_users: [{ user_id: 'u-nameless', display_name: '', count: 3 }],
    });
    renderPage();
    await openTab('Summary');
    const users = await screen.findByRole('list', { name: 'Top denied users' });
    expect(within(users).getByText('u-nameless')).toBeInTheDocument();
  });

  it('Credentials shows "Not available yet" until phase 4 ships', async () => {
    renderPage();
    await openTab('Credentials');
    expect(await screen.findByText('Not available yet')).toBeInTheDocument();
    expect(listCredentialEvents).toHaveBeenCalled();
  });

  it('Credentials lists token and client events once available', async () => {
    const event: CredentialEvent = {
      id: 'e1',
      at: '2026-10-09T08:00:00Z',
      event: 'token.revoke',
      user_id: 'u-omar',
      actor_user_id: 'u-ashik',
      via: 'web',
      token_id: 'tok-12345678',
      client_id: null,
      details: { reason: 'lost laptop' },
    };
    listCredentialEvents.mockResolvedValue({ available: true, data: [event] });
    renderPage();
    await openTab('Credentials');
    const table = await screen.findByRole('table', { name: 'Credential events' });
    expect(within(table).getByText('token.revoke')).toHaveClass('font-mono');
    expect(within(table).queryByText(/lost laptop/)).not.toBeInTheDocument();
  });

  it('Summary labels every number in text and toggles 7 / 30 days', async () => {
    renderPage();
    await openTab('Summary');
    const perDay = await screen.findByRole('list', { name: 'Tool calls per day' });
    expect(within(perDay).getByText('412 allow')).toBeInTheDocument();
    expect(within(perDay).getByText('18 deny')).toBeInTheDocument();
    expect(within(perDay).getByText('Fri 09 Oct')).toBeInTheDocument();
    // Newest day first.
    expect(within(perDay).getAllByRole('listitem')[0]).toHaveTextContent('Fri 09 Oct');
    expect(perDay.querySelector('[data-series="secondary"]')).toHaveClass('series-hatch');
    expect(screen.getByText('Tool calls').nextElementSibling).toHaveTextContent('988');
    expect(screen.getByText('Deny rate').nextElementSibling).toHaveTextContent('4.0%');
    const reasons = screen.getByRole('list', { name: 'Top deny reasons' });
    expect(within(reasons).getByText('no grant allows it')).toHaveClass('font-mono');
    expect(within(reasons).getByText('58 denials')).toBeInTheDocument();
    const users = screen.getByRole('list', { name: 'Top denied users' });
    expect(within(users).getByText('12 denials')).toBeInTheDocument();
    expect(fetchAuditSummary).toHaveBeenLastCalledWith(7);
    await fast().click(screen.getByRole('radio', { name: 'Last 30 days' }));
    await waitFor(() => expect(fetchAuditSummary).toHaveBeenLastCalledWith(30));
  });

  it('a quiet range says so and offers 30 days', async () => {
    fetchAuditSummary.mockResolvedValue({
      days: 7,
      per_day: [{ date: '2026-10-09', allow: 0, deny: 0 }],
      top_deny_reasons: [],
      top_denied_users: [],
    });
    renderPage();
    await openTab('Summary');
    expect(await screen.findByText('No activity in this range')).toBeInTheDocument();
    await fast().click(screen.getByRole('button', { name: 'Show the last 30 days' }));
    await waitFor(() => expect(fetchAuditSummary).toHaveBeenLastCalledWith(30));
  });
});

describe('diffLines', () => {
  it('marks added, removed, changed and unchanged keys', () => {
    expect(
      diffLines(
        { role: 'viewer', status: 'active', note: 'x' },
        { role: 'analyst', status: 'active', tags: ['a'] },
      ),
    ).toEqual([
      { kind: 'remove', text: 'role      viewer' },
      { kind: 'add', text: 'role      analyst' },
      { kind: 'context', text: 'status    active' },
      { kind: 'remove', text: 'note      x' },
      { kind: 'add', text: 'tags      ["a"]' },
    ]);
  });

  it('a create has only additions, a delete only removals, null is a dash', () => {
    expect(diffLines(null, { expires_at: null })).toEqual([{ kind: 'add', text: 'expires_at —' }]);
    expect(diffLines({ name: 'g' }, null)).toEqual([{ kind: 'remove', text: 'name      g' }]);
    expect(diffLines(null, null)).toEqual([]);
  });
});
