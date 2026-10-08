import { useEffect, useRef, type DependencyList, type RefObject } from 'react';

const NEAR_BOTTOM_PX = 240;

/** DESIGN.md › Streaming: auto-scroll only while the reader is within 240px of
 * the bottom; scrolling up pauses it. `deps` is what grows the content. */
export function useStickToBottom(ref: RefObject<HTMLElement | null>, deps: DependencyList) {
  const nearBottom = useRef(true);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const onScroll = () => {
      nearBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < NEAR_BOTTOM_PX;
    };
    onScroll(); // measure where the reader starts, not just after they scroll
    el.addEventListener('scroll', onScroll, { passive: true });
    return () => el.removeEventListener('scroll', onScroll);
  }, [ref]);

  useEffect(() => {
    const el = ref.current;
    if (el && nearBottom.current) el.scrollTop = el.scrollHeight;
    // eslint-disable-next-line react-hooks/exhaustive-deps -- deps is the caller's content-growth list
  }, deps);
}
