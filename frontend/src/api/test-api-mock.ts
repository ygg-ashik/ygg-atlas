// Shared axios-instance mock for client tests: `vi.mock('./axios-instance', () => apiMock)`.
import { vi } from 'vitest';

export const http = {
  get: vi.fn(),
  post: vi.fn(),
  put: vi.fn(),
  patch: vi.fn(),
  delete: vi.fn(),
};

export const apiMock = { api: http, backendUrl: '' };

/** Every verb resolves `{data}`; call in `beforeEach`. */
export function answerWith(data: unknown = {}) {
  for (const fn of Object.values(http)) {
    fn.mockReset();
    fn.mockResolvedValue({ data });
  }
}
