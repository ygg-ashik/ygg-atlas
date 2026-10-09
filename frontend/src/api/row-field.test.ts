import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
  deleteUserAttribute,
  listLabelClasses,
  listScopeDimensions,
  listUserAttributes,
  putLabelClass,
  putUserAttribute,
} from './row-field';
import { answerWith, http } from './test-api-mock';
import { httpError } from './test-support';

vi.mock('./axios-instance', async () => (await import('./test-api-mock')).apiMock);

describe('row and field client (phase 3)', () => {
  beforeEach(() => answerWith([{ key: 'csm', value: 'sara' }]));

  it('wraps reads as available', async () => {
    await expect(listUserAttributes('u1')).resolves.toEqual({
      available: true,
      data: [{ key: 'csm', value: 'sara' }],
    });
    expect(http.get).toHaveBeenCalledWith('/admin/users/u1/attributes');
    await listLabelClasses();
    expect(http.get).toHaveBeenCalledWith('/admin/label-classes');
    await listScopeDimensions();
    expect(http.get).toHaveBeenCalledWith('/meta/scope-dimensions');
  });

  it('resolves every read to unavailable when the route is missing', async () => {
    http.get.mockRejectedValue(httpError(404, { detail: 'Not Found' }));
    const missing = { available: false, reason: 'missing' };
    await expect(listUserAttributes('u1')).resolves.toEqual(missing);
    await expect(listLabelClasses()).resolves.toEqual(missing);
    await expect(listScopeDimensions()).resolves.toEqual(missing);
  });

  it('keeps a business 404 (unknown user) as an error', async () => {
    http.get.mockRejectedValue(httpError(404, { detail: 'No such user.' }));
    await expect(listUserAttributes('u1')).rejects.toMatchObject({ response: { status: 404 } });
  });

  it('scope dimensions: a 403 (self-service viewer) is unavailable, not an error', async () => {
    http.get.mockRejectedValue(httpError(403, { detail: 'This needs admin:groups.' }));
    await expect(listScopeDimensions()).resolves.toEqual({ available: false, reason: 'forbidden' });
    await expect(listLabelClasses()).rejects.toMatchObject({ response: { status: 403 } });
  });

  it('writes attributes per key (escaped) and label classes', async () => {
    await putUserAttribute('u1', 'csm', 'sara@x.com');
    expect(http.put).toHaveBeenCalledWith('/admin/users/u1/attributes/csm', {
      value: 'sara@x.com',
    });
    await deleteUserAttribute('u1', 'a/b');
    expect(http.delete).toHaveBeenCalledWith('/admin/users/u1/attributes/a%2Fb');
    await putLabelClass('person_name', { mode: 'bucket', bucket_size: 3 });
    expect(http.put).toHaveBeenLastCalledWith('/admin/label-classes/person_name', {
      mode: 'bucket',
      bucket_size: 3,
    });
  });
});
