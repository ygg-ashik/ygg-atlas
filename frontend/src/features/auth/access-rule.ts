// src/features/auth/access-rule.ts
import { type MyAccessView } from '@/api/hooks/use-my-access';

/** Which part of the backend's answer opens a route or a nav entry. One rule
 * drives both the route guard and the navigation, so they never disagree. */
export interface AccessRule {
  /** Any one of these capabilities opens it; empty means every signed-in user. */
  anyOf: readonly string[];
  /** Group managers (backend `is_manager`) open it too. */
  managers?: boolean;
  /** The capability the denied page names, e.g. `admin:users`. */
  need: string;
}

/** True only on a successful `/me/access` answer that satisfies the rule. Loading
 * and failures are false (fail closed); the API still refuses whatever this lets through. */
export function allows(view: MyAccessView, rule: AccessRule): boolean {
  if (view.status !== 'ready') return false;
  if (rule.anyOf.length === 0) return true;
  return view.canAny(...rule.anyOf) || (rule.managers === true && view.isManager);
}
