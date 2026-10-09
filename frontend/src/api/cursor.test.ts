import { describe, expect, it } from 'vitest';
import { mergePages, nextCursor, type Page } from './cursor';

interface Row {
  id: string;
  n: number;
}

const page = (ids: number[], next: string | null): Page<Row> => ({
  items: ids.map((n) => ({ id: `r${n}`, n })),
  next_cursor: next,
});

describe('nextCursor', () => {
  it('returns the cursor, or undefined on the last page', () => {
    expect(nextCursor(page([1], 'abc'))).toBe('abc');
    expect(nextCursor(page([1], null))).toBeUndefined();
    expect(nextCursor({ items: [] })).toBeUndefined();
  });
});

describe('mergePages', () => {
  it('is empty before the first page arrives', () => {
    expect(mergePages<Row>(undefined)).toEqual([]);
  });

  it('concatenates pages in order', () => {
    const merged = mergePages({ pages: [page([1, 2], 'c1'), page([3, 4], 'c2'), page([5], null)] });
    expect(merged.map((r) => r.n)).toEqual([1, 2, 3, 4, 5]);
  });

  it('keeps the first copy of a row repeated across pages (refetch after inserts)', () => {
    const merged = mergePages({ pages: [page([1, 2], 'c1'), page([2, 3], null)] });
    expect(merged.map((r) => r.n)).toEqual([1, 2, 3]);
  });

  it('accepts a custom key for rows without an id', () => {
    const pages = {
      pages: [
        { items: [{ family_id: 'a' }, { family_id: 'b' }], next_cursor: 'x' },
        { items: [{ family_id: 'b' }], next_cursor: null },
      ],
    };
    expect(mergePages(pages, (r) => r.family_id)).toHaveLength(2);
  });
});
