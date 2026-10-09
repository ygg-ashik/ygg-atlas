import { describe, expect, it } from 'vitest';
import { type Group } from '@/api/admin-groups';
import { buildGroupTree, subtreeIds } from './group-tree';

const g = (id: string, parent: string | null = null, name = id): Group => ({
  id,
  name,
  description: '',
  parent_id: parent,
  created_at: '2026-09-23T00:00:00Z',
});

const shape = (nodes: ReturnType<typeof buildGroupTree>): unknown =>
  nodes.map((n) => [n.group.id, shape(n.children)]);

describe('buildGroupTree', () => {
  it('nests children under parents, sorted by name', () => {
    const tree = buildGroupTree([
      g('mp', 'm', 'marketing-paid'),
      g('m', null, 'marketing'),
      g('a', null, 'atlas-admins'),
    ]);
    expect(shape(tree)).toEqual([
      ['a', []],
      ['m', [['mp', []]]],
    ]);
  });

  it('treats a group whose parent is missing as a root', () => {
    expect(shape(buildGroupTree([g('x', 'gone')]))).toEqual([['x', []]]);
  });

  it('is cycle-safe: every group appears exactly once', () => {
    const tree = buildGroupTree([g('a', 'b'), g('b', 'a'), g('c', 'a')]);
    const ids: string[] = [];
    const walk = (nodes: typeof tree) =>
      nodes.forEach((n) => {
        ids.push(n.group.id);
        walk(n.children);
      });
    walk(tree);
    expect(ids.sort()).toEqual(['a', 'b', 'c']);
  });

  it('handles an empty list', () => {
    expect(buildGroupTree([])).toEqual([]);
  });
});

describe('subtreeIds', () => {
  it('lists the group and every descendant', () => {
    const groups = [g('m'), g('mp', 'm'), g('mps', 'mp'), g('c')];
    expect(subtreeIds(groups, 'm')).toEqual(['m', 'mp', 'mps']);
    expect(subtreeIds(groups, 'c')).toEqual(['c']);
  });

  it('terminates on a cycle', () => {
    expect(subtreeIds([g('a', 'b'), g('b', 'a')], 'a').sort()).toEqual(['a', 'b']);
  });
});
