import { Link } from 'react-router-dom';
import { useMyAccess } from '@/api/hooks/use-my-access';
import { ROUTES } from '@/lib/routes';
import {
  Avatar,
  Dialog,
  DialogBareContent,
  DialogBareOverlay,
  DialogDescription,
  DialogPortal,
  DialogTitle,
  RolePill,
  Tag,
} from '@/ui';
import { GroupList } from './group-list';

interface AccessPeekProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

const SHOWN = 4;

/** ⌘K › My access (DESIGN.md › access-peek): role, groups and a few held
 * capabilities from `/me/access`, with one way to the full page. Rules are not
 * listed: no self-service endpoint returns them, and the UI never reconstructs access. */
export function AccessPeek({ open, onOpenChange }: AccessPeekProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogPortal>
        <DialogBareOverlay className="fixed inset-0 z-40" />
        <DialogBareContent className="glass fixed inset-x-0 top-[11%] z-50 mx-auto w-[min(400px,calc(100vw-32px))] origin-top rounded-shell px-3.5 pb-3 pt-3.5 text-label text-body outline-none data-[state=closed]:animate-materialize-out data-[state=open]:animate-materialize-in">
          <PeekBody onOpenChange={onOpenChange} />
        </DialogBareContent>
      </DialogPortal>
    </Dialog>
  );
}

function PeekBody({ onOpenChange }: { onOpenChange: (open: boolean) => void }) {
  const view = useMyAccess();
  const access = view.access;
  if (!access) {
    return (
      <>
        <DialogTitle className="font-serif text-section text-ink">My access</DialogTitle>
        <DialogDescription className="mt-1 text-muted-foreground">
          {view.status === 'loading' ? 'Loading your access…' : "Couldn't load your access."}
        </DialogDescription>
      </>
    );
  }
  const held = access.capabilities.slice(0, SHOWN);
  return (
    <>
      <DialogTitle className="sr-only">My access</DialogTitle>
      <DialogDescription className="sr-only">
        Your role, groups and what you can do, from your sign-in.
      </DialogDescription>
      <div className="flex items-center gap-2.5">
        <Avatar name={access.display_name || access.email} />
        <div className="min-w-0 flex-1">
          <div className="truncate text-sm font-medium text-ink">
            {access.display_name || access.email}
          </div>
          <div className="truncate text-caption text-muted-foreground">{access.email}</div>
        </div>
        <RolePill role={access.role} />
      </div>
      <div className="mb-1.5 mt-3 font-medium text-ink">Groups</div>
      <GroupList groups={access.groups} />
      <div className="mb-1.5 mt-3 flex items-center font-medium text-ink">
        What you can do
        <span className="ml-auto text-caption font-normal text-muted-foreground">
          {held.length} of {access.capabilities.length}
        </span>
      </div>
      <ul className="overflow-hidden rounded-lg bg-card shadow-[0_0_0_1px_hsl(var(--border)/0.5)] [&>*+*]:border-t [&>*+*]:border-border/50">
        {held.map((c) => (
          <li key={c} className="px-3 py-2 font-mono text-xs text-ink">
            {c}
          </li>
        ))}
        <li className="px-3 py-2 text-caption text-muted-foreground">
          {access.has_data_access
            ? 'Your groups and grants cover data in the catalog.'
            : 'No data yet: no group or grant covers any data.'}
        </li>
      </ul>
      <div className="mt-2.5 flex items-center gap-2 px-0.5">
        <Tag dot>scope · from your sign-in</Tag>
        <Link
          to={ROUTES.access}
          onClick={() => onOpenChange(false)}
          className="ml-auto text-label font-medium text-primary-text hover:underline"
        >
          Open full page →
        </Link>
      </div>
    </>
  );
}
