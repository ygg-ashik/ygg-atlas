import { SendHorizontal, Square } from 'lucide-react';

export function Composer({
  value,
  onChange,
  isStreaming,
  canSend,
  onSubmit,
  onAbort,
}: {
  value: string;
  onChange: (value: string) => void;
  isStreaming: boolean;
  canSend: boolean;
  onSubmit: () => void;
  onAbort: () => void;
}) {
  return (
    <div className="border-t bg-background">
      <div className="mx-auto w-full max-w-3xl px-4 py-3">
        <div className="flex items-end gap-2">
          <textarea
            className="max-h-32 min-h-[42px] flex-1 resize-none rounded-lg border bg-background px-3 py-2.5 text-sm shadow-sm outline-none transition-shadow placeholder:text-muted-foreground focus:ring-1 focus:ring-ring disabled:opacity-50"
            rows={1}
            placeholder="Ask about revenue, orders, funnels…"
            value={value}
            disabled={isStreaming || !canSend}
            onChange={(e) => onChange(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
                e.preventDefault();
                onSubmit();
              }
            }}
          />
          {isStreaming ? (
            <button
              type="button"
              aria-label="Stop generating"
              className="rounded-lg bg-muted p-2.5 text-muted-foreground transition-colors hover:bg-muted/80"
              onClick={onAbort}
            >
              <Square className="h-4 w-4" />
            </button>
          ) : (
            <button
              type="button"
              aria-label="Send"
              className="rounded-lg bg-primary p-2.5 text-primary-foreground transition-opacity disabled:opacity-50"
              disabled={!value.trim() || !canSend}
              onClick={onSubmit}
            >
              <SendHorizontal className="h-4 w-4" />
            </button>
          )}
        </div>
        <p className="px-1 pt-1.5 text-[10px] text-muted-foreground">
          Answers come from vetted atlas metrics — check the provenance chips under each number.
        </p>
      </div>
    </div>
  );
}
