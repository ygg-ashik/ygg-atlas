// src/ui/route-guard-page.tsx
import * as React from 'react';
import { Lock } from 'lucide-react';
import { Tag } from './tag';

export interface RouteGuardPageProps {
  /** The capability the route needs, e.g. `admin:users`. */
  capability: string;
  /** The route that stays closed, e.g. `/admin/users`. */
  route: string;
  /** The viewer's role, from the token. */
  role: string;
  /** "Go to My access" and "Request access". */
  actions?: React.ReactNode;
}

const mono = (text: string) => <code className="font-mono text-[0.86em] text-ink">{text}</code>;

/** Full-page notice-denied for routes the token doesn't cover (DESIGN.md › route-guard).
 * Presentational: the caller decides from backend capabilities, never from the URL. */
export function RouteGuardPage({ capability, route, role, actions }: RouteGuardPageProps) {
  const titleId = React.useId();
  return (
    <div className="mx-auto max-w-[560px] px-6 pb-20 pt-[18vh]">
      <section
        aria-labelledby={titleId}
        className="flex items-start gap-3 rounded-card bg-card px-[22px] pb-5 pt-[22px] shadow-[0_0_0_1px_hsl(var(--border))]"
      >
        <span
          aria-hidden
          className="grid h-[30px] w-[30px] shrink-0 place-items-center rounded-full bg-foreground/[0.08] text-ink"
        >
          <Lock className="h-3.5 w-3.5" />
        </span>
        <div className="min-w-0 flex-1">
          <h2 id={titleId} className="mb-1.5 mt-0.5 font-serif text-title text-ink">
            This area needs {mono(capability)}
          </h2>
          <p className="text-sm leading-[1.55] text-body">
            Access comes from your sign-in, not from the page you open. Your role (
            <b className="font-semibold">{role}</b>) doesn&apos;t include {mono(capability)}, so{' '}
            {mono(route)} stays closed. Nothing you type can widen it.
          </p>
          <div className="mt-2.5 flex flex-wrap gap-1.5">
            <Tag dot>scope · from your Google sign-in</Tag>
            <Tag dot>role · {role}</Tag>
          </div>
          {actions && <div className="mt-4 flex flex-wrap items-center gap-2.5">{actions}</div>}
        </div>
      </section>
    </div>
  );
}
