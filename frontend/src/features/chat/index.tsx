// Public interface of the chat feature: sessions sidebar + chat panel.
import { useCallback, useRef, useState } from 'react';
import { MessageSquareText, Plus, Trash2 } from 'lucide-react';
import {
  Button,
  cn,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  ScrollArea,
} from '@/ui';
import { formatRelativeTime } from '@/lib/utils';
import {
  useChatSessions,
  useCreateChatSession,
  useDeleteChatSession,
} from '@/api/hooks/use-chat-sessions';
import type { ChatSession } from '@/api/chat';
import { ChatPanel } from './components/chat-panel';

export default function ChatPage() {
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [pendingDelete, setPendingDelete] = useState<ChatSession | null>(null);
  const { data: sessions = [] } = useChatSessions();
  const createSession = useCreateChatSession();
  const deleteSession = useDeleteChatSession();
  const ensuringRef = useRef<Promise<string> | null>(null);

  // "New chat" is a draft — no session exists until the first message is sent.
  const handleNewChat = () => setActiveSessionId(null);

  const ensureSession = useCallback((): Promise<string> => {
    if (ensuringRef.current) return ensuringRef.current;
    const p = createSession
      .mutateAsync(undefined)
      .then((s) => {
        setActiveSessionId(s.id);
        ensuringRef.current = null;
        return s.id;
      })
      .catch((err) => {
        ensuringRef.current = null;
        throw err;
      });
    ensuringRef.current = p;
    return p;
  }, [createSession]);

  const confirmDelete = async () => {
    if (!pendingDelete) return;
    await deleteSession.mutateAsync(pendingDelete.id);
    if (activeSessionId === pendingDelete.id) setActiveSessionId(null);
    setPendingDelete(null);
  };

  return (
    <div className="flex h-full min-h-0">
      {/* Sessions sidebar */}
      <aside className="flex w-64 shrink-0 flex-col border-r bg-card">
        <div className="p-3">
          <Button
            variant="outline"
            size="sm"
            className="w-full justify-start"
            onClick={handleNewChat}
          >
            <Plus className="h-3.5 w-3.5" />
            New chat
          </Button>
        </div>
        <ScrollArea className="min-h-0 flex-1">
          <div className="space-y-0.5 px-2 pb-2">
            {sessions.length === 0 && (
              <p className="px-2 py-6 text-center text-xs text-muted-foreground">
                No conversations yet.
              </p>
            )}
            {sessions.map((session) => {
              const isActive = session.id === activeSessionId;
              return (
                <div
                  key={session.id}
                  role="button"
                  tabIndex={0}
                  onClick={() => setActiveSessionId(session.id)}
                  onKeyDown={(e) => e.key === 'Enter' && setActiveSessionId(session.id)}
                  className={cn(
                    'group flex cursor-pointer items-center gap-2 rounded-md px-2.5 py-2 text-sm transition-colors',
                    isActive
                      ? 'bg-accent text-accent-foreground'
                      : 'text-muted-foreground hover:bg-accent/60 hover:text-foreground',
                  )}
                >
                  <MessageSquareText className="h-3.5 w-3.5 shrink-0 opacity-60" />
                  <span className="min-w-0 flex-1 truncate">
                    {session.title || 'Untitled chat'}
                  </span>
                  <span className="shrink-0 text-[10px] text-muted-foreground/70 group-hover:hidden">
                    {formatRelativeTime(session.updated_at)}
                  </span>
                  <button
                    type="button"
                    aria-label={`Delete ${session.title || 'chat'}`}
                    onClick={(e) => {
                      e.stopPropagation();
                      setPendingDelete(session);
                    }}
                    className="hidden shrink-0 rounded p-0.5 text-muted-foreground transition-colors hover:text-destructive group-hover:block"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </div>
              );
            })}
          </div>
        </ScrollArea>
      </aside>

      {/* Chat panel — always mounted; null session means draft mode */}
      <div className="flex min-w-0 flex-1 flex-col">
        {/* No key: the panel must NOT remount when the draft session gets its
            real id mid-stream, or the in-flight stream would be aborted. */}
        <ChatPanel
          sessionId={activeSessionId}
          ensureSession={activeSessionId ? undefined : ensureSession}
        />
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
