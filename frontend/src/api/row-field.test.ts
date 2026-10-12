import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
  deleteUserAttribute,
  listLabelClasses,
  listScopeDimensions,
  listUserAttributes,
  putLabelClass,
  putUserAttribute,
  type LabelClass,
  type ScopeDimension,
  type UserAttribute,
} from './row-field';
import { answerWith, http } from './test-api-mock';
import { httpError } from './test-support';

vi.mock('./axios-instance', async () => (await import('./test-api-mock')).apiMock);

// Exactly the fields of the backend schemas (app/access/schemas/row_field.py).
const ATTRIBUTE: UserAttribute = {
  key: 'csm',
  value: 'sara',
  set_by: null,
  set_at: '2026-10-01T00:00:00Z',
};
const LABEL_CLASS: LabelClass = {
  label_class: 'person_name',
  mode: 'suppress',
  bucket_size: 5,
  updated_at: '2026-10-01T00:00:00Z',
};
const DIMENSION: ScopeDimension = {
  source: 'demo',
  entity: 'order',
  dimension: 'country',
  self_attribute: null,
  description: 'Shopper country',
};

describe('row and field client', () => {
  beforeEach(() => answerWith([]));

  it('reads return the backend arrays as they are', async () => {
    http.get.mockResolvedValueOnce({ data: [ATTRIBUTE] });
    await expect(listUserAttributes('u1')).resolves.toEqual([ATTRIBUTE]);
    expect(http.get).toHaveBeenCalledWith('/admin/users/u1/attributes');
    http.get.mockResolvedValueOnce({ data: [LABEL_CLASS] });
    await expect(listLabelClasses()).resolves.toEqual([LABEL_CLASS]);
    expect(http.get).toHaveBeenCalledWith('/admin/label-classes');
    http.get.mockResolvedValueOnce({ data: [DIMENSION] });
    await expect(listScopeDimensions()).resolves.toEqual([DIMENSION]);
    expect(http.get).toHaveBeenCalledWith('/meta/scope-dimensions');
  });

  it('every failure is an error: there is no "not deployed" state any more', async () => {
    http.get.mockRejectedValue(httpError(404, { detail: 'Not Found' }));
    await expect(listLabelClasses()).rejects.toMatchObject({ response: { status: 404 } });
    http.get.mockRejectedValue(httpError(404, { detail: 'No such user.' }));
    await expect(listUserAttributes('u1')).rejects.toMatchObject({ response: { status: 404 } });
    http.get.mockRejectedValue(httpError(403, { detail: 'This needs admin:groups.' }));
    await expect(listScopeDimensions()).rejects.toMatchObject({ response: { status: 403 } });
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
