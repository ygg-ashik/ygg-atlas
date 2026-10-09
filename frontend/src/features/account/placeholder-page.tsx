// Temporary page shell for routes whose screens land in later tasks (F4–F9).
import { useLocation } from 'react-router-dom';
import { Toolbar } from '@/ui';

/** Toolbar with the mono route label and the page title; the body arrives later. */
export function PlaceholderPage({ title }: { title: string }) {
  const { pathname } = useLocation();
  return (
    <div className="relative h-full">
      <Toolbar title={title} route={pathname} />
      <div className="absolute inset-0 overflow-y-auto">
        <div className="mx-auto max-w-[760px] px-6 pb-16 pt-[84px]">
          <h2 className="font-serif text-display text-ink">{title}</h2>
          <p className="mt-1 text-muted-foreground">This page is on its way.</p>
        </div>
      </div>
    </div>
  );
}
