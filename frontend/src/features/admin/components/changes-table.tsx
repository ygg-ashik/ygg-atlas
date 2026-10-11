import { History } from 'lucide-react';
import { useMemo, useState } from 'react';
import { type Change, type ChangeFilters } from '@/api/audit';
import { useGroups } from '@/api/hooks/use-admin-groups';
import { useAdminUsers } from '@/api/hooks/use-admin-users';
import { useChanges } from '@/api/hooks/use-audit';
import { useMyAccess } from '@/api/hooks/use-my-access';
import { Button, DataTable, type DataColumn, EmptyState, FilterBar } from '@/ui';
import { changeLabel, type NameBook, nameBook } from '../change-label';
import { seenAt } from '../format';
import { useDebouncedValue } from '../hooks/use-debounced-value';
import {
  DateRangeFields,
  type DateRange,
  NO_RANGE,
  PagedBody,
  Pick,
  type PickOption,
  plainOptions,
  rangeQuery,
  seenOptions,
} from './audit-filters';
import { ChangeDiff } from './change-diff';

/** Every action `rbac_changes` records (backend `app/access`). */
const ACTIONS = plainOptions([
  'grant.create',
  'grant.revoke',
  'group.create',
  'group.delete',
  'group.update',
  'member.put',
  'member.remove',
  'request.approve',
  'user.bootstrap_admin',
  'user.role',
  'user.status',
  'user.update',
]);
const OBJECT_TYPES = plainOptions(['access_request', 'grant', 'group', 'group_member', 'user']);

interface FilterState {
  objectId: string;
  action: string;
  objectType: string;
  actor: PickOption | null;
  range: DateRange;
}

const NO_FILTERS: FilterState = {
  objectId: '',
  action: '',
  objectType: '',
  actor: null,
  range: NO_RANGE,
};

function toQuery(f: FilterState): ChangeFilters {
  const out: ChangeFilters = {};
  if (f.objectId.trim()) out.object_id = f.objectId.trim();
  if (f.action) out.action = f.action;
  if (f.objectType) out.object_type = f.objectType;
  if (f.actor) out.actor_user_id = f.actor.value;
  return { ...out, ...rangeQuery(f.range) };
}

const actorName = (c: Change) =>
  c.actor ? c.actor.display_name || c.actor.email : 'CLI · operator';

function columns(names: NameBook): readonly DataColumn<Change>[] {
  return [
    {
      key: 'time',
      header: 'Time (UTC)',
      cell: (c) => <span className="whitespace-nowrap text-muted-foreground">{seenAt(c.at)}</span>,
    },
    { key: 'actor', header: 'Actor', cell: actorName },
    {
      key: 'action',
      header: 'Action',
      cell: (c) => <span className="font-mono text-xs text-ink">{c.action}</span>,
    },
    {
      key: 'object',
      header: 'Object',
      cell: (c) => (
        <span
          className="block max-w-[22rem] truncate whitespace-nowrap"
          title={`${c.object_type} ${c.object_id}`}
        >
          {changeLabel(c, names)}
        </span>
      ),
    },
  ];
}

/** Names for the Object column from lists the viewer may already read: groups
 * (admin:groups) and the first page of users (admin:users), plus every actor
 * on screen. Misses fall back to short ids. */
function useChangeNames(changes: readonly Change[]): NameBook {
  const me = useMyAccess();
  const groups = useGroups({ enabled: me.can('admin:groups') });
  const users = useAdminUsers({}, { enabled: me.can('admin:users') });
  return useMemo(() => {
    const actors = changes.flatMap((c) =>
      c.actor_user_id && c.actor ? [{ user_id: c.actor_user_id, email: c.actor.email }] : [],
    );
    return nameBook({
      groups: groups.data ?? [],
      users: [...actors, ...users.items.map((u) => ({ user_id: u.id, email: u.email }))],
    });
  }, [changes, groups.data, users.items]);
}

/** Changes tab: the paged `rbac_changes` log, newest first; a row expands into
 * its before → after diff. */
export function ChangesTable() {
  const [filters, setFilters] = useState<FilterState>(NO_FILTERS);
  const [open, setOpen] = useState<string | null>(null);
  const objectId = useDebouncedValue(filters.objectId);
  const changes = useChanges(toQuery({ ...filters, objectId }));
  const names = useChangeNames(changes.items);
  const cols = useMemo(() => columns(names), [names]);
  const set = (patch: Partial<FilterState>) => setFilters((f) => ({ ...f, ...patch }));
  const actors = seenOptions(
    changes.items,
    (c) => (c.actor_user_id && c.actor ? { value: c.actor_user_id, label: actorName(c) } : null),
    filters.actor,
  );
  const filtered = Object.keys(toQuery(filters)).length > 0;

  return (
    <>
      <FilterBar
        label="Filter changes"
        search={{
          value: filters.objectId,
          onChange: (v) => set({ objectId: v }),
          placeholder: 'Object id (exact)',
          label: 'Object id',
        }}
        summary={changes.isSuccess ? `${changes.items.length} shown` : undefined}
      >
        <Pick
          label="Action"
          value={filters.action}
          options={ACTIONS}
          onChange={(action) => set({ action })}
        />
        <Pick
          label="Object type"
          value={filters.objectType}
          options={OBJECT_TYPES}
          onChange={(objectType) => set({ objectType })}
        />
        <Pick
          label="Actor"
          value={filters.actor?.value ?? ''}
          options={actors}
          onChange={(v) => set({ actor: actors.find((a) => a.value === v) ?? null })}
        />
        <DateRangeFields value={filters.range} onChange={(range) => set({ range })} />
      </FilterBar>
      <PagedBody query={changes} what="the change log">
        {changes.items.length > 0 ? (
          <DataTable
            caption="Access changes"
            columns={cols}
            rows={changes.items}
            rowKey={(c) => c.id}
            expandedKey={open}
            onToggleExpand={(key) => setOpen((k) => (k === key ? null : key))}
            renderExpanded={(c) => <ChangeDiff change={c} />}
          />
        ) : (
          <EmptyState
            icon={<History className="h-5 w-5" />}
            title={filtered ? 'No changes match these filters' : 'No access changes yet'}
            actions={
              filtered && (
                <Button variant="pill" onClick={() => setFilters(NO_FILTERS)}>
                  Clear filters
                </Button>
              )
            }
          >
            Role, group, membership and grant changes show here with who made them.
          </EmptyState>
        )}
      </PagedBody>
    </>
  );
}
