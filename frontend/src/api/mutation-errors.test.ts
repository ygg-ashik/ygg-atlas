import { QueryClient } from '@tanstack/react-query';
import { describe, expect, it, vi } from 'vitest';
import { describeMutationError, handleMutationError } from './mutation-errors';
import { queryKeys } from './query-keys';
import { httpError, networkError } from './test-support';

describe('describeMutationError', () => {
  it('maps 409 to a conflict with the backend sentence and no Retry by default', () => {
    const info = describeMutationError(
      httpError(409, { detail: 'This request was already decided.' }),
    );
    expect(info).toEqual({
      kind: 'conflict',
      status: 409,
      message: 'This request was already decided.',
      retry: null,
    });
  });

  it('offers Retry on 409 only when the write opts in (stale actor)', () => {
    const info = describeMutationError(
      httpError(409, { detail: 'Access changed while this request was running; retry.' }),
      { retryOn409: true },
    );
    expect(info).toEqual({
      kind: 'conflict',
      status: 409,
      message: 'Access changed while this request was running; retry.',
      retry: { actionLabel: 'Retry' },
    });
  });

  it('maps 403 to the backend sentence, not retryable', () => {
    const info = describeMutationError(
      httpError(403, { detail: "You can't grant capabilities you don't hold." }),
    );
    expect(info.kind).toBe('forbidden');
    expect(info.message).toBe("You can't grant capabilities you don't hold.");
    expect(info.retry).toBeNull();
  });

  it('reads a structured detail message (phase-4 consent shape)', () => {
    const info = describeMutationError(
      httpError(403, {
        detail: { reason: 'no_mcp_use', message: "Your role doesn't include MCP access yet." },
      }),
    );
    expect(info.message).toBe("Your role doesn't include MCP access yet.");
  });

  it('reads the first FastAPI validation message on 422', () => {
    const info = describeMutationError(
      httpError(422, { detail: [{ loc: ['body', 'note'], msg: 'Field required' }] }),
    );
    expect(info).toMatchObject({ kind: 'invalid', status: 422, message: 'Field required' });
  });

  it('maps 400 to invalid and 429 to rate limited, with the backend sentence', () => {
    expect(describeMutationError(httpError(400, { detail: 'Name is taken.' }))).toMatchObject({
      kind: 'invalid',
      status: 400,
      message: 'Name is taken.',
    });
    expect(
      describeMutationError(
        httpError(429, { detail: 'Too many consent attempts; wait a minute.' }),
      ),
    ).toMatchObject({
      kind: 'rate_limited',
      status: 429,
      message: 'Too many consent attempts; wait a minute.',
    });
    expect(describeMutationError(httpError(429)).message).toBe(
      'Too many attempts. Wait a moment and try again.',
    );
    expect(
      describeMutationError(httpError(429, { detail: 'x' }), { retryOn409: true }).retry,
    ).toBeNull();
  });

  it('maps 404 and 503 with their backend sentences', () => {
    expect(describeMutationError(httpError(404, { detail: 'No such request.' }))).toMatchObject({
      kind: 'not_found',
      message: 'No such request.',
    });
    expect(
      describeMutationError(
        httpError(503, { detail: 'The access check is unavailable right now.' }),
      ),
    ).toMatchObject({ kind: 'unavailable', message: 'The access check is unavailable right now.' });
  });

  it('falls back to a plain sentence when the backend sent none', () => {
    expect(describeMutationError(httpError(403)).message).toBe("You don't have access to do that.");
    expect(describeMutationError(httpError(409)).message).toBe(
      'Access changed while this request was running; retry.',
    );
    expect(describeMutationError(httpError(500, 'boom')).kind).toBe('unknown');
  });

  it('treats a missing response as a network failure and a 401 as signed out', () => {
    expect(describeMutationError(networkError())).toMatchObject({ kind: 'network', status: null });
    expect(describeMutationError(httpError(401)).kind).toBe('unauthenticated');
  });

  it('never leaks a non-HTTP error message', () => {
    const info = describeMutationError(new Error('TypeError: x is undefined at foo.ts:3'));
    expect(info).toMatchObject({ kind: 'unknown', status: null });
    expect(info.message).not.toContain('foo.ts');
  });
});

describe('handleMutationError', () => {
  it("invalidates ['me','access'] on every 409, with or without Retry", () => {
    const qc = new QueryClient();
    const spy = vi.spyOn(qc, 'invalidateQueries');
    const plain = handleMutationError(qc, httpError(409, { detail: 'already decided' }));
    expect(plain).toMatchObject({ kind: 'conflict', retry: null });
    const stale = handleMutationError(qc, httpError(409, { detail: 'stale' }), {
      retryOn409: true,
    });
    expect(stale.retry).toEqual({ actionLabel: 'Retry' });
    expect(spy).toHaveBeenCalledTimes(2);
    expect(spy).toHaveBeenCalledWith({ queryKey: queryKeys.myAccess });
    expect(queryKeys.myAccess).toEqual(['me', 'access']);
  });

  it('does not invalidate anything on other failures', () => {
    const qc = new QueryClient();
    const spy = vi.spyOn(qc, 'invalidateQueries');
    handleMutationError(qc, httpError(403, { detail: 'no' }));
    handleMutationError(qc, httpError(422, { detail: 'bad' }));
    expect(spy).not.toHaveBeenCalled();
  });
});
