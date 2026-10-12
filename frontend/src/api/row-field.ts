// Row and field controls (phase 3): per-user attributes, label-class masking
// and the declared row-scope dimensions. Shapes: backend app/access/schemas/row_field.py
// (`AttributeOut`, `LabelClassOut`, `LabelClassPut`, `ScopeDimensionOut`).
import { api } from './axios-instance';
import { seg } from './params';

/** `AttributeOut`; `set_by` is null for CLI writes. */
export interface UserAttribute {
  key: string;
  value: string;
  set_by: string | null;
  set_at: string;
}

/** `LabelClassPut.mode` (backend `MASK_MODES`). */
export type MaskMode = 'pseudonymise' | 'suppress' | 'bucket';

/** `LabelClassOut`: one maskable class. `GET /admin/label-classes` lists exactly
 * the classes `PUT` accepts; an unset class reads as `suppress` (fail closed). */
export interface LabelClass {
  label_class: string;
  mode: MaskMode;
  bucket_size: number;
  updated_at: string;
}

/** The largest `bucket_size` the backend accepts (`MAX_BUCKET_SIZE`). */
export const MAX_BUCKET_SIZE = 50;

/** `LabelClassPut`; `bucket_size` 1..50, omitted keeps the stored one. */
export interface LabelClassPut {
  mode: MaskMode;
  bucket_size?: number | null;
}

/** `ScopeDimensionOut`: a dimension a grant's row scope may restrict. */
export interface ScopeDimension {
  source: string;
  entity: string;
  dimension: string;
  /** The user attribute `$self` resolves to; null when `$self` isn't allowed. */
  self_attribute: string | null;
  description: string;
}

/** Needs admin:users; a 404 is "No such user." (a business error). */
export async function listUserAttributes(userId: string): Promise<UserAttribute[]> {
  const { data } = await api.get<UserAttribute[]>(`/admin/users/${seg(userId)}/attributes`);
  return data;
}

/** Per-key write; there is no bulk PUT. Refused (409) on the caller's own user. */
export async function putUserAttribute(
  userId: string,
  key: string,
  value: string,
): Promise<UserAttribute> {
  const { data } = await api.put<UserAttribute>(
    `/admin/users/${seg(userId)}/attributes/${seg(key)}`,
    { value },
  );
  return data;
}

/** 204; a 404 when the user has no such attribute. */
export async function deleteUserAttribute(userId: string, key: string): Promise<void> {
  await api.delete(`/admin/users/${seg(userId)}/attributes/${seg(key)}`);
}

/** Needs admin:groups. */
export async function listLabelClasses(): Promise<LabelClass[]> {
  const { data } = await api.get<LabelClass[]>('/admin/label-classes');
  return data;
}

/** Needs admin:groups; a class not in `listLabelClasses()` is refused (422). */
export async function putLabelClass(labelClass: string, body: LabelClassPut): Promise<LabelClass> {
  const { data } = await api.put<LabelClass>(`/admin/label-classes/${seg(labelClass)}`, body);
  return data;
}

/** Needs admin:groups or admin:users: the grant editor's row-scope builder. */
export async function listScopeDimensions(): Promise<ScopeDimension[]> {
  const { data } = await api.get<ScopeDimension[]>('/meta/scope-dimensions');
  return data;
}
