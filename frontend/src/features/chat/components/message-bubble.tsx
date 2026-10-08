import { MarkdownMessage } from './markdown-message';

export function MessageBubble({ role, text }: { role: 'user' | 'assistant'; text: string }) {
  return (
    <div className={role === 'user' ? 'flex justify-end' : 'flex justify-start'}>
      <div
        className={
          role === 'user'
            ? 'max-w-[85%] whitespace-pre-wrap rounded-2xl rounded-br-sm bg-primary px-3.5 py-2 text-sm text-primary-foreground'
            : // Assistant answers carry tables/lists: the bubble hugs its content
              // (w-fit) but may use the full row (max-w-full min-w-0) so wide
              // markdown scrolls INSIDE the background instead of bleeding out.
              'w-fit min-w-0 max-w-full rounded-2xl rounded-bl-sm bg-muted px-3.5 py-2 text-sm'
        }
      >
        {role === 'assistant' ? <MarkdownMessage text={text} /> : text}
      </div>
    </div>
  );
}
