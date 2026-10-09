// src/ui/roving.test.ts
import { describe, expect, it } from 'vitest';
import { moveIndex } from './roving';

describe('moveIndex (roving focus)', () => {
  const all = [true, true, true];
  it('moves forward and back with wrap-around', () => {
    expect(moveIndex('ArrowRight', 2, all)).toBe(0);
    expect(moveIndex('ArrowDown', 0, all)).toBe(1);
    expect(moveIndex('ArrowLeft', 0, all)).toBe(2);
    expect(moveIndex('ArrowUp', 1, all)).toBe(0);
  });

  it('skips disabled items and jumps to the ends', () => {
    const some = [false, true, false, true, false];
    expect(moveIndex('ArrowRight', 1, some)).toBe(3);
    expect(moveIndex('Home', 3, some)).toBe(1);
    expect(moveIndex('End', 1, some)).toBe(3);
  });

  it('ignores other keys and empty lists', () => {
    expect(moveIndex('a', 0, all)).toBeNull();
    expect(moveIndex('ArrowRight', 0, [])).toBeNull();
  });
});
