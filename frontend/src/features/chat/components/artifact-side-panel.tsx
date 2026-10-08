import { AnimatePresence, motion, useReducedMotion } from 'motion/react';
import type { ArtifactBlock } from '@/api/chat';
import {
  Dialog,
  DialogBareContent,
  DialogBareOverlay,
  DialogPortal,
  DialogTitle,
  durations,
  EASE_SHEET,
  withReducedMotion,
} from '@/ui';
import { useMediaQuery } from '../hooks/use-media-query';
import { ArtifactPanel } from './artifact-panel';

/** At and above this width the panel docks beside the conversation. */
const DOCKED_QUERY = '(min-width: 1200px)';
const WIDTH = 'min(44vw, 540px)';
// Same path in and out (DESIGN.md › Motion): enters from the right, leaves to the right.
const SLIDE = { hidden: { x: '110%', opacity: 1 }, shown: { x: 0, opacity: 1 } };
const FADE = { hidden: { x: 0, opacity: 0 }, shown: { x: 0, opacity: 1 } };

interface ArtifactSidePanelProps {
  /** The open artifact, or null when the panel is closed. */
  artifact: ArtifactBlock | null;
  onClose: () => void;
}

/** The artifact panel: a docked column that springs open beside the chat on wide
 * screens, an overlay sheet with a scrim (Esc / scrim closes) below 1200px. */
export function ArtifactSidePanel({ artifact, onClose }: ArtifactSidePanelProps) {
  const docked = useMediaQuery(DOCKED_QUERY, true);
  const reduced = useReducedMotion();
  const transition = withReducedMotion({ duration: durations.panel, ease: EASE_SHEET }, reduced);

  if (docked) {
    return (
      <AnimatePresence initial={false}>
        {artifact && (
          <motion.aside
            key="artifact-panel"
            aria-label="Artifact"
            initial={{ width: 0, opacity: 0 }}
            animate={{ width: WIDTH, opacity: 1 }}
            exit={{ width: 0, opacity: 0 }}
            transition={transition}
            // z-20: full height beside the conversation, above the page toolbar (reference Mode ①).
            className="relative z-20 shrink-0 overflow-hidden py-2.5 pr-2.5"
          >
            <div className="h-full w-[min(44vw,540px)] min-w-[320px]">
              <ArtifactPanel artifact={artifact} onClose={onClose} />
            </div>
          </motion.aside>
        )}
      </AnimatePresence>
    );
  }

  return (
    <Dialog open={artifact !== null} onOpenChange={(open) => !open && onClose()}>
      <AnimatePresence>
        {artifact && (
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
                className="fixed inset-y-2.5 right-2.5 z-50 w-[min(540px,calc(100vw-20px))] focus:outline-none"
                variants={reduced ? FADE : SLIDE}
                initial="hidden"
                animate="shown"
                exit="hidden"
                transition={transition}
              >
                <DialogTitle className="sr-only">Artifact</DialogTitle>
                <ArtifactPanel artifact={artifact} onClose={onClose} />
              </motion.div>
            </DialogBareContent>
          </DialogPortal>
        )}
      </AnimatePresence>
    </Dialog>
  );
}
