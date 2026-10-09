// Routes owned by phases 3 and 4 may not exist on this deployment yet. When
// the route itself is missing, the read resolves to a typed state the UI
// renders ("Not available yet"), not an error. Every other failure, including
// a business 404 such as "No such user.", still throws.
import { isAxiosError } from 'axios';

/** `missing`: the route is not deployed. `forbidden`: the caller may not read it
 * (only for reads that opt in, e.g. self-service screens over admin-gated metadata). */
export type UnavailableReason = 'missing' | 'forbidden';

export type Availability<T> =
  { available: true; data: T } | { available: false; reason: UnavailableReason };

/** FastAPI's body for an unmatched route; access 404s carry a business sentence instead. */
const ROUTE_MISSING_DETAIL = 'Not Found';

/** True only for FastAPI's default 404 (`{"detail": "Not Found"}`): the route does not exist. */
export function isRouteMissing(error: unknown): boolean {
  if (!isAxiosError(error) || error.response?.status !== 404) return false;
  const data: unknown = error.response.data;
  return (
    typeof data === 'object' &&
    data !== null &&
    (data as { detail?: unknown }).detail === ROUTE_MISSING_DETAIL
  );
}

const isForbidden = (error: unknown) => isAxiosError(error) && error.response?.status === 403;

export interface AvailabilityOptions {
  /** Resolve a 403 to `{available: false, reason: 'forbidden'}` instead of throwing. */
  forbiddenIsUnavailable?: boolean;
}

/** Runs a request against a route that may not ship yet. */
export async function whenAvailable<T>(
  request: () => Promise<T>,
  { forbiddenIsUnavailable = false }: AvailabilityOptions = {},
): Promise<Availability<T>> {
  try {
    return { available: true, data: await request() };
  } catch (error) {
    if (isRouteMissing(error)) return { available: false, reason: 'missing' };
    if (forbiddenIsUnavailable && isForbidden(error)) {
      return { available: false, reason: 'forbidden' };
    }
    throw error;
  }
}
