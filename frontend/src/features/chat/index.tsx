// Public interface of the chat feature: the chat page + the sidebar thread list.
import { useCallback, useRef } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { Toolbar } from '@/ui';
import { useChatSessions, useCreateChatSession } from '@/api/hooks/use-chat-sessions';
import { ChatPanel } from './components/chat-panel';

export { ChatThreadList } from './components/chat-thread-list';

export default function ChatPage() {
  const { sessionId = null } = useParams();
  const navigate = useNavigate();
  const { data: sessions = [] } = useChatSessions();
  const createSession = useCreateChatSession();
  const ensuringRef = useRef<Promise<string> | null>(null);

  // A draft (/ask) has no session until the first message is sent. The route
  // is /ask/:sessionId? (one route), so swapping the param does NOT remount the
  // panel and the in-flight stream survives.
  const ensureSession = useCallback((): Promise<string> => {
    if (ensuringRef.current) return ensuringRef.current;
    const p = createSession
      .mutateAsync(undefined)
      .then((s) => {
        navigate(`/ask/${s.id}`, { replace: true });
        ensuringRef.current = null;
        return s.id;
      })
      .catch((err) => {
        ensuringRef.current = null;
        throw err;
      });
    ensuringRef.current = p;
    return p;
  }, [createSession, navigate]);

  const title = sessions.find((s) => s.id === sessionId)?.title || 'New chat';

  return (
    <div className="relative h-full min-h-0">
      <Toolbar title={title} />
      <ChatPanel sessionId={sessionId} ensureSession={sessionId ? undefined : ensureSession} />
    </div>
  );
}
