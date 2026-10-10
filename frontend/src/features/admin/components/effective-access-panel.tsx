import { type EffectiveAccess, type User } from '@/api/admin-users';
import { useEffectiveAccess } from '@/api/hooks/use-admin-users';
import { useCapabilityCatalog } from '@/api/hooks/use-capability-catalog';
import { Notice, Tag } from '@/ui';
import { CatalogDecisions } from './catalog-decisions';
import { ResourceProbe } from './resource-probe';
import { CARD } from './surfaces';

/** "Omar Khalil" → "Omar"; no display name → the email's local part. */
const firstNameOf = (u: User) =>
  u.display_name.trim().split(/\s+/)[0] || (u.email.split('@')[0] ?? u.email);

/** Where a held capability comes from: the role's bundle (per `/meta/capabilities`),
 * else a direct user grant; unknown while the catalog is loading. */
function useCapabilitySource(role: string | undefined) {
  const roles = useCapabilityCatalog().data?.roles;
  return (capability: string): string | null => {
    if (!roles || !role) return null;
    const bundle = roles.find((r) => r.name === role)?.capabilities ?? [];
    return bundle.includes(capability) ? `from role ${role}` : 'from a direct grant';
  };
}

function Capabilities({ userId }: { userId: string }) {
  const access = useEffectiveAccess(userId).data;
  const sourceOf = useCapabilitySource(access?.role);
  return (
    <div className={`${CARD} self-start px-5 py-4`}>
      <p className="mb-1.5 text-label font-medium text-ink">Capabilities</p>
      <ul className="grid gap-2">
        {(access?.capabilities ?? []).map((c) => (
          <li key={c} className="flex items-start gap-2.5">
            <span aria-hidden className="text-positive">
              ✓
            </span>
            <div>
              <span className="font-mono text-[12.5px] text-ink">{c}</span>
              {sourceOf(c) && (
                <div className="text-caption text-muted-foreground">{sourceOf(c)}</div>
              )}
            </div>
          </li>
        ))}
      </ul>
      <p className="mt-2.5 text-caption text-muted-foreground">
        Groups never grant capabilities; only the role and user overrides do.
      </p>
      {access && <Clearances codes={access.clearances} />}
    </div>
  );
}

/** Field clearances: which masked label classes this user sees in clear. */
function Clearances({ codes }: { codes: readonly string[] }) {
  return (
    <div className="mt-3.5 border-t border-border/60 pt-3">
      <p className="mb-1.5 text-label font-medium text-ink">Clearances</p>
      {codes.length ? (
        <div className="flex flex-wrap gap-1.5">
          {codes.map((c) => (
            <Tag key={c} mono>
              {c}
            </Tag>
          ))}
        </div>
      ) : (
        <p className="text-caption text-muted-foreground">None: masked labels show masked.</p>
      )}
    </div>
  );
}

/** Grants the evaluator ignored (fail closed), e.g. a `$self` scope with no attribute. */
function SkippedGrants({ access }: { access: EffectiveAccess | undefined }) {
  if (!access?.skipped.length) return null;
  return (
    <Notice role="status" icon="!" title="Some grants don't apply">
      <ul className="mt-1 grid gap-1">
        {access.skipped.map((r) => (
          <li key={r.grant_id} className="flex flex-wrap items-baseline gap-2">
            <span className="font-mono text-xs text-ink">{r.pattern}</span>
            <span className="text-caption">{r.reason}</span>
            <Tag mono>{r.origin}</Tag>
          </li>
        ))}
      </ul>
    </Notice>
  );
}

/** Screen 8: what the target user can see and do, as the evaluator decides it. */
export function EffectiveAccessPanel({ user }: { user: User }) {
  const firstName = firstNameOf(user);
  const access = useEffectiveAccess(user.id).data;
  return (
    <div className="grid gap-3">
      <SkippedGrants access={access} />
      <ResourceProbe userId={user.id} firstName={firstName} />
      <div className="grid gap-3 min-[900px]:grid-cols-[1.6fr_1fr]">
        <CatalogDecisions userId={user.id} firstName={firstName} />
        <Capabilities userId={user.id} />
      </div>
    </div>
  );
}
