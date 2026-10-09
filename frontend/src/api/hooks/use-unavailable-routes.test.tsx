// Phase-3 and phase-4 reads: a missing route is a typed "unavailable" state, not an error.
import { type UseQueryResult } from '@tanstack/react-query';
import { renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { type Availability } from '../availability';
import { httpError } from '../test-support';
import { createQueryWrapper } from './test-query-wrapper';
import { useCredentialEvents } from './use-credential-events';
import { useLabelClasses, useScopeDimensions, useUserAttributes } from './use-row-field';
import { useAdminTokens, useClients, useConnectedApps, useMyTokens } from './use-tokens';

const get = vi.hoisted(() => vi.fn());
vi.mock('../axios-instance', () => ({ api: { get } }));

const READS: Record<string, () => UseQueryResult<Availability<unknown>>> = {
  useUserAttributes: () => useUserAttributes('u1'),
  useLabelClasses: () => useLabelClasses(),
  useScopeDimensions: () => useScopeDimensions(),
  useMyTokens: () => useMyTokens(),
  useConnectedApps: () => useConnectedApps(),
  useAdminTokens: () => useAdminTokens(),
  useClients: () => useClients(),
  useCredentialEvents: () => useCredentialEvents(),
};

describe.each(Object.entries(READS))('%s', (_name, useRead) => {
  beforeEach(() => {
    get.mockReset();
  });

  it('resolves a missing route to {available: false} without an error', async () => {
    get.mockRejectedValue(httpError(404, { detail: 'Not Found' }));
    const { result } = renderHook(useRead, { wrapper: createQueryWrapper().wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual({ available: false, reason: 'missing' });
    expect(result.current.isError).toBe(false);
  });

  it('wraps a live answer as available', async () => {
    get.mockResolvedValue({ data: [] });
    const { result } = renderHook(useRead, { wrapper: createQueryWrapper().wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual({ available: true, data: [] });
  });

  it('still errors on a business 404', async () => {
    get.mockRejectedValue(httpError(404, { detail: 'No such user.' }));
    const { result } = renderHook(useRead, { wrapper: createQueryWrapper().wrapper });
    await waitFor(() => expect(result.current.isError).toBe(true));
  });
});

describe('a 403', () => {
  beforeEach(() => {
    get.mockReset();
    get.mockRejectedValue(httpError(403, { detail: 'This needs admin:groups.' }));
  });

  it('is an error for admin reads', async () => {
    const { result } = renderHook(() => useLabelClasses(), {
      wrapper: createQueryWrapper().wrapper,
    });
    await waitFor(() => expect(result.current.isError).toBe(true));
  });

  it('is "unavailable for this viewer" for scope dimensions (self-service reads it)', async () => {
    const { result } = renderHook(() => useScopeDimensions(), {
      wrapper: createQueryWrapper().wrapper,
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual({ available: false, reason: 'forbidden' });
  });
});
