import { renderHook } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { useStickToBottom } from './use-stick-to-bottom';

function scroller(scrollTop: number, scrollHeight = 2000, clientHeight = 600) {
  const el = document.createElement('div');
  Object.defineProperty(el, 'scrollHeight', { configurable: true, get: () => scrollHeight });
  Object.defineProperty(el, 'clientHeight', { configurable: true, get: () => clientHeight });
  el.scrollTop = scrollTop;
  return el;
}

describe('useStickToBottom', () => {
  it('follows new content while the reader is near the bottom', () => {
    const el = scroller(1300); // 100px from bottom
    const ref = { current: el };
    const { rerender } = renderHook(({ dep }) => useStickToBottom(ref, [dep]), {
      initialProps: { dep: 1 },
    });
    el.dispatchEvent(new Event('scroll'));
    rerender({ dep: 2 });
    expect(el.scrollTop).toBe(2000);
  });

  it('does not yank the reader who scrolled up', () => {
    const el = scroller(200); // far from bottom
    const ref = { current: el };
    const { rerender } = renderHook(({ dep }) => useStickToBottom(ref, [dep]), {
      initialProps: { dep: 1 },
    });
    el.dispatchEvent(new Event('scroll'));
    rerender({ dep: 2 });
    expect(el.scrollTop).toBe(200);
  });
});
