import { renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { httpError } from '../test-support';
import { createQueryWrapper } from './test-query-wrapper';
import { useAuthMethods } from './use-auth-methods';

const get = vi.hoisted(() => vi.fn());
vi.mock('../axios-instance', () => ({ api: { get } }));

const render = () => renderHook(() => useAuthMethods(), { wrapper: createQueryWrapper().wrapper });

describe('useAuthMethods', () => {
  beforeEach(() => {
    get.mockReset();
  });

  it('reads both methods when phase 4 is live', async () => {
    get.mockResolvedValue({
      data: {
        pat: { enabled: true, default_days: 90, max_days: 365 },
        oauth: { enabled: true, hosted_connectors: true },
      },
    });
    const { result } = render();
    await waitFor(() => expect(result.current.methods.available).toBe(true));
    expect(result.current.methods.pat).toEqual({ enabled: true, default_days: 90, max_days: 365 });
    expect(result.current.methods.oauth.hosted_connectors).toBe(true);
  });

  it('treats a 404 as both disabled', async () => {
    get.mockRejectedValue(httpError(404, { detail: 'Not Found' }));
    const { result } = render();
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.methods).toMatchObject({
      available: false,
      pat: { enabled: false },
      oauth: { enabled: false, hosted_connectors: false },
    });
  });

  it('treats a failure as disabled too (never promises a method)', async () => {
    get.mockRejectedValue(httpError(500));
    const { result } = render();
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.methods.pat.enabled).toBe(false);
    expect(result.current.methods.oauth.enabled).toBe(false);
  });
});
