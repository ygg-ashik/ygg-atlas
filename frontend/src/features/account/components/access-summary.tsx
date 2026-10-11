import { type ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { type CapabilityCatalog, type MeAccess } from '@/api/access';
import { Avatar, cn, ErrorNotice, RolePill } from '@/ui';
import { addedCapabilities, nextRole } from '../request-rules';
import { GroupList } from './group-list';

interface AccessSummaryProps {
  access: MeAccess;
  /** Descriptions and role ladder; absent while loading or after a failure. */
  catalog: CapabilityCatalog | undefined;
  catalogFailed: boolean;
  catalogRetrying: boolean;
  onRetryCatalog: () => void;
}

const LABEL = 'text-label font-medium text-ink';

/** Identity, role, capabilities (and what the next role adds), and groups,
 * all as the backend reported them (DESIGN.md › Admin and self-service). */
export function AccessSummary({
  access,
  catalog,
  catalogFailed,
  catalogRetrying,
  onRetryCatalog,
}: AccessSummaryProps) {
  const describe = new Map(catalog?.capabilities.map((c) => [c.code, c.description]));
  const roles = catalog?.roles ?? [];
  const next = nextRole(roles, access.role);
  const adds = next ? addedCapabilities(roles, access.role, next).slice(0, 2) : [];
  return (
    <section
      aria-label="Your access"
      className="rounded-card bg-card px-5 py-[18px] shadow-[0_0_0_1px_hsl(var(--border)/0.6),0_1px_2px_rgba(0,0,0,0.04)]"
    >
      <div className="flex flex-wrap items-center gap-3.5">
        <Avatar name={access.display_name || access.email} size="lg" />
        <div className="min-w-0 flex-1">
          <div className="font-serif text-[19px] text-ink">
            {access.display_name?.trim() || access.email}
          </div>
          <div className="truncate text-[13px] text-muted-foreground">{access.email}</div>
        </div>
        <div className="text-right">
          <RolePill role={access.role} />
          <div className="mt-1 text-caption text-muted-foreground">Role · set by an admin</div>
        </div>
      </div>

      <div className={cn(LABEL, 'mb-1 mt-[18px] flex items-center')}>
        Capabilities
        <span className="ml-2 text-caption font-normal text-muted-foreground">
          {access.capabilities.length} held · role {access.role}
        </span>
      </div>
      {catalogFailed && (
        <ErrorNotice
          className="my-2"
          title="Couldn't load capability descriptions"
          onRetry={onRetryCatalog}
          retrying={catalogRetrying}
        >
          The codes below are still accurate; only their descriptions are missing.
        </ErrorNotice>
      )}
      <ul className="grid gap-x-[18px] gap-y-0.5 sm:grid-cols-2">
        {access.capabilities.map((code) => (
          <CapabilityRow key={code} code={code} description={describe.get(code)} held />
        ))}
        {next &&
          adds.map((code) => (
            <CapabilityRow
              key={code}
              code={code}
              description={`Comes with ${next}.`}
              held={false}
            />
          ))}
      </ul>
      {next && adds.length > 0 && (
        <Link
          to="/account/requests/new?kind=role"
          className="mt-2 inline-block text-label font-medium text-primary-text hover:underline"
        >
          Request {next}
        </Link>
      )}

      <div className={cn(LABEL, 'mb-2 mt-[18px]')}>Groups</div>
      <GroupList groups={access.groups} />
    </section>
  );
}

function CapabilityRow({
  code,
  description,
  held,
}: {
  code: string;
  description: ReactNode;
  held: boolean;
}) {
  return (
    <li
      className={cn(
        'flex items-start gap-2.5 border-b border-border/50 py-2',
        !held && 'opacity-75',
      )}
    >
      <span
        aria-hidden
        className={cn(
          'mt-px grid h-[18px] w-[18px] shrink-0 place-items-center rounded-md text-[11px]',
          held ? 'bg-positive/15 text-positive' : 'bg-card-2 text-muted-2',
        )}
      >
        {held ? '✓' : '·'}
      </span>
      <div className="min-w-0">
        <span className="font-mono text-xs text-ink">{code}</span>
        {held ? null : <span className="sr-only"> (not held)</span>}
        {description && <div className="text-[12.5px] text-muted-foreground">{description}</div>}
      </div>
    </li>
  );
}
