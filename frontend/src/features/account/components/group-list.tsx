import { type GroupRef } from '@/api/access';
import { StandingPill } from '@/ui';

/** The caller's groups as mono chips with their standing (member or manager). */
export function GroupList({ groups }: { groups: readonly GroupRef[] }) {
  if (!groups.length) {
    return (
      <p className="text-[13.5px] text-muted-foreground">
        None yet. Groups decide what data you can see.
      </p>
    );
  }
  return (
    <ul aria-label="Groups" className="flex flex-wrap gap-2">
      {groups.map((g) => (
        <li
          key={g.id}
          className="inline-flex items-center gap-2 rounded-full border border-border/50 bg-card-2 py-1 pl-2.5 pr-1.5 text-[12.5px] text-ink"
        >
          <span className="font-mono text-xs">{g.name}</span>
          <StandingPill standing={g.standing} />
        </li>
      ))}
    </ul>
  );
}
