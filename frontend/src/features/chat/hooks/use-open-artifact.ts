import { useCallback, useState } from 'react';
import type { ArtifactBlock } from '@/api/chat';

/** The artifact shown in the side panel. It belongs to one conversation, so
 * switching threads (the panel is not remounted) closes it. */
export function useOpenArtifact(sessionId: string | null) {
  const [state, setState] = useState<{ sessionId: string | null; artifact: ArtifactBlock | null }>({
    sessionId,
    artifact: null,
  });
  // Adjust state during render when the conversation changes (no effect flash).
  if (state.sessionId !== sessionId) setState({ sessionId, artifact: null });

  const open = useCallback((artifact: ArtifactBlock) => setState((s) => ({ ...s, artifact })), []);
  const close = useCallback(() => setState((s) => ({ ...s, artifact: null })), []);
  const artifact = state.sessionId === sessionId ? state.artifact : null;
  return { artifact, open, close };
}
