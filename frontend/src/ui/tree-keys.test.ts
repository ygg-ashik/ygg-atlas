// src/ui/tree-keys.test.ts
import { describe, expect, it } from 'vitest';
import { type FlatNode, treeMove } from './tree-keys';

const V: FlatNode[] = [
  { id: 'a', parentId: null, hasChildren: true },
  { id: 'a1', parentId: 'a', hasChildren: false },
  { id: 'b', parentId: null, hasChildren: false },
];
const open = () => true;
const shut = () => false;

describe('treeMove', () => {
  it('moves vertically and to the ends', () => {
    expect(treeMove('ArrowDown', 0, V, open)).toEqual({ focus: 'a1' });
    expect(treeMove('ArrowUp', 1, V, open)).toEqual({ focus: 'a' });
    expect(treeMove('ArrowUp', 0, V, open)).toBeNull();
    expect(treeMove('ArrowDown', 2, V, open)).toBeNull();
    expect(treeMove('Home', 2, V, open)).toEqual({ focus: 'a' });
    expect(treeMove('End', 0, V, open)).toEqual({ focus: 'b' });
  });

  it('Right expands a closed parent, then enters it', () => {
    expect(treeMove('ArrowRight', 0, V, shut)).toEqual({ toggle: 'a' });
    expect(treeMove('ArrowRight', 0, V, open)).toEqual({ focus: 'a1' });
    expect(treeMove('ArrowRight', 2, V, open)).toBeNull();
  });

  it('Left collapses an open parent, else goes to the parent', () => {
    expect(treeMove('ArrowLeft', 0, V, open)).toEqual({ toggle: 'a' });
    expect(treeMove('ArrowLeft', 1, V, open)).toEqual({ focus: 'a' });
    expect(treeMove('ArrowLeft', 2, V, open)).toBeNull();
  });

  it('Enter and Space activate; other keys do nothing', () => {
    expect(treeMove('Enter', 1, V, open)).toEqual({ activate: 'a1' });
    expect(treeMove(' ', 1, V, open)).toEqual({ activate: 'a1' });
    expect(treeMove('x', 1, V, open)).toBeNull();
    expect(treeMove('ArrowDown', 9, V, open)).toBeNull();
  });
});
