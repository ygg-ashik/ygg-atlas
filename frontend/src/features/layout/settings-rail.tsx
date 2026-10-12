// src/features/layout/settings-rail.tsx
import { ArrowLeft } from 'lucide-react';
import { TitledSection } from './nav-links';
import { type NavSection } from './types';

interface SettingsRailProps {
  sections: readonly NavSection[];
  email: string | null;
  onBack: () => void;
}

/** The sidebar inside Settings (DESIGN.md › settings-rail): back to Atlas, the
 * serif title, then You and Organization. It swaps in place of the app sidebar. */
export function SettingsRail({ sections, email, onBack }: SettingsRailProps) {
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <button
        type="button"
        onClick={onBack}
        data-swap-focus
        aria-keyshortcuts="Escape"
        className="flex items-center gap-2.5 rounded-md px-2.5 py-2 text-[13.5px] text-muted-foreground transition-[background-color,color,transform] duration-200 hover:bg-foreground/5 hover:text-ink active:scale-[.97]"
      >
        <ArrowLeft aria-hidden className="h-4 w-4" />
        Back to Atlas
        <kbd className="ml-auto font-mono text-[10.5px] text-muted-2">esc</kbd>
      </button>
      <h2 className="px-2.5 pb-1.5 pt-2 font-serif text-[21px] text-ink">Settings</h2>
      <nav aria-label="Settings" className="min-h-0 space-y-0.5 overflow-y-auto">
        {sections.map((s) => (
          <TitledSection key={s.title} section={s} />
        ))}
      </nav>
      {email && (
        <p className="mt-auto truncate px-2.5 pt-2.5 text-caption text-muted-2">
          Signed in as <span className="font-mono text-[11px]">{email}</span>
        </p>
      )}
    </div>
  );
}
