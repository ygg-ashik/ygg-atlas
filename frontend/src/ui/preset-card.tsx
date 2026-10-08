// src/ui/preset-card.tsx
import { cn } from './utils';

export type PresetPreview = 'line' | 'bars' | 'funnel';

interface PresetCardProps {
  title: string;
  description?: string;
  preview: PresetPreview;
  onSelect: () => void;
  compact?: boolean;
}

/** Preset gallery card (DESIGN.md › preset-card): lifts on hover and plays a
 * preview of what the analysis produces. Purely presentational. */
export function PresetCard({
  title,
  description,
  preview,
  onSelect,
  compact = false,
}: PresetCardProps) {
  return (
    <button
      type="button"
      onClick={onSelect}
      className="group overflow-hidden rounded-feature bg-card text-left shadow-[0_0_0_1px_hsl(var(--border)/0.6)] transition-[transform,box-shadow] duration-300 ease-out hover:-translate-y-[3px] hover:shadow-[0_0_0_1px_hsl(var(--border)),0_14px_34px_rgba(0,0,0,0.10)] active:scale-[.98] focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-primary/15"
    >
      <div className={cn('relative bg-card-2', compact ? 'h-20' : 'h-[108px]')}>
        <Preview kind={preview} />
      </div>
      <div className="px-3.5 pb-3.5 pt-3">
        <span className="block text-sm font-semibold text-ink">{title}</span>
        {description && (
          <span className="block text-caption text-muted-foreground">{description}</span>
        )}
      </div>
    </button>
  );
}

// Preview geometry in the 200x108 viewBox: bars are [x, y, height], funnel steps [y, width, opacity].
const BARS: readonly (readonly [number, number, number])[] = [
  [25, 40, 58],
  [65, 24, 74],
  [105, 54, 44],
  [145, 34, 64],
];
const FUNNEL: readonly (readonly [number, number, number])[] = [
  [20, 160, 0.85],
  [45, 118, 0.6],
  [70, 62, 0.4],
];

function Preview({ kind }: { kind: PresetPreview }) {
  const drawn =
    'transition-[stroke-dashoffset] [transition-duration:1100ms] ease-out [stroke-dasharray:420] [stroke-dashoffset:420] group-hover:[stroke-dashoffset:0]';
  if (kind === 'line') {
    return (
      <svg
        data-preview="line"
        viewBox="0 0 200 108"
        preserveAspectRatio="none"
        className="absolute inset-0 h-full w-full"
      >
        <path
          d="M10 88 C40 78,60 58,90 64 S140 28,190 22"
          fill="none"
          strokeWidth="2.2"
          strokeLinecap="round"
          className={cn('stroke-primary', drawn)}
        />
      </svg>
    );
  }
  if (kind === 'bars') {
    return (
      <svg data-preview="bars" viewBox="0 0 200 108" className="absolute inset-0 h-full w-full">
        {BARS.map(([x, y, h], i) => (
          <rect
            key={x}
            x={x}
            y={y}
            width="22"
            height={h}
            rx="5"
            style={{ transitionDelay: `${i * 50}ms` }}
            className="origin-bottom fill-primary/75 [transform-box:fill-box] [transform:scaleY(.25)] transition-transform duration-700 ease-out group-hover:[transform:scaleY(1)]"
          />
        ))}
      </svg>
    );
  }
  return (
    <svg data-preview="funnel" viewBox="0 0 200 108" className="absolute inset-0 h-full w-full">
      {FUNNEL.map(([y, w, o], i) => (
        <rect
          key={y}
          x="20"
          y={y}
          width={w}
          height="16"
          rx="5"
          style={{ opacity: o, transitionDelay: `${i * 60}ms` }}
          className="origin-left fill-primary [transform-box:fill-box] [transform:scaleX(.25)] transition-transform duration-700 ease-out group-hover:[transform:scaleX(1)]"
        />
      ))}
    </svg>
  );
}
