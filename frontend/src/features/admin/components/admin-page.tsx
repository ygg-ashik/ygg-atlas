import type * as React from 'react';
import { useLocation } from 'react-router-dom';
import { Toolbar } from '@/ui';

interface AdminPageProps {
  title: string;
  /** Serif page heading and its sub-line; omit for pages with their own header card. */
  heading?: React.ReactNode;
  sub?: React.ReactNode;
  actions?: React.ReactNode;
  children: React.ReactNode;
}

/** Admin page frame: glass toolbar with the mono route, then a 1080px column. */
export function AdminPage({ title, heading, sub, actions, children }: AdminPageProps) {
  const { pathname, search } = useLocation();
  return (
    <div className="relative h-full">
      <Toolbar title={title} route={pathname + search} />
      <div className="absolute inset-0 overflow-y-auto">
        <div className="mx-auto max-w-[1080px] px-6 pb-16 pt-[84px]">
          {heading && (
            <div className="mb-[22px] mt-1.5 flex flex-wrap items-end justify-between gap-4">
              <div>
                <h2 className="font-serif text-display text-ink">{heading}</h2>
                {sub && <p className="mt-1 max-w-[640px] text-muted-foreground">{sub}</p>}
              </div>
              {actions}
            </div>
          )}
          {children}
        </div>
      </div>
    </div>
  );
}
