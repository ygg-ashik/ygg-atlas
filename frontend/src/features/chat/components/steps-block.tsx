import { useState } from 'react';
import { AnimatePresence, motion, useReducedMotion } from 'motion/react';
import { Check, ChevronRight } from 'lucide-react';
import { cn, springDefault, withReducedMotion } from '@/ui';
import { stepLabel, type Step } from '../steps';

interface StepsBlockProps {
  steps: Step[];
  /** Turn still in progress: list stays open, header shimmers. */
  live?: boolean;
  /** Known duration for the just-finished turn ("Worked for Ns"). */
  durationMs?: number;
}

const plural = (n: number) => `${n} step${n === 1 ? '' : 's'}`;

function stepsTitle(count: number, live: boolean, durationMs?: number): string {
  if (live) return `Working · ${plural(count)}`;
  if (durationMs !== undefined) {
    return `Worked for ${Math.max(1, Math.round(durationMs / 1000))}s · ${plural(count)}`;
  }
  return `Used ${count} atlas ${count === 1 ? 'step' : 'steps'}`;
}

const SHIMMER =
  'animate-shimmer bg-[linear-gradient(90deg,hsl(var(--muted-foreground))_0%,hsl(var(--ink))_45%,hsl(var(--muted-foreground))_60%)] bg-[length:200%_100%] bg-clip-text text-transparent';

function StepRow({ step }: { step: Step }) {
  const done = step.status === 'done';
  return (
    <li className="flex items-center gap-2.5 pt-1.5 text-label">
      {done ? (
        <span className="grid h-[15px] w-[15px] shrink-0 place-items-center rounded-[5px] bg-positive text-white">
          <Check className="h-2.5 w-2.5" />
        </span>
      ) : (
        <span className="h-[15px] w-[15px] shrink-0 animate-spin rounded-full border-[1.5px] border-primary border-t-transparent" />
      )}
      <span className={done ? 'text-body' : 'text-muted-foreground'}>{stepLabel(step.tool)}</span>
      <span className="ml-auto font-mono text-[11px] text-muted-2">{step.tool}</span>
    </li>
  );
}

/** Codex live plan → Claude "Worked for Ns" collapse (DESIGN.md › plan-block). */
export function StepsBlock({ steps, live = false, durationMs }: StepsBlockProps) {
  const [open, setOpen] = useState(false);
  const reduced = useReducedMotion();
  if (steps.length === 0) return null;

  const expanded = live || open;

  return (
    <div className="mb-3.5 rounded-lg bg-card px-3.5 py-3 shadow-[0_0_0_1px_hsl(var(--border)/0.6)]">
      <button
        type="button"
        aria-expanded={expanded}
        disabled={live}
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center gap-2 text-label text-muted-foreground"
      >
        <ChevronRight
          className={cn(
            'h-3.5 w-3.5 transition-transform duration-300 ease-out',
            expanded && 'rotate-90',
          )}
        />
        <span className={cn(live && SHIMMER)}>{stepsTitle(steps.length, live, durationMs)}</span>
      </button>
      <AnimatePresence initial={false}>
        {expanded && (
          <motion.ol
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={withReducedMotion(springDefault, reduced)}
            className="overflow-hidden"
          >
            {steps.map((s, i) => (
              <StepRow key={`${s.tool}-${i}`} step={s} />
            ))}
          </motion.ol>
        )}
      </AnimatePresence>
    </div>
  );
}
