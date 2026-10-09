import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fetchCapabilityCatalog, fetchMyAccess } from './access';
import { answerWith, http } from './test-api-mock';

vi.mock('./axios-instance', async () => (await import('./test-api-mock')).apiMock);

describe('access client', () => {
  beforeEach(() => answerWith({ role: 'viewer' }));

  it('reads /me/access', async () => {
    await expect(fetchMyAccess()).resolves.toEqual({ role: 'viewer' });
    expect(http.get).toHaveBeenCalledWith('/me/access');
  });

  it('reads /meta/capabilities', async () => {
    await fetchCapabilityCatalog();
    expect(http.get).toHaveBeenCalledWith('/meta/capabilities');
  });
});
