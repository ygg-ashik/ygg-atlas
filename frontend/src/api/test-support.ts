// Test helpers for the api layer: build the errors axios raises, and a
// QueryClient wrapper for hook tests. Imported only by *.test.ts(x).
import { AxiosError, AxiosHeaders, type AxiosResponse } from 'axios';

/** An AxiosError carrying an HTTP response, as the interceptor chain throws it. */
export function httpError(status: number, data: unknown = {}): AxiosError {
  const config = { headers: new AxiosHeaders() };
  const response: AxiosResponse = {
    status,
    statusText: String(status),
    data,
    headers: {},
    config,
  };
  return new AxiosError(`Request failed with status code ${status}`, 'ERR', config, {}, response);
}

/** An AxiosError with no response: the network failed or the server never answered. */
export function networkError(): AxiosError {
  return new AxiosError('Network Error', AxiosError.ERR_NETWORK, {
    headers: new AxiosHeaders(),
  });
}
