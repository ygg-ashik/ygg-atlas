import { Lock } from 'lucide-react';
import { Link } from 'react-router-dom';
import type { DeniedBlock as DeniedBlockData } from '@/api/chat';
import { Button, Notice, Tag } from '@/ui';

/** The account feature's request form, prefilled. A URL keeps chat and account
 * decoupled (no cross-feature import). */
export function requestAccessHref(resource: string, label: string): string {
  return `/account/requests/new?${new URLSearchParams({ resource, label }).toString()}`;
}

/** A policy denial in an answer (DESIGN.md › notice-denied, guardrail #4): the
 * fact, why it can't be widened here, the exact scope to ask for, and the way to ask. */
export function DeniedBlock({ block }: { block: DeniedBlockData }) {
  return (
    <Notice
      className="my-3"
      icon={<Lock className="h-3.5 w-3.5" />}
      title={`${block.label} isn't available to your access`}
    >
      <p>
        Access comes from your sign-in, not from the question, so it can't be widened here. It needs{' '}
        <span className="font-mono text-xs text-ink">{block.resource}</span>; the managers of a
        group that holds it can approve a request.
      </p>
      <div className="mt-2.5 flex flex-wrap gap-1.5">
        <Tag dot>scope · from your Google sign-in</Tag>
      </div>
      <div className="mt-3">
        <Button asChild size="sm">
          <Link to={requestAccessHref(block.resource, block.label)}>Request access</Link>
        </Button>
      </div>
    </Notice>
  );
}
