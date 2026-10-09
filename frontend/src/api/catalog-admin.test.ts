import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fetchCatalogResources } from './catalog-admin';
import { answerWith, http } from './test-api-mock';

vi.mock('./axios-instance', async () => (await import('./test-api-mock')).apiMock);

describe('catalog admin client', () => {
  beforeEach(() => answerWith({ sources: [] }));

  it('reads metadata, optionally as a user', async () => {
    await expect(fetchCatalogResources()).resolves.toEqual({ sources: [] });
    expect(http.get).toHaveBeenCalledWith('/atlas/catalog/resources', { params: {} });
    await fetchCatalogResources('u1');
    expect(http.get).toHaveBeenLastCalledWith('/atlas/catalog/resources', {
      params: { as_user: 'u1' },
    });
  });
});
