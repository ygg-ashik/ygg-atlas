import { Clock } from 'lucide-react';
import { useState } from 'react';
import { type AuditSummary as Summary, type DayCount, type SummaryDays } from '@/api/audit';
import { useAuditSummary } from '@/api/hooks/use-audit';
import {
  Button,
  cn,
  EmptyState,
  ErrorNotice,
  SegmentedControl,
  type Series,
  SeriesSwatch,
  seriesFill,
  Skeleton,
  SkeletonRegion,
  Tag,
} from '@/ui';
import { plural } from '../format';
import { CARD } from './surfaces';

const WEEKDAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

/** `2026-10-09` → `Fri 09 Oct` (UTC). */
function dayLabel(iso: string): string {
  const d = new Date(`${iso}T00:00:00Z`);
  if (Number.isNaN(d.getTime())) return iso;
  const day = String(d.getUTCDate()).padStart(2, '0');
  return `${WEEKDAYS[d.getUTCDay()]} ${day} ${MONTHS[d.getUTCMonth()]}`;
}

const count = (n: number) => n.toLocaleString('en-US');
const pct = (part: number, whole: number) => (whole ? (part / whole) * 100 : 0);

const WINDOWS = [
  { value: '7', label: 'Last 7 days' },
  { value: '30', label: 'Last 30 days' },
] as const;

/** A labelled figure; the source tag is the provenance of the number. */
function Kpi({ label, value, days }: { label: string; value: string; days: number }) {
  return (
    <div className={cn(CARD, 'px-4 py-3.5')}>
      <div className="text-caption text-muted-foreground">{label}</div>
      <div className="my-1.5 text-[27px] font-semibold leading-[1.1] tracking-[-0.025em] text-ink tabular-nums">
        {value}
      </div>
      <Tag dot>atlas_audit_log · last {days} days</Tag>
    </div>
  );
}

function Bar({
  series,
  value,
  max,
  label,
}: {
  series: Series;
  value: number;
  max: number;
  label: string;
}) {
  return (
    <div className="flex items-center gap-2">
      <i
        aria-hidden
        data-series={series}
        className={cn('block h-2.5 rounded-[4px]', seriesFill(series))}
        style={{ width: `${Math.max(value ? 1.5 : 0, pct(value, max) * 0.82)}%` }}
      />
      <span className="whitespace-nowrap text-[11.5px] tabular-nums text-muted-foreground">
        {count(value)} {label}
      </span>
    </div>
  );
}

function PerDay({ days }: { days: readonly DayCount[] }) {
  const newestFirst = [...days].sort((a, b) => b.date.localeCompare(a.date));
  const max = Math.max(1, ...days.map((d) => Math.max(d.allow, d.deny)));
  return (
    <section className={cn(CARD, 'p-[18px]')} aria-labelledby="audit-per-day">
      <div className="mb-3 flex flex-wrap items-center gap-3">
        <h3 id="audit-per-day" className="font-serif text-section text-ink">
          Per day
        </h3>
        <span className="ml-auto flex gap-3">
          <SeriesSwatch series="primary">allow</SeriesSwatch>
          <SeriesSwatch series="secondary">deny</SeriesSwatch>
        </span>
      </div>
      <ul aria-label="Tool calls per day" className="grid gap-2.5">
        {newestFirst.map((d) => (
          <li key={d.date} className="grid grid-cols-[76px_1fr] items-center gap-3 text-[12.5px]">
            <span className="tabular-nums text-muted-foreground">{dayLabel(d.date)}</span>
            <div className="grid gap-[3px]">
              <Bar series="primary" value={d.allow} max={max} label="allow" />
              <Bar series="secondary" value={d.deny} max={max} label="deny" />
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}

interface TopRow {
  key: string;
  label: string;
  count: number;
  mono?: boolean;
}

function TopList({
  title,
  rows,
  empty,
}: {
  title: string;
  rows: readonly TopRow[];
  empty: string;
}) {
  const max = Math.max(1, ...rows.map((r) => r.count));
  return (
    <section className={cn(CARD, 'p-[18px]')}>
      <h3 className="mb-2 font-serif text-section text-ink">{title}</h3>
      {rows.length ? (
        <ul aria-label={title}>
          {rows.map((r) => (
            <li
              key={r.key}
              className="grid grid-cols-[1fr_auto] gap-x-2.5 gap-y-1 border-b border-border/50 py-[9px] text-[13px] last:border-b-0"
            >
              <span className={cn('text-ink', r.mono && 'font-mono text-xs')}>{r.label}</span>
              <span className="tabular-nums text-muted-foreground">
                {plural(r.count, 'denial')}
              </span>
              <div
                aria-hidden
                className="col-span-full h-1.5 overflow-hidden rounded-[3px] bg-primary/10"
              >
                <i
                  className="block h-full bg-primary-text"
                  style={{ width: `${pct(r.count, max)}%` }}
                />
              </div>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-caption text-muted-foreground">{empty}</p>
      )}
    </section>
  );
}

function SummaryBody({ summary, onWiden }: { summary: Summary; onWiden?: () => void }) {
  const allow = summary.per_day.reduce((s, d) => s + d.allow, 0);
  const deny = summary.per_day.reduce((s, d) => s + d.deny, 0);
  const total = allow + deny;
  if (total === 0) {
    return (
      <EmptyState
        icon={<Clock className="h-5 w-5" />}
        title="No activity in this range"
        actions={
          onWiden && (
            <Button variant="pill" onClick={onWiden}>
              Show the last 30 days
            </Button>
          )
        }
      >
        Access changes and tool decisions from the last {summary.days} days show here.
      </EmptyState>
    );
  }
  return (
    <>
      <div className="mb-3 grid grid-cols-2 gap-3 min-[900px]:grid-cols-4">
        <Kpi label="Tool calls" value={count(total)} days={summary.days} />
        <Kpi label="Allowed" value={count(allow)} days={summary.days} />
        <Kpi label="Denied" value={count(deny)} days={summary.days} />
        <Kpi label="Deny rate" value={`${pct(deny, total).toFixed(1)}%`} days={summary.days} />
      </div>
      <div className="grid gap-3 min-[900px]:grid-cols-[1.6fr_1fr]">
        <PerDay days={summary.per_day} />
        <div className="grid content-start gap-3">
          <TopList
            title="Top deny reasons"
            empty="No denials in this range."
            rows={summary.top_deny_reasons.map((r) => ({
              key: r.reason,
              label: r.reason,
              count: r.count,
              mono: true,
            }))}
          />
          <TopList
            title="Top denied users"
            empty="No denials in this range."
            rows={summary.top_denied_users.map((u) => ({
              key: u.user_id,
              label: u.display_name,
              count: u.count,
            }))}
          />
        </div>
      </div>
    </>
  );
}

type SummaryQuery = ReturnType<typeof useAuditSummary>;

/** Skeleton, a stated failure with Retry, or the summary. */
function SummaryState({ summary, onWiden }: { summary: SummaryQuery; onWiden?: () => void }) {
  if (summary.isPending) {
    return (
      <SkeletonRegion label="the audit summary" className={cn(CARD, 'grid gap-3 p-[18px]')}>
        {Array.from({ length: 6 }, (_, i) => (
          <Skeleton key={i} style={{ width: `${40 + ((i * 13) % 45)}%` }} />
        ))}
      </SkeletonRegion>
    );
  }
  if (summary.isError) {
    return (
      <ErrorNotice
        title="Couldn't load the audit summary"
        onRetry={() => void summary.refetch()}
        retrying={summary.isFetching}
      >
        The access service didn&apos;t answer. Nothing changed.
      </ErrorNotice>
    );
  }
  return <SummaryBody summary={summary.data} onWiden={onWiden} />;
}

/** Summary tab: allow / deny per day and the top deny reasons and users, over
 * the last 7 or 30 days. Every figure carries a text label. */
export function AuditSummary() {
  const [days, setDays] = useState<SummaryDays>(7);
  const summary = useAuditSummary(days);
  return (
    <>
      <SegmentedControl
        kind="radio"
        label="Summary range"
        className="mb-3"
        options={WINDOWS}
        value={String(days) as '7' | '30'}
        onChange={(v) => setDays(v === '30' ? 30 : 7)}
      />
      <SummaryState summary={summary} onWiden={days === 7 ? () => setDays(30) : undefined} />
    </>
  );
}
