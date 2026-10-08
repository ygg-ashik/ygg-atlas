import { act, renderHook } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import type { ArtifactBlock } from '@/api/chat';
import { useOpenArtifact } from './use-open-artifact';

const artifact = { kind: 'artifact', id: 'x' } as ArtifactBlock;

describe('useOpenArtifact', () => {
  it('opens, closes, and closes when the conversation changes', () => {
    const { result, rerender } = renderHook(({ id }) => useOpenArtifact(id), {
      initialProps: { id: 's1' as string | null },
    });
    expect(result.current.artifact).toBeNull();
    act(() => result.current.open(artifact));
    expect(result.current.artifact).toBe(artifact);
    act(() => result.current.close());
    expect(result.current.artifact).toBeNull();

    act(() => result.current.open(artifact));
    rerender({ id: 's2' });
    expect(result.current.artifact).toBeNull();
  });
});
