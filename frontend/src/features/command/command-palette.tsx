// src/features/command/command-palette.tsx
import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Command } from 'cmdk';
import { BarChart3, MessageCircle, Search, Sparkles } from 'lucide-react';
import { DialogDescription, DialogTitle } from '@/ui';
import { useMetricsCatalog } from '@/api/hooks/use-atlas';
import { useChatSessions } from '@/api/hooks/use-chat-sessions';
import { usePaletteOpen } from './use-palette-open';

const PAGES = [
  { label: 'Overview', to: '/' },
  { label: 'Ask Atlas', to: '/ask' },
  { label: 'Metrics', to: '/metrics' },
];

const ITEM =
  'flex cursor-pointer items-center gap-2.5 rounded-md px-2.5 py-2 text-sm text-body data-[selected=true]:bg-primary/10 data-[selected=true]:text-ink';
const GROUP =
  '[&_[cmdk-group-heading]]:px-2.5 [&_[cmdk-group-heading]]:pb-1 [&_[cmdk-group-heading]]:pt-2 [&_[cmdk-group-heading]]:text-caption [&_[cmdk-group-heading]]:uppercase [&_[cmdk-group-heading]]:tracking-[0.06em] [&_[cmdk-group-heading]]:text-muted-2';

/** Spotlight-style palette (DESIGN.md › command-palette): glass, scrim, materialize. */
export function CommandPalette() {
  const [open, setOpen] = usePaletteOpen();
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
  const metrics = (catalog?.sources ?? []).flatMap((s) =>
    [...s.metrics, ...s.funnels].map((m) => ({ ...m, key: `${s.id}:${m.id}` })),
  );
  const asked = query.trim();

  return (
    <Command.Dialog
      open={open}
      onOpenChange={onOpenChange}
      label="Command palette"
      vimBindings={false}
      overlayClassName="fixed inset-0 z-40 bg-black/20 data-[state=closed]:animate-out data-[state=open]:animate-in data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0"
      contentClassName="glass fixed inset-x-0 top-[18%] z-50 mx-auto w-[min(560px,calc(100vw-32px))] rounded-shell p-2.5 data-[state=closed]:animate-materialize-out data-[state=open]:animate-materialize-in"
    >
      <DialogTitle className="sr-only">Command palette</DialogTitle>
      <DialogDescription className="sr-only">
        Search metrics and threads, jump to a page, or ask Atlas a question.
      </DialogDescription>
      <div className="flex items-center gap-2 border-b border-border/70 px-2.5 pb-2.5">
        <Search aria-hidden className="h-4 w-4 text-muted-2" />
        <Command.Input
          value={query}
          onValueChange={setQuery}
          placeholder="Search metrics, threads, or ask a question…"
          className="w-full bg-transparent py-1.5 text-[17px] text-ink outline-none placeholder:text-muted-2"
        />
      </div>
      <Command.List className="max-h-[360px] overflow-y-auto pt-1.5">
        <Command.Empty className="px-2.5 py-6 text-center text-label text-muted-foreground">
          No matches.
        </Command.Empty>
        {asked && (
          <Command.Group heading="Ask" className={GROUP}>
            <Command.Item
              value={`ask ${asked}`}
              onSelect={() => go(`/ask?q=${encodeURIComponent(asked)}`)}
              className={ITEM}
            >
              <Sparkles aria-hidden className="h-4 w-4 text-primary-text" />
              Ask: “{asked}”<kbd className="ml-auto font-mono text-caption text-muted-2">↵</kbd>
            </Command.Item>
          </Command.Group>
        )}
        <Command.Group heading="Metrics" className={GROUP}>
          {metrics.map((m) => (
            <Command.Item
              key={m.key}
              value={`${m.name} ${m.id}`}
              onSelect={() => go(`/metrics#metric-${m.id}`)}
              className={ITEM}
            >
              <BarChart3 aria-hidden className="h-4 w-4 text-muted-2" />
              {m.name}
              <span className="ml-auto font-mono text-[11px] text-muted-2">{m.id}</span>
            </Command.Item>
          ))}
        </Command.Group>
        <Command.Group heading="Threads" className={GROUP}>
          {sessions.map((s) => (
            <Command.Item
              key={s.id}
              value={`thread ${s.id} ${s.title}`}
              onSelect={() => go(`/ask/${s.id}`)}
              className={ITEM}
            >
              <MessageCircle aria-hidden className="h-4 w-4 text-muted-2" />
              {s.title || 'Untitled chat'}
            </Command.Item>
          ))}
        </Command.Group>
        <Command.Group heading="Go to" className={GROUP}>
          {PAGES.map((p) => (
            <Command.Item
              key={p.to}
              value={`page ${p.label}`}
              onSelect={() => go(p.to)}
              className={ITEM}
            >
              {p.label}
            </Command.Item>
          ))}
        </Command.Group>
      </Command.List>
    </Command.Dialog>
  );
}
