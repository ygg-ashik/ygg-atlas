import { useEffect, useState } from 'react';
import { ArrowUp } from 'lucide-react';
import { Button, cn, Glass } from '@/ui';

interface ComposerProps {
  value: string;
  onChange: (v: string) => void;
  onSend: () => void;
  onStop: () => void;
  isStreaming: boolean;
  disabled: boolean;
  /** Turn start (epoch ms) for the elapsed timer while streaming. */
  startedAt?: number;
}

function useElapsedSeconds(startedAt: number | undefined, active: boolean): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active) return;
    setNow(Date.now());
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [active]);
  if (!active || !startedAt) return 0;
  return Math.max(0, Math.floor((now - startedAt) / 1000));
}

/** Send ⇄ stop morph: the arrow fades into a stop square inside a spinning ring. */
function SendStopButton({
  isStreaming,
  canSend,
  onStop,
}: {
  isStreaming: boolean;
  canSend: boolean;
  onStop: () => void;
}) {
  return (
    <Button
      type={isStreaming ? 'button' : 'submit'}
      variant="send"
      size="send"
      data-streaming={isStreaming}
      aria-label={isStreaming ? 'Stop generating' : 'Send'}
      disabled={!isStreaming && !canSend}
      onClick={isStreaming ? onStop : undefined}
      className="relative"
    >
      <span
        aria-hidden
        className={cn(
          'absolute -inset-1 rounded-full border-2 border-transparent border-t-primary transition-opacity',
          isStreaming ? 'animate-spin opacity-100' : 'opacity-0',
        )}
      />
      <ArrowUp className={cn('transition-opacity duration-200', isStreaming && 'opacity-0')} />
      <span
        aria-hidden
        className={cn(
          'absolute h-[11px] w-[11px] rounded-[3px] bg-white transition-transform duration-300 ease-out',
          isStreaming ? 'scale-100' : 'scale-0',
        )}
      />
    </Button>
  );
}

/** Glass composer (DESIGN.md › glass-composer): send⇄stop morph with progress
 * ring, mono elapsed timer while working, accent focus ring. */
export function Composer({
  value,
  onChange,
  onSend,
  onStop,
  isStreaming,
  disabled,
  startedAt,
}: ComposerProps) {
  const elapsed = useElapsedSeconds(startedAt, isStreaming);
  const canSend = !disabled && value.trim().length > 0;
  const submit = () => {
    if (!isStreaming && canSend) onSend();
  };

  return (
    <Glass
      as="form"
      specular
      onSubmit={(e) => {
        e.preventDefault();
        submit();
      }}
      className="w-full max-w-[740px] rounded-glass pb-2.5 pl-[18px] pr-3 pt-3 transition-shadow duration-300 focus-within:shadow-[var(--glass-shadow),var(--glass-spec),0_0_0_4px_hsl(var(--primary)/0.12)]"
    >
      <textarea
        rows={1}
        value={value}
        disabled={disabled || isStreaming}
        aria-label="Ask Atlas"
        placeholder="Ask Atlas about revenue, campaigns, accounts…"
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
            e.preventDefault();
            submit();
          }
        }}
        className="max-h-40 min-h-[26px] w-full resize-none bg-transparent text-answer text-ink outline-none [field-sizing:content] placeholder:text-muted-2 disabled:opacity-60"
      />
      <div className="mt-1.5 flex items-center gap-1.5">
        <span className="text-caption text-muted-2">
          Answers come from governed metrics, with provenance on every number.
        </span>
        <span
          role="timer"
          className={cn(
            'ml-auto font-mono text-caption text-muted-foreground transition-opacity',
            isStreaming ? 'opacity-100' : 'opacity-0',
          )}
        >
          {isStreaming ? `${elapsed}s` : ''}
        </span>
        <SendStopButton isStreaming={isStreaming} canSend={canSend} onStop={onStop} />
      </div>
    </Glass>
  );
}
