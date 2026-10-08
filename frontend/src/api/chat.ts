import { api } from './axios-instance';

/** Audit record attached to every metric answer — the atlas guarantee that
 * "every number carries provenance". */
export interface Provenance {
  tool: string;
  metric_id?: string;
  metric_name?: string;
  source: string;
  freshness?: string;
  executed_at: string;
}

/** Answer blocks: shared contract with backend/app/agent/blocks.py. */
export interface ClarifyOption {
  label: string;
  metric_id?: string | null;
}

export interface ClarifyBlock {
  kind: 'clarify';
  question: string;
  options: ClarifyOption[];
}

export interface ArtifactBlock {
  kind: 'artifact';
  id: string; // e.g. "metric_breakdown:revenue:1"
  artifact_type: 'breakdown' | 'comparison' | 'funnel';
  title: string;
  unit: string; // '' when unitless
  columns: string[];
  rows: (string | number | null)[][];
  provenance: Provenance;
}

export type AnswerBlock = ClarifyBlock | ArtifactBlock;

export interface ChatSession {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
}

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  provenance?: Provenance[];
  blocks?: AnswerBlock[] | null;
  feedback_rating?: 'up' | 'down' | null;
  created_at: string;
}

export type FeedbackCategory = 'inaccurate' | 'incomplete' | 'not_relevant';

export async function createChatSession(title?: string): Promise<ChatSession> {
  const { data } = await api.post<ChatSession>('/chat/sessions', title ? { title } : {});
  return data;
}

export async function listChatSessions(): Promise<ChatSession[]> {
  const { data } = await api.get<ChatSession[]>('/chat/sessions');
  return data;
}

export async function listChatMessages(sessionId: string): Promise<ChatMessage[]> {
  const { data } = await api.get<ChatMessage[]>(`/chat/sessions/${sessionId}/messages`);
  return data;
}

export async function deleteChatSession(sessionId: string): Promise<void> {
  await api.delete(`/chat/sessions/${sessionId}`);
}

export async function setMessageFeedback(
  messageId: string,
  body: { rating: 'up' | 'down'; category?: FeedbackCategory },
): Promise<void> {
  await api.patch(`/chat/messages/${messageId}/feedback`, body);
}
