import type { ReactNode } from 'react';
import { useReducedMotion } from 'motion/react';
import { Streamdown, type AnimateOptions, type Components } from 'streamdown';

interface MarkdownMessageProps {
  text: string;
  /** True while tokens are still arriving. Enables incomplete-markdown repair,
   * word blur-in (DESIGN.md › Streaming) and the caret. */
  streaming?: boolean;
}

// DESIGN.md › Streaming: word chunks fade in from blur(3px) over 420ms. The
// animate plugin staggers words 40ms apart and caps the backlog at 320ms, which
// is the adaptive pacing (bursty network chunks flow out evenly).
const STREAM_ANIMATION: AnimateOptions = {
  animation: 'blurIn',
  sep: 'word',
  duration: 420,
  stagger: 40,
  maxBacklogMs: 320,
  easing: 'cubic-bezier(.22,1,.36,1)',
};

const PROSE =
  'min-w-0 text-answer text-body [&_h1]:mb-2.5 [&_h1]:mt-1.5 [&_h1]:font-serif [&_h1]:text-title [&_h1]:font-normal [&_h1]:text-ink [&_h2]:mb-2.5 [&_h2]:mt-1.5 [&_h2]:font-serif [&_h2]:text-title [&_h2]:font-normal [&_h2]:text-ink [&_h3]:mb-1.5 [&_h3]:mt-3 [&_h3]:font-serif [&_h3]:text-section [&_h3]:font-normal [&_h3]:text-ink [&_li]:my-0.5 [&_ol]:my-2 [&_ol]:list-decimal [&_ol]:pl-5 [&_p]:mb-3 [&_strong]:font-semibold [&_strong]:text-ink [&_table]:tabular [&_td]:border-b [&_td]:px-2 [&_td]:py-1.5 [&_th]:border-b [&_th]:px-2 [&_th]:py-1.5 [&_th]:text-left [&_th]:text-label [&_th]:font-medium [&_th]:text-muted-foreground [&_ul]:my-2 [&_ul]:list-disc [&_ul]:pl-5';

/** Only http(s) links render as anchors (new tab); anything else is plain text. */
function SafeLink({ href, children }: { href?: string; children?: ReactNode }) {
  if (href && /^https?:\/\//.test(href)) {
    return (
      <a
        href={href}
        target="_blank"
        rel="noopener noreferrer"
        className="text-primary-text underline underline-offset-2"
      >
        {children}
      </a>
    );
  }
  return <span>{children}</span>;
}

/** Wide tables scroll horizontally inside a solid card (never on glass). */
function ScrollTable({ children }: { children?: ReactNode }) {
  return (
    <div className="my-3 max-w-full overflow-x-auto rounded-lg bg-card shadow-[0_0_0_1px_hsl(var(--border)/0.6)]">
      <table className="w-max min-w-full">{children}</table>
    </div>
  );
}

const COMPONENTS: Components = {
  a: ({ href, children }) => <SafeLink href={href}>{children}</SafeLink>,
  table: ({ children }) => <ScrollTable>{children}</ScrollTable>,
};

/** Assistant prose: GFM, no raw HTML, safe links. Text already on screen never re-animates. */
export function MarkdownMessage({ text, streaming = false }: MarkdownMessageProps) {
  const reduced = useReducedMotion();
  return (
    <Streamdown
      mode={streaming ? 'streaming' : 'static'}
      isAnimating={streaming}
      parseIncompleteMarkdown
      animated={streaming && !reduced ? STREAM_ANIMATION : false}
      caret={streaming ? 'circle' : undefined}
      controls={{ table: false, code: { copy: true } }}
      className={PROSE}
      components={COMPONENTS}
    >
      {text}
    </Streamdown>
  );
}
