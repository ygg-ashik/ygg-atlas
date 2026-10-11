import { ShieldCheck } from 'lucide-react';
import { useState } from 'react';
import { type AuditDecision, type DecisionFilters } from '@/api/audit';
import { useDecisions } from '@/api/hooks/use-audit';
import { Button, Checkbox, DataTable, type DataColumn, EmptyState, FilterBar, Tag } from '@/ui';
import { seenAt } from '../format';
import { useDebouncedValue } from '../hooks/use-debounced-value';
import {
  DateRangeFields,
  type DateRange,
  JsonDetails,
  NO_RANGE,
  PagedBody,
  Pick,
  type PickOption,
  plainOptions,
  rangeQuery,
  seenOptions,
} from './audit-filters';
import { EffectPill } from './effect-pill';

/** `atlas_audit_log.surface` values. */
const SURFACES = plainOptions(['api', 'chat', 'mcp']);
/** `Principal.auth_method` values (identity `AuthMethod`). */
const AUTH_METHODS = plainOptions(['web', 'oauth', 'pat', 'service', 'dev']);

interface FilterState {
  tool: string;
  denyOnly: boolean;
  surface: string;
  authMethod: string;
  user: PickOption | null;
  range: DateRange;
}

const NO_FILTERS: FilterState = {
  tool: '',
  denyOnly: false,
  surface: '',
  authMethod: '',
  user: null,
  range: NO_RANGE,
};

function toQuery(f: FilterState): DecisionFilters {
  const out: DecisionFilters = {};
  if (f.tool.trim()) out.tool = f.tool.trim();
  if (f.denyOnly) out.decision = 'deny';
  if (f.surface) out.surface = f.surface;
  if (f.authMethod) out.auth_method = f.authMethod;
  if (f.user) out.user_id = f.user.value;
  return { ...out, ...rangeQuery(f.range) };
}

const userName = (d: AuditDecision) => d.user.display_name || d.user.email;

const COLUMNS: readonly DataColumn<AuditDecision>[] = [
  {
    key: 'time',
    header: 'Time (UTC)',
    cell: (d) => (
      <span className="whitespace-nowrap text-muted-foreground">{seenAt(d.created_at)}</span>
    ),
  },
  { key: 'user', header: 'User', cell: userName },
  { key: 'surface', header: 'Surface', cell: (d) => <Tag>{d.surface}</Tag> },
  {
    key: 'tool',
    header: 'Tool',
    cell: (d) => <span className="font-mono text-xs text-ink">{d.tool}</span>,
  },
  { key: 'decision', header: 'Decision', cell: (d) => <EffectPill effect={d.decision} /> },
  {
    key: 'reason',
    header: 'Deny reason',
    cell: (d) =>
      d.deny_reason ? (
        <span className="font-mono text-xs">{d.deny_reason}</span>
      ) : (
        <span className="text-muted-foreground">—</span>
      ),
  },
  {
    key: 'duration',
    header: 'Duration',
    align: 'end',
    cell: (d) => (d.duration_ms === null ? '—' : `${d.duration_ms} ms`),
  },
];

/** The expanded decision: outcome facts, then the arguments as collapsed JSON. */
function DecisionDetail({ decision }: { decision: AuditDecision }) {
  return (
    <div className="grid gap-1.5">
      <p className="text-caption text-muted-foreground">
        {decision.user.email} · signed in with {decision.auth_method ?? 'unknown'} ·{' '}
        {decision.success ? 'the tool call succeeded' : 'the tool call failed'}
        {decision.error && (
          <>
            {' '}
            · <span className="font-mono">{decision.error}</span>
          </>
        )}
      </p>
      {decision.arguments && <JsonDetails label="Arguments (JSON)" value={decision.arguments} />}
    </div>
  );
}

/** Decisions tab: every allow and deny the atlas tools made, newest first. */
export function DecisionsTable() {
  const [filters, setFilters] = useState<FilterState>(NO_FILTERS);
  const [open, setOpen] = useState<string | null>(null);
  const tool = useDebouncedValue(filters.tool);
  const decisions = useDecisions(toQuery({ ...filters, tool }));
  const set = (patch: Partial<FilterState>) => setFilters((f) => ({ ...f, ...patch }));
  const users = seenOptions(
    decisions.items,
    (d) => ({ value: d.user.user_id, label: userName(d) }),
    filters.user,
  );
  const filtered = Object.keys(toQuery(filters)).length > 0;

  return (
    <>
      <FilterBar
        label="Filter decisions"
        search={{
          value: filters.tool,
          onChange: (v) => set({ tool: v }),
          placeholder: 'Tool, e.g. query_metric',
          label: 'Tool',
        }}
        summary={decisions.isSuccess ? `${decisions.items.length} shown` : undefined}
      >
        <Checkbox
          label="Deny only"
          checked={filters.denyOnly}
          onChange={(e) => set({ denyOnly: e.target.checked })}
        />
        <Pick
          label="Surface"
          value={filters.surface}
          options={SURFACES}
          onChange={(surface) => set({ surface })}
        />
        <Pick
          label="Sign-in"
          value={filters.authMethod}
          options={AUTH_METHODS}
          onChange={(authMethod) => set({ authMethod })}
        />
        <Pick
          label="User"
          value={filters.user?.value ?? ''}
          options={users}
          onChange={(v) => set({ user: users.find((u) => u.value === v) ?? null })}
        />
        <DateRangeFields value={filters.range} onChange={(range) => set({ range })} />
      </FilterBar>
      <PagedBody query={decisions} what="the decision log">
        {decisions.items.length > 0 ? (
          <DataTable
            caption="Tool decisions"
            columns={COLUMNS}
            rows={decisions.items}
            rowKey={(d) => d.id}
            expandedKey={open}
            onToggleExpand={(key) => setOpen((k) => (k === key ? null : key))}
            renderExpanded={(d) => <DecisionDetail decision={d} />}
          />
        ) : (
          <EmptyState
            icon={<ShieldCheck className="h-5 w-5" />}
            title={filtered ? 'No decisions match these filters' : 'No tool decisions yet'}
            actions={
              filtered && (
                <Button variant="pill" onClick={() => setFilters(NO_FILTERS)}>
                  Clear filters
                </Button>
              )
            }
          >
            Every atlas tool call is logged with its allow or deny and the reason.
          </EmptyState>
        )}
      </PagedBody>
    </>
  );
}
