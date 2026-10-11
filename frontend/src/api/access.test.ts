import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fetchCapabilityCatalog, fetchMyAccess, type CapabilityCatalog } from './access';
import { answerWith, http } from './test-api-mock';

vi.mock('./axios-instance', async () => (await import('./test-api-mock')).apiMock);

describe('access client', () => {
  beforeEach(() => answerWith({ role: 'viewer' }));

  it('reads /me/access', async () => {
    await expect(fetchMyAccess()).resolves.toEqual({ role: 'viewer' });
    expect(http.get).toHaveBeenCalledWith('/me/access');
  });

  it('reads /meta/capabilities with the row and field vocabulary', async () => {
    // `CatalogOut`: label_classes is the YAML vocabulary, `category` included.
    const catalog: CapabilityCatalog = {
      capabilities: [{ code: 'chat:use', description: 'Ask Atlas questions in chat' }],
      roles: [{ name: 'viewer', capabilities: ['chat:use'] }],
      clearances: [{ code: 'fields:people_names', description: "See people's names" }],
      label_classes: ['category', 'business_name', 'person_name'],
      mask_modes: ['pseudonymise', 'suppress', 'bucket'],
    };
    http.get.mockResolvedValue({ data: catalog });
    await expect(fetchCapabilityCatalog()).resolves.toEqual(catalog);
    expect(http.get).toHaveBeenCalledWith('/meta/capabilities');
  });
});
