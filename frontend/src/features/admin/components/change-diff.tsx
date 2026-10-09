import { type Change } from '@/api/audit';
import { DiffBlock, type DiffLine } from '@/ui';

type Snapshot = Record<string, unknown> | null;

/** Key column width: values line up like the review cards ("role      viewer"). */
const KEY_WIDTH = 9;

const show = (value: unknown): string => {
  if (value === null || value === undefined || value === '') return '—';
  return typeof value === 'string' ? value : JSON.stringify(value);
};

const line = (kind: DiffLine['kind'], key: string, value: unknown): DiffLine => ({
  kind,
  text: `${key.padEnd(KEY_WIDTH)} ${show(value)}`,
});

/** An `rbac_changes` row's before → after, key by key: unchanged keys are
 * context, a changed key is its old value removed and its new value added. */
export function diffLines(before: Snapshot, after: Snapshot): DiffLine[] {
  const was = before ?? {};
  const now = after ?? {};
  const lines: DiffLine[] = [];
  for (const [key, value] of Object.entries(was)) {
    if (!(key in now)) {
      lines.push(line('remove', key, value));
    } else if (JSON.stringify(value) === JSON.stringify(now[key])) {
      lines.push(line('context', key, value));
    } else {
      lines.push(line('remove', key, value), line('add', key, now[key]));
    }
  }
  for (const [key, value] of Object.entries(now)) {
    if (!(key in was)) lines.push(line('add', key, value));
  }
  return lines;
}

/** The expanded change row: the diff plus where the row came from. */
export function ChangeDiff({ change }: { change: Change }) {
  const lines = diffLines(change.before, change.after);
  return (
    <div className="grid gap-1.5">
      {lines.length ? (
        <DiffBlock lines={lines} />
      ) : (
        <p className="text-caption text-muted-foreground">No field values were recorded.</p>
      )}
      <p className="text-caption text-muted-foreground">
        rbac_changes · {change.object_type} <span className="font-mono">{change.object_id}</span> ·
        via {change.via}
      </p>
    </div>
  );
}
