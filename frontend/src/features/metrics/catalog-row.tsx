// src/features/metrics/catalog-row.tsx
import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { AnimatePresence, motion, useReducedMotion } from 'motion/react';
import { ChevronRight } from 'lucide-react';
import { cn, springDefault, withReducedMotion } from '@/ui';

export interface CatalogRowProps {
  /** DOM id used for `#metric-<id>` deep links. */
  anchor: string;
  name: string;
  id: string;
  description: string;
  meta: string;
  ask: string;
  /** True when the URL hash names this row: it opens and scrolls into view. */
  targeted: boolean;
}

/** One inset-list row (DESIGN.md › inset-list): name + mono id, expands on a spring. */
export function CatalogRow({
  anchor,
  name,
  id,
  description,
  meta,
  ask,
  targeted,
}: CatalogRowProps) {
  const [open, setOpen] = useState(targeted);
  const ref = useRef<HTMLLIElement>(null);
  const reduced = useReducedMotion();

  // Follow hash changes while mounted (e.g. ⌘K jumps to another metric on this page).
  useEffect(() => {
    if (!targeted) return;
    setOpen(true);
    ref.current?.scrollIntoView({ block: 'center' });
  }, [targeted]);

  return (
    <li id={anchor} ref={ref} className="border-b border-border/60 last:border-0">
      <button
        type="button"
        aria-expanded={open}
        aria-controls={`${anchor}-detail`}
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center gap-2.5 px-4 py-3 text-left transition-colors duration-200 hover:bg-foreground/[0.03]"
      >
        <span className="text-[14.5px] font-medium text-ink">{name}</span>
        <span className="font-mono text-[11px] text-muted-2">{id}</span>
        <ChevronRight
          aria-hidden
          className={cn(
            'ml-auto h-4 w-4 text-muted-2 transition-transform duration-300 ease-out',
            open && 'rotate-90',
          )}
        />
      </button>
      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            id={`${anchor}-detail`}
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={withReducedMotion(springDefault, reduced)}
            className="overflow-hidden"
          >
            <div className="space-y-2 px-4 pb-3.5 text-label text-body">
              <p>{description || 'No description yet.'}</p>
              <p className="text-caption text-muted-foreground">{meta}</p>
              <Link
                to={ask}
                className="inline-block text-label font-medium text-primary-text hover:underline"
              >
                Ask about this →
              </Link>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </li>
  );
}
