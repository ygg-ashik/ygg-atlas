import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { createChatSession, deleteChatSession, listChatMessages, listChatSessions } from '../chat';

export function useChatSessions(enabled = true) {
  return useQuery({
    queryKey: ['chat-sessions'],
    queryFn: listChatSessions,
    enabled,
  });
}

export function useChatMessages(sessionId: string | null) {
  return useQuery({
    queryKey: ['chat-messages', sessionId],
    queryFn: () => listChatMessages(sessionId as string),
    enabled: !!sessionId,
  });
}

export function useCreateChatSession() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (title?: string) => createChatSession(title),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['chat-sessions'] }),
  });
}

export function useDeleteChatSession() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => deleteChatSession(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['chat-sessions'] }),
  });
}
