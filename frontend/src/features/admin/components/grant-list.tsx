import { type GrantOut } from '@/api/admin-groups';
import { Button } from '@/ui';
import { EffectPill } from './effect-pill';
import { isoDate } from '../format';
import { INSET_LIST } from './surfaces';

interface GrantListProps {
  grants: readonly GrantOut[];
  label: string;
  /** Present only when the viewer may revoke (admin:groups / admin:users). */
  onRevoke?: (grant: GrantOut) => void;
}

/** Access rules as inset rows: effect, mono pattern, reason, expiry and id. */
export function GrantList({ grants, label, onRevoke }: GrantListProps) {
  if (!grants.length) return null;
  return (
    <ul aria-label={label} className={`${INSET_LIST}`}>
      {grants.map((g) => (
        <li
          key={g.id}
          aria-label={`${g.effect} ${g.target}`}
          className="flex min-h-[52px] items-center gap-3 border-b border-border/50 px-4 py-2.5 last:border-b-0"
        >
          <EffectPill effect={g.effect} />
          <div className="min-w-0 flex-1">
            <div className="font-mono text-[12.5px] text-ink">{g.target}</div>
            <div className="text-[12.5px] text-muted-foreground">
              {g.reason || 'No reason'}
              {g.expires_at && ` · until ${isoDate(g.expires_at)}`} ·{' '}
              <span className="font-mono">{g.id.slice(0, 8)}</span>
            </div>
          </div>
          {onRevoke && (
            <Button
              variant="pill"
              size="sm"
              aria-label={`Revoke ${g.effect} ${g.target}`}
              onClick={() => onRevoke(g)}
            >
              Revoke
            </Button>
          )}
        </li>
      ))}
    </ul>
  );
}
