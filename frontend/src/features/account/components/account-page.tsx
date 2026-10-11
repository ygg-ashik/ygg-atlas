import type * as React from 'react';
import { Link, useLocation } from 'react-router-dom';
import { Toolbar, ToolbarCrumb } from '@/ui';

interface AccountPageProps {
  /** Toolbar title, e.g. "My access". */
  title: string;
  /** A back link before the toolbar title: `My access ›`. */
  crumb?: { to: string; label: string };
  /** Serif page heading; defaults to the title. */
  heading?: React.ReactNode;
  sub: React.ReactNode;
  /** One primary action at the right of the heading. */
  action?: React.ReactNode;
  children: React.ReactNode;
}

/** The 760px account page: glass toolbar with the route label, serif heading row,
 * then solid cards (DESIGN.md › Admin and self-service). */
export function AccountPage({
  title,
  crumb,
  heading = title,
  sub,
  action,
  children,
}: AccountPageProps) {
  const { pathname } = useLocation();
  return (
    <div className="relative h-full">
      <Toolbar
        title={title}
        route={pathname}
        crumb={
          crumb && (
            <ToolbarCrumb>
              <Link to={crumb.to}>{crumb.label}</Link>
            </ToolbarCrumb>
          )
        }
      />
      <div className="absolute inset-0 overflow-y-auto">
        <div className="mx-auto max-w-[760px] px-6 pb-16 pt-[84px]">
          <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
            <div className="min-w-[min(100%,320px)] flex-1">
              <h2 className="mb-1 mt-1.5 font-serif text-display text-ink">{heading}</h2>
              <p className="max-w-[640px] text-muted-foreground">{sub}</p>
            </div>
            {action}
          </div>
          {children}
        </div>
      </div>
    </div>
  );
}

/** Section heading inside an account page ("What I can see"). */
export function SectionHeading({
  children,
  meta,
}: {
  children: React.ReactNode;
  meta?: React.ReactNode;
}) {
  return (
    <h3 className="mb-2.5 mt-[26px] flex items-center gap-2.5 font-serif text-section text-ink">
      {children}
      {meta && <span className="ml-auto font-sans text-caption text-muted-foreground">{meta}</span>}
    </h3>
  );
}
