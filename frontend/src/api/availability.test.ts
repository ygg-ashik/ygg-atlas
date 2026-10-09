import { describe, expect, it } from 'vitest';
import { isRouteMissing, whenAvailable } from './availability';
import { httpError } from './test-support';

const failWith = (err: unknown) => async () => {
  throw err;
};

describe('isRouteMissing', () => {
  it("is true only for FastAPI's default 404 body", () => {
    expect(isRouteMissing(httpError(404, { detail: 'Not Found' }))).toBe(true);
    expect(isRouteMissing(httpError(404, { detail: 'No such user.' }))).toBe(false);
    expect(isRouteMissing(httpError(404))).toBe(false);
    expect(isRouteMissing(httpError(403, { detail: 'Not Found' }))).toBe(false);
    expect(isRouteMissing(new Error('Not Found'))).toBe(false);
  });
});

describe('whenAvailable', () => {
  it('wraps a successful response', async () => {
    await expect(whenAvailable(async () => [1, 2])).resolves.toEqual({
      available: true,
      data: [1, 2],
    });
  });

  it('turns a missing route into the typed unavailable state', async () => {
    await expect(whenAvailable(failWith(httpError(404, { detail: 'Not Found' })))).resolves.toEqual(
      { available: false, reason: 'missing' },
    );
  });

  it('keeps a business 404 as an error', async () => {
    const err = httpError(404, { detail: 'No such user.' });
    await expect(whenAvailable(failWith(err))).rejects.toBe(err);
  });

  it('rethrows a 403 unless the read opts in', async () => {
    const err = httpError(403, { detail: 'no' });
    await expect(whenAvailable(failWith(err))).rejects.toBe(err);
    await expect(whenAvailable(failWith(err), { forbiddenIsUnavailable: true })).resolves.toEqual({
      available: false,
      reason: 'forbidden',
    });
  });
});
