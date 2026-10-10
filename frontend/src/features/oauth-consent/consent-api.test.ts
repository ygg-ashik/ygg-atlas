import { AxiosError, AxiosHeaders, type AxiosResponse } from 'axios';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { api } from '@/api/axios-instance';
import { ConsentApiError, getConsentPrompt, submitConsent } from './consent-api';

vi.mock('@/api/axios-instance', () => ({ api: { get: vi.fn(), post: vi.fn() } }));

const get = vi.mocked(api.get);
const post = vi.mocked(api.post);

function httpError(status: number, data: unknown): AxiosError {
  const response = { status, data, headers: {}, config: { headers: new AxiosHeaders() } };
  return new AxiosError('fail', 'ERR', undefined, undefined, response as AxiosResponse);
}

async function caught(p: Promise<unknown>): Promise<ConsentApiError> {
  const error: unknown = await p.catch((e: unknown) => e);
  expect(error).toBeInstanceOf(ConsentApiError);
  return error as ConsentApiError;
}

beforeEach(() => {
  get.mockReset();
  post.mockReset();
});

describe('consent-api', () => {
  it('fetches the prompt for an encoded txn', async () => {
    get.mockResolvedValue({ data: { transaction_id: 'a/b' } });
    await expect(getConsentPrompt('a/b')).resolves.toEqual({ transaction_id: 'a/b' });
    expect(get).toHaveBeenCalledWith('/oauth/consent/a%2Fb');
  });

  it('posts only the transaction id and the decision', async () => {
    post.mockResolvedValue({ data: { redirect_to: 'http://localhost:1/cb?code=c' } });
    await expect(submitConsent('t', 'approve')).resolves.toEqual({
      redirect_to: 'http://localhost:1/cb?code=c',
    });
    expect(post).toHaveBeenCalledWith('/oauth/consent', {
      transaction_id: 't',
      decision: 'approve',
    });
  });

  it('never keeps backend text: a string detail has no code', async () => {
    get.mockRejectedValue(httpError(403, { detail: 'Use your @yougotagift.com account.' }));
    const e = await caught(getConsentPrompt('t'));
    expect([e.status, e.reason]).toEqual([403, null]);
    expect(JSON.stringify(e)).not.toMatch(/yougotagift/);
  });

  it('reads an identity refusal code', async () => {
    get.mockRejectedValue(
      httpError(403, { detail: { reason: 'user_disabled', message: 'Your atlas access…' } }),
    );
    const e = await caught(getConsentPrompt('t'));
    expect([e.status, e.reason]).toEqual([403, 'user_disabled']);
  });

  it('reads the reason from a structured detail', async () => {
    post.mockRejectedValue(
      httpError(403, { detail: { reason: 'no_mcp_use', message: 'Your role…' } }),
    );
    const e = await caught(submitConsent('t', 'approve'));
    expect([e.status, e.reason]).toEqual([403, 'no_mcp_use']);
  });

  it('tolerates a body without detail', async () => {
    get.mockRejectedValue(httpError(500, '<html>oops</html>'));
    const e = await caught(getConsentPrompt('t'));
    expect([e.status, e.reason]).toEqual([500, null]);
  });

  it('maps a non-HTTP failure to a status-less error', async () => {
    post.mockRejectedValue(new TypeError('network down'));
    const e = await caught(submitConsent('t', 'deny'));
    expect([e.status, e.reason]).toEqual([null, null]);
  });
});
