// src/ui/motion.test.ts
import { describe, expect, it } from 'vitest';
import { durations, materialize, springDefault, springMomentum, withReducedMotion } from './motion';

describe('motion presets (DESIGN.md › Motion)', () => {
  it('default spring is critically damped (no bounce)', () => {
    expect(springDefault).toMatchObject({ type: 'spring', bounce: 0, duration: 0.35 });
  });

  it('momentum spring has a small bounce', () => {
    expect(springMomentum).toMatchObject({ type: 'spring', bounce: 0.2 });
  });

  it('exposes the duration tokens in seconds', () => {
    expect(durations).toEqual({ press: 0.1, micro: 0.2, standard: 0.4, panel: 0.6 });
  });

  it('materialize animates opacity, scale and blur together', () => {
    expect(materialize.initial).toMatchObject({ opacity: 0, scale: 0.94, filter: 'blur(6px)' });
    expect(materialize.animate).toMatchObject({ opacity: 1, scale: 1, filter: 'blur(0px)' });
  });

  it('replaces any transition with a short cross-fade when motion is reduced', () => {
    expect(withReducedMotion(springDefault, true)).toEqual({ duration: 0.15, ease: 'linear' });
    expect(withReducedMotion(springDefault, false)).toBe(springDefault);
    expect(withReducedMotion(springDefault, null)).toBe(springDefault);
  });
});
