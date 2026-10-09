// Row and field controls owned by phase 3 (contracts.md). Until phase 3 ships,
// these routes are missing and every read resolves to `{available: false,
// reason: 'missing'}`, which the UI shows as "Arrives with row and field controls".
import { whenAvailable, type Availability } from './availability';
import { api } from './axios-instance';
import { seg } from './params';

/** `AttributeOut`; `set_by` is null for CLI writes. */
export interface UserAttribute {
  key: string;
  value: string;
  set_by: string | null;
  set_at: string;
}

export type MaskMode = 'pseudonymise' | 'suppress' | 'bucket';

/** `LabelClassOut`. */
export interface LabelClass {
  label_class: string;
  mode: MaskMode;
  bucket_size: number | null;
  updated_at: string;
}

/** `LabelClassPut`; `bucket_size` 1..50, for `bucket` mode. */
export interface LabelClassPut {
  mode: MaskMode;
  bucket_size?: number | null;
}

/** `ScopeDimensionOut`: a dimension a grant's row scope may restrict. */
export interface ScopeDimension {
  source: string;
  entity: string;
  dimension: string;
  self_attribute: string | null;
  description: string;
}

export function listUserAttributes(userId: string): Promise<Availability<UserAttribute[]>> {
  return whenAvailable(async () => {
    const { data } = await api.get<UserAttribute[]>(`/admin/users/${seg(userId)}/attributes`);
    return data;
  });
}

/** Per-key write; there is no bulk PUT. */
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

export async function deleteUserAttribute(userId: string, key: string): Promise<void> {
  await api.delete(`/admin/users/${seg(userId)}/attributes/${seg(key)}`);
}

export function listLabelClasses(): Promise<Availability<LabelClass[]>> {
  return whenAvailable(async () => {
    const { data } = await api.get<LabelClass[]>('/admin/label-classes');
    return data;
  });
}

export async function putLabelClass(labelClass: string, body: LabelClassPut): Promise<LabelClass> {
  const { data } = await api.put<LabelClass>(`/admin/label-classes/${seg(labelClass)}`, body);
  return data;
}

/** `/meta/scope-dimensions` needs admin:groups or admin:users. The admin grant
 * editor and the self-service request form both read it, so a 403 resolves to
 * `{available: false, reason: 'forbidden'}` (the form simply omits row scope). */
export function listScopeDimensions(): Promise<Availability<ScopeDimension[]>> {
  return whenAvailable(
    async () => {
      const { data } = await api.get<ScopeDimension[]>('/meta/scope-dimensions');
      return data;
    },
    { forbiddenIsUnavailable: true },
  );
}
