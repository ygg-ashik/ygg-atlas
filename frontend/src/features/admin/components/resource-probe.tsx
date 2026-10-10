import { useState } from 'react';
import { type RowScope } from '@/api/admin-groups';
import { type EffectiveAccess, type Rule } from '@/api/admin-users';
import { useEffectiveAccess } from '@/api/hooks/use-admin-users';
import { FieldError, Input, Tag } from '@/ui';
import { EffectPill } from './effect-pill';
import { isResourcePath } from '../grant-rules';
import { useDebouncedValue } from '../hooks/use-debounced-value';
import { scopeText } from '../review-lines';
import { CARD } from './surfaces';

/** The rule the backend's reason names (`… by grant <id> (<origin>)`), if any. */
function decidingRule(access: EffectiveAccess): Rule | null {
  const reason = access.decision?.reason ?? '';
  return [...access.deny, ...access.allow].find((r) => reason.includes(r.grant_id)) ?? null;
}

/** `decision.row_scope`: null = all rows, [] = no rows, else alternatives ORed. */
function RowsLine({ scope }: { scope: RowScope[] | null }) {
  let text: string;
  if (scope === null) text = 'all rows';
  else if (scope.length === 0) text = 'no rows';
  else text = scope.map(scopeText).join('  or  ');
  return (
    <p className="mt-2 flex flex-wrap items-baseline gap-2 text-caption text-muted-foreground">
      Rows
      <span className="font-mono text-xs text-ink">{text}</span>
    </p>
  );
}

function ProbeResult({ access, firstName }: { access: EffectiveAccess; firstName: string }) {
  const { decision } = access;
  if (!decision) return null;
  const rule = decidingRule(access);
  return (
    <div role="status" aria-label="Probe result" className="mt-3">
      <div className="flex flex-wrap items-center gap-2.5">
        <EffectPill effect={decision.allowed ? 'allow' : 'deny'} />
        <span className="font-mono text-xs text-ink">{decision.reason}</span>
      </div>
      {decision.allowed && <RowsLine scope={decision.row_scope} />}
      {rule ? (
        <div className="mt-2.5 flex flex-wrap items-center gap-2 rounded-md bg-card-2 px-3 py-2">
          <span className="font-mono text-[12.5px] text-ink">{rule.pattern}</span>
          <span className="text-caption text-muted-foreground">deciding grant {rule.grant_id}</span>
          {rule.row_scope && <Tag mono>{scopeText(rule.row_scope)}</Tag>}
          <Tag mono className="ml-auto">
            {rule.origin}
          </Tag>
        </div>
      ) : (
        <p className="mt-2 text-caption text-muted-foreground">
          {access.active
            ? `No allow matches, so it's denied. Grant it to a group ${firstName} is in, or approve a request.`
            : 'This user is disabled, so every check is denied.'}
        </p>
      )}
    </div>
  );
}

/** Probe one resource path for the target user; the backend decides, this shows it. */
export function ResourceProbe({ userId, firstName }: { userId: string; firstName: string }) {
  const [path, setPath] = useState('');
  const settled = useDebouncedValue(path.trim());
  const valid = isResourcePath(settled);
  const access = useEffectiveAccess(userId, valid ? settled : null);
  const showInvalid = settled !== '' && !valid;
  return (
    <div className={`${CARD} px-5 py-4`}>
      <label htmlFor="probe-path" className="mb-2 block text-label font-medium text-ink">
        Probe a resource
      </label>
      <Input
        id="probe-path"
        aria-label="Resource path"
        className="font-mono"
        spellCheck={false}
        placeholder="demo/order/revenue"
        value={path}
        onChange={(e) => setPath(e.target.value)}
        aria-invalid={showInvalid || undefined}
      />
      {showInvalid && (
        <div className="mt-2">
          <FieldError>
            Enter a resource path like <span className="font-mono">demo/order/revenue</span>
          </FieldError>
        </div>
      )}
      {valid && access.data?.decision?.resource === settled && (
        <ProbeResult access={access.data} firstName={firstName} />
      )}
    </div>
  );
}
