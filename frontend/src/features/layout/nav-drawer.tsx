// src/features/layout/nav-drawer.tsx
import { useEffect, useState } from 'react';
import { useLocation } from 'react-router-dom';
import { AnimatePresence, motion, useReducedMotion } from 'motion/react';
import { Menu } from 'lucide-react';
import {
  Dialog,
  DialogBareContent,
  DialogBareOverlay,
  DialogPortal,
  DialogTitle,
  DialogTrigger,
  springDefault,
  withReducedMotion,
} from '@/ui';
import { SidebarContent, type SidebarContentProps } from './sidebar-content';

// Same path in and out (DESIGN.md › Motion rule 3): slides in from the left and
// leaves to the left. Reduced motion swaps the slide for a short cross-fade.
const SLIDE = { hidden: { x: '-110%', opacity: 1 }, shown: { x: 0, opacity: 1 } };
const FADE = { hidden: { x: 0, opacity: 0 }, shown: { x: 0, opacity: 1 } };
/** Mirrors the `max-[999px]` breakpoint that hides the docked sidebar. */
const DOCKED_QUERY = '(min-width: 1000px)';

/** Below 1000px the docked sidebar is hidden; this compact glass button opens
 * the same sidebar content as a left drawer. Closes on Esc, scrim or navigation. */
export function NavDrawer(props: SidebarContentProps) {
  const [open, setOpen] = useState(false);
  const reduced = useReducedMotion();
  const { key } = useLocation();
  const transition = withReducedMotion(springDefault, reduced);
  const panel = reduced ? FADE : SLIDE;

  // Any navigation (nav link, thread, "New chat") dismisses the drawer.
  useEffect(() => setOpen(false), [key]);

  // Growing past the breakpoint docks the sidebar again, so drop the drawer.
  useEffect(() => {
    const docked = window.matchMedia(DOCKED_QUERY);
    const onChange = (e: MediaQueryListEvent) => {
      if (e.matches) setOpen(false);
    };
    docked.addEventListener('change', onChange);
    return () => docked.removeEventListener('change', onChange);
  }, []);

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <button
          type="button"
          aria-label="Open navigation"
          className="glass fixed left-[30px] top-[28px] z-30 grid h-9 w-9 place-items-center rounded-full text-ink transition-transform duration-100 ease-out active:scale-[.96] min-[1000px]:hidden"
        >
          <Menu aria-hidden className="h-4 w-4" />
        </button>
      </DialogTrigger>
      <AnimatePresence>
        {open && (
          <DialogPortal forceMount>
            <DialogBareOverlay asChild forceMount>
              <motion.div
                className="fixed inset-0 z-40 bg-black/20"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                transition={transition}
              />
            </DialogBareOverlay>
            <DialogBareContent asChild forceMount aria-describedby={undefined}>
              <motion.div
                className="glass glass-heavy fixed inset-y-2.5 left-2.5 z-50 flex w-[min(280px,calc(100vw-40px))] flex-col rounded-shell px-2.5 py-3.5 focus:outline-none"
                variants={panel}
                initial="hidden"
                animate="shown"
                exit="hidden"
                transition={transition}
              >
                <DialogTitle className="sr-only">Navigation</DialogTitle>
                <SidebarContent {...props} />
              </motion.div>
            </DialogBareContent>
          </DialogPortal>
        )}
      </AnimatePresence>
    </Dialog>
  );
}
