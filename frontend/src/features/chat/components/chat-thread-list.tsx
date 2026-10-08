// src/features/chat/components/chat-thread-list.tsx
import { useState } from 'react';
import { Link, useMatch, useNavigate } from 'react-router-dom';
import { Plus, Trash2 } from 'lucide-react';
import {
  Button,
  cn,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/ui';
import { formatRelativeTime } from '@/lib/utils';
import { useChatSessions, useDeleteChatSession } from '@/api/hooks/use-chat-sessions';
import type { ChatSession } from '@/api/chat';

/** Threads for the shell sidebar. The active thread comes from the URL
 * (/ask/:sessionId) so the list and the chat page never share state. */
export function ChatThreadList() {
  const navigate = useNavigate();
  const activeId = useMatch('/ask/:sessionId')?.params.sessionId ?? null;
  const { data: sessions = [] } = useChatSessions();
  const deleteSession = useDeleteChatSession();
  const [pendingDelete, setPendingDelete] = useState<ChatSession | null>(null);

  const confirmDelete = async () => {
    if (!pendingDelete) return;
    await deleteSession.mutateAsync(pendingDelete.id);
    if (activeId === pendingDelete.id) navigate('/ask');
    setPendingDelete(null);
  };

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex items-center px-2.5 pb-1.5 pt-4">
        <span className="flex-1 text-caption uppercase tracking-[0.06em] text-muted-2">
          Threads
        </span>
        <Button variant="ghost" size="sm" className="h-7 px-2" onClick={() => navigate('/ask')}>
          <Plus /> New chat
        </Button>
      </div>
      <div className="min-h-0 flex-1 space-y-0.5 overflow-y-auto pb-2">
        {sessions.length === 0 && (
          <p className="px-2.5 py-4 text-caption text-muted-foreground">No conversations yet.</p>
        )}
        {sessions.map((s) => {
          const current = s.id === activeId;
          return (
            <div key={s.id} className="group relative">
              <Link
                to={`/ask/${s.id}`}
                aria-current={current ? 'page' : undefined}
                className={cn(
                  'flex items-center gap-2 rounded-md px-2.5 py-1.5 text-label transition-colors duration-200',
                  current
                    ? 'bg-card text-ink shadow-[0_0_0_1px_hsl(var(--border))]'
                    : 'text-muted-foreground hover:bg-foreground/5 hover:text-ink',
                )}
              >
                <span className="min-w-0 flex-1 truncate">{s.title || 'Untitled chat'}</span>
                <span className="font-mono text-[10.5px] text-muted-2 group-focus-within:invisible group-hover:invisible">
                  {formatRelativeTime(s.updated_at)}
                </span>
              </Link>
              <button
                type="button"
                aria-label={`Delete ${s.title || 'chat'}`}
                onClick={() => setPendingDelete(s)}
                className="absolute right-1.5 top-1/2 hidden -translate-y-1/2 rounded-full p-1 text-muted-foreground hover:text-negative group-focus-within:block group-hover:block"
              >
                <Trash2 className="h-3.5 w-3.5" />
              </button>
            </div>
          );
        })}
      </div>

      <Dialog open={!!pendingDelete} onOpenChange={(open) => !open && setPendingDelete(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete this chat?</DialogTitle>
            <DialogDescription>
              “{pendingDelete?.title || 'Untitled chat'}” and its messages will be permanently
              removed.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" size="sm" onClick={() => setPendingDelete(null)}>
              Cancel
            </Button>
            <Button
              variant="destructive"
              size="sm"
              onClick={() => void confirmDelete()}
              disabled={deleteSession.isPending}
            >
              Delete
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
