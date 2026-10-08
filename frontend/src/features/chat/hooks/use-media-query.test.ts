import { act, renderHook } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { useMediaQuery } from './use-media-query';

afterEach(() => vi.unstubAllGlobals());

describe('useMediaQuery', () => {
  it('falls back when matchMedia is unavailable', () => {
    vi.stubGlobal('matchMedia', undefined);
    expect(renderHook(() => useMediaQuery('(min-width: 1200px)', true)).result.current).toBe(true);
  });

  it('tracks the query as it changes', () => {
    let listener: (() => void) | null = null;
    const mql = {
      matches: false,
      addEventListener: (_: string, cb: () => void) => (listener = cb),
      removeEventListener: vi.fn(),
    };
    vi.stubGlobal('matchMedia', () => mql);
    const { result } = renderHook(() => useMediaQuery('(min-width: 1200px)', true));
    expect(result.current).toBe(false);
    mql.matches = true;
    act(() => listener?.());
    expect(result.current).toBe(true);
  });
});
