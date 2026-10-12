// src/features/command/command-palette.tsx
import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Command, defaultFilter } from 'cmdk';
import { BarChart3, CornerDownLeft, MessageCircle, Search, Sparkles } from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import { DialogDescription, DialogTitle, Tag } from '@/ui';
import { useMetricsCatalog } from '@/api/hooks/use-atlas';
import { useChatSessions } from '@/api/hooks/use-chat-sessions';
import { usePaletteOpen } from './use-palette-open';
import { askPath, metricPath, threadPath } from '@/lib/routes';

/** A page the palette can jump to. */
export interface PaletteLink {
  label: string;
  to: string;
}

/** A task the palette runs in place (DESIGN.md › Quick actions). App.tsx
 * composes the list from the viewer's capabilities; the palette only shows it. */
export interface QuickAction {
  id: string;
  label: string;
  icon: LucideIcon;
  /** Extra search words ("pat", "permissions"). */
  keywords?: string[];
  /** Offered only once something is typed (the second theme, older requests). */
  onlyWhenSearching?: boolean;
  /** A role-gated action's tag: "admin" or "manager". */
  tag?: string;
  run: () => void;
}

interface CommandPaletteProps {
  pages: readonly PaletteLink[];
  actions?: readonly QuickAction[];
  /** Lets App.tsx load what the actions need only while the palette is open. */
  onOpenChange?: (open: boolean) => void;
}

/** Threads listed before anything is typed; a search covers them all. */
const RECENT = 5;
const ASK = 'ask ';

/** "Ask: …" matches whatever is typed, so it always shows but ranks last: a
 * typed task or page is what Enter runs, and asking is the fallback. */
function rank(value: string, search: string, keywords?: string[]): number {
  return value.startsWith(ASK) ? Number.MIN_VALUE : defaultFilter(value, search, keywords);
}

const ITEM =
  'flex cursor-pointer items-center gap-2.5 rounded-md px-2.5 py-2 text-sm text-body data-[selected=true]:bg-primary/10 data-[selected=true]:text-ink';
const GROUP =
  '[&_[cmdk-group-heading]]:px-2.5 [&_[cmdk-group-heading]]:pb-1 [&_[cmdk-group-heading]]:pt-2 [&_[cmdk-group-heading]]:text-caption [&_[cmdk-group-heading]]:uppercase [&_[cmdk-group-heading]]:tracking-[0.06em] [&_[cmdk-group-heading]]:text-muted-2';

/** Spotlight-style palette (DESIGN.md › command-palette): glass, scrim, materialize.
 * Groups: Quick actions, Go to, Recent threads, Metrics, then Ask as the fallback. `pages` and
 * `actions` are composed in App.tsx from the same capability-filtered lists as
 * the navigation, so the palette never offers what the viewer can't open. */
export function CommandPalette({ pages, actions = [], onOpenChange: notify }: CommandPaletteProps) {
  const [open, setOpen] = usePaletteOpen(notify);
  const [query, setQuery] = useState('');
  const navigate = useNavigate();
  const { data: catalog } = useMetricsCatalog();
  const { data: sessions = [] } = useChatSessions();

  const onOpenChange = (next: boolean) => {
    setOpen(next);
    if (!next) setQuery('');
  };
  const go = (to: string) => {
    onOpenChange(false);
    navigate(to);
  };
  const run = (action: QuickAction) => {
    onOpenChange(false);
    action.run();
  };
  const metrics = (catalog?.sources ?? []).flatMap((s) =>
    [...s.metrics, ...s.funnels].map((m) => ({ ...m, key: `${s.id}:${m.id}` })),
  );
  const asked = query.trim();
  const shownActions = asked ? actions : actions.filter((a) => !a.onlyWhenSearching);
  const threads = asked ? sessions : sessions.slice(0, RECENT);

  return (
    <Command.Dialog
      open={open}
      onOpenChange={onOpenChange}
      label="Command palette"
      filter={rank}
      vimBindings={false}
      overlayClassName="fixed inset-0 z-40 bg-black/20 data-[state=closed]:animate-out data-[state=open]:animate-in data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0"
      contentClassName="glass fixed inset-x-0 top-[18%] z-50 mx-auto w-[min(560px,calc(100vw-32px))] rounded-shell p-2.5 data-[state=closed]:animate-materialize-out data-[state=open]:animate-materialize-in"
    >
      <DialogTitle className="sr-only">Command palette</DialogTitle>
      <DialogDescription className="sr-only">
        Run a quick action, jump to a page or thread, search metrics, or ask Atlas a question.
      </DialogDescription>
      <div className="flex items-center gap-2 border-b border-border/70 px-2.5 pb-2.5">
        <Search aria-hidden className="h-4 w-4 text-muted-2" />
        <Command.Input
          value={query}
          onValueChange={setQuery}
          placeholder="Type a task, a page, a metric, or ask a question…"
          className="w-full bg-transparent py-1.5 text-[17px] text-ink outline-none placeholder:text-muted-2"
        />
      </div>
      <Command.List className="max-h-[360px] overflow-y-auto pt-1.5">
        <Command.Empty className="px-2.5 py-6 text-center text-label text-muted-foreground">
          No matches.
        </Command.Empty>
        {shownActions.length > 0 && (
          <Command.Group heading="Quick actions" className={GROUP}>
            {shownActions.map((a) => (
              <Command.Item
                key={a.id}
                value={`action ${a.label}`}
                keywords={a.keywords}
                onSelect={() => run(a)}
                className={ITEM}
              >
                <a.icon aria-hidden className="h-4 w-4 shrink-0 text-muted-2" />
                <span className="min-w-0 truncate">{a.label}</span>
                {a.tag && <Tag className="shrink-0">{a.tag}</Tag>}
                <span className="ml-auto flex shrink-0 items-center gap-1 whitespace-nowrap text-caption text-muted-2">
                  <CornerDownLeft aria-hidden className="h-3 w-3" />
                  do it
                </span>
              </Command.Item>
            ))}
          </Command.Group>
        )}
        <Command.Group heading="Go to" className={GROUP}>
          {pages.map((p) => (
            <Command.Item
              key={p.to}
              value={`page ${p.label}`}
              onSelect={() => go(p.to)}
              className={ITEM}
            >
              {p.label}
              <span className="ml-auto font-mono text-[11px] text-muted-2">{p.to}</span>
            </Command.Item>
          ))}
        </Command.Group>
        <Command.Group heading="Recent threads" className={GROUP}>
          {threads.map((s) => (
            <Command.Item
              key={s.id}
              value={`thread ${s.id} ${s.title}`}
              onSelect={() => go(threadPath(s.id))}
              className={ITEM}
            >
              <MessageCircle aria-hidden className="h-4 w-4 text-muted-2" />
              {s.title || 'Untitled chat'}
            </Command.Item>
          ))}
        </Command.Group>
        <Command.Group heading="Metrics" className={GROUP}>
          {metrics.map((m) => (
            <Command.Item
              key={m.key}
              value={`${m.name} ${m.id}`}
              onSelect={() => go(metricPath(m.id))}
              className={ITEM}
            >
              <BarChart3 aria-hidden className="h-4 w-4 text-muted-2" />
              {m.name}
              <span className="ml-auto font-mono text-[11px] text-muted-2">{m.id}</span>
            </Command.Item>
          ))}
        </Command.Group>
        {asked && (
          <Command.Group heading="Ask" className={GROUP}>
            <Command.Item
              value={`${ASK}${asked}`}
              onSelect={() => go(askPath(asked))}
              className={ITEM}
            >
              <Sparkles aria-hidden className="h-4 w-4 text-primary-text" />
              Ask: “{asked}”<kbd className="ml-auto font-mono text-caption text-muted-2">↵</kbd>
            </Command.Item>
          </Command.Group>
        )}
      </Command.List>
    </Command.Dialog>
  );
}
