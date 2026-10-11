// Query-string hygiene shared by the list clients: empty filters are not sent,
// so the backend applies its own defaults.

type ParamValue = string | number | boolean | null | undefined;

/** Drops undefined, null and empty-string values. */
export function compactParams(
  params: Record<string, ParamValue>,
): Record<string, string | number | boolean> {
  const out: Record<string, string | number | boolean> = {};
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === '') continue;
    out[key] = value;
  }
  return out;
}

/** One URL path segment, escaped (ids are UUIDs, but keys and client ids are not). */
export const seg = (value: string): string => encodeURIComponent(value);
