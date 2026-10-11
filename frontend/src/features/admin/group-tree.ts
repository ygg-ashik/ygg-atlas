// Flat `GroupOut[]` → the group tree. Pure and cycle-safe: the backend refuses
// cycles, but the view must never hang or drop a group if one slips through.
import { type Group } from '@/api/admin-groups';

export interface GroupTreeNode {
  group: Group;
  children: GroupTreeNode[];
}

const byName = (a: Group, b: Group) => a.name.localeCompare(b.name);

/** True when `id`'s parent chain reaches a root without looping or a missing parent. */
function anchored(id: string, byId: ReadonlyMap<string, Group>): boolean {
  const seen = new Set<string>();
  let current = byId.get(id);
  while (current?.parent_id) {
    if (seen.has(current.id)) return false;
    seen.add(current.id);
    const parent = byId.get(current.parent_id);
    if (!parent) return false;
    current = parent;
  }
  return true;
}

/** Roots first, children nested, siblings by name. A group with a missing
 * parent, or caught in a cycle, becomes a root, so every group appears once. */
export function buildGroupTree(groups: readonly Group[]): GroupTreeNode[] {
  const byId = new Map(groups.map((x) => [x.id, x]));
  const isRoot = (x: Group) => !x.parent_id || !byId.has(x.parent_id) || !anchored(x.id, byId);
  const children = new Map<string, Group[]>();
  for (const x of groups) {
    if (isRoot(x) || !x.parent_id) continue;
    children.set(x.parent_id, [...(children.get(x.parent_id) ?? []), x]);
  }
  const build = (x: Group): GroupTreeNode => ({
    group: x,
    children: [...(children.get(x.id) ?? [])].sort(byName).map(build),
  });
  return groups.filter(isRoot).sort(byName).map(build);
}

/** `id` and all its descendants (cycle-safe). */
export function subtreeIds(groups: readonly Group[], id: string): string[] {
  const out: string[] = [];
  const queue = [id];
  while (queue.length) {
    const next = queue.shift() as string;
    if (out.includes(next)) continue;
    out.push(next);
    queue.push(...groups.filter((x) => x.parent_id === next).map((x) => x.id));
  }
  return out;
}
