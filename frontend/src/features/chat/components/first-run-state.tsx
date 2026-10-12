import type { ReactNode } from 'react';
import { Lock } from 'lucide-react';
import { newRequestPath } from '@/lib/routes';
import { EmptyState, Tag } from '@/ui';
import { RequestAccessButton } from './request-access-button';

interface FirstRunStateProps {
  /** Display name, or '' while the backend has none. */
  name: string;
  email: string;
  /** The centered composer: questions about Atlas itself still work. */
  composer: ReactNode;
}

const FIRST_REQUEST = { kind: 'group' } as const;

/** A signed-in viewer with no data access (DESIGN.md › first-run-empty-state):
 * the chat says so plainly and offers the request in place. */
export function FirstRunState({ name, email, composer }: FirstRunStateProps) {
  const first = name.trim().split(/\s+/)[0] || email.split('@')[0];
  return (
    <div className="mx-auto max-w-[620px] px-6 pb-10 pt-[15vh]">
      <h2 className="text-center font-serif text-display font-normal text-ink">
        Welcome to Atlas, {first}
      </h2>
      <p className="mb-[22px] mt-1.5 text-center text-muted-foreground">
        You&apos;re signed in. One step before Atlas can answer.
      </p>
      <EmptyState
        className="px-6 pb-[26px] pt-[30px]"
        icon={<Lock className="h-5 w-5" />}
        title="No data access yet"
        actions={<RequestAccessButton to={newRequestPath(FIRST_REQUEST)} prefill={FIRST_REQUEST} />}
      >
        No group or grant covers any data for <b className="font-medium text-ink">{email}</b> yet,
        so metric questions would be denied. Ask for the group your team uses; its managers decide.
      </EmptyState>
      <div className="mt-3.5 flex justify-center">
        <Tag dot>scope · from your Google sign-in</Tag>
      </div>
      <div className="mt-8">{composer}</div>
    </div>
  );
}
