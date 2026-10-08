// src/ui/motion.ts
// Shared motion vocabulary (DESIGN.md › Motion). Components import these
// presets instead of inventing durations or easings.
import type { Transition } from 'motion/react';

export const EASE_OUT = [0.22, 1, 0.36, 1] as const;
export const EASE_SHEET = [0.32, 0.72, 0, 1] as const;

/** All interactive motion: critically damped, interruptible. */
export const springDefault: Transition = { type: 'spring', bounce: 0, duration: 0.35 };

/** Only after a physical flick/drag carried momentum. */
export const springMomentum: Transition = { type: 'spring', bounce: 0.2, duration: 0.4 };

export const durations = { press: 0.1, micro: 0.2, standard: 0.4, panel: 0.6 } as const;

/** Glass surfaces arrive as a material: opacity + scale + blur together. */
export const materialize = {
  initial: { opacity: 0, scale: 0.94, filter: 'blur(6px)' },
  animate: { opacity: 1, scale: 1, filter: 'blur(0px)' },
  exit: { opacity: 0, scale: 0.96, filter: 'blur(6px)' },
} as const;

/** prefers-reduced-motion: swap any movement for a short cross-fade. */
export function withReducedMotion(transition: Transition, reduced: boolean | null): Transition {
  return reduced ? { duration: 0.15, ease: 'linear' } : transition;
}
