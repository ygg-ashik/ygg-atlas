// src/ui/morph.tsx
import type * as React from 'react';
import { motion, useReducedMotion } from 'motion/react';
import { springDefault, withReducedMotion } from './motion';

const HIDDEN = { opacity: 0, scale: 0.5, filter: 'blur(3px)' };
const SHOWN = { opacity: 1, scale: 1, filter: 'blur(0px)' };

export interface MorphProps {
  /** false shows `from`, true shows `to`. */
  done: boolean;
  from: React.ReactNode;
  to: React.ReactNode;
}

/** In-place completion morph ("Copy" → "✓ Copied", "Apply" → "✓ Applied"):
 * both labels share one grid cell so the control never changes size. With
 * reduced motion it is a plain cross-fade (no scale, no blur). */
export function Morph({ done, from, to }: MorphProps) {
  const reduced = useReducedMotion();
  const transition = withReducedMotion(springDefault, reduced);
  const hidden = reduced ? { opacity: 0 } : HIDDEN;
  const shown = reduced ? { opacity: 1 } : SHOWN;
  return (
    <span data-morph={done ? 'done' : 'idle'} className="relative inline-grid place-items-center">
      <motion.span
        data-morph-part="from"
        aria-hidden={done}
        className="[grid-area:1/1]"
        initial={false}
        animate={done ? hidden : shown}
        transition={transition}
      >
        {from}
      </motion.span>
      <motion.span
        data-morph-part="to"
        aria-hidden={!done}
        className="[grid-area:1/1]"
        initial={false}
        animate={done ? shown : hidden}
        transition={transition}
      >
        {to}
      </motion.span>
    </span>
  );
}
