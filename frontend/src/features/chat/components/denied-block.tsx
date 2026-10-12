import { Lock } from 'lucide-react';
import type { DeniedBlock as DeniedBlockData } from '@/api/chat';
import { deniedRequestPath } from '@/lib/routes';
import { Notice, Tag } from '@/ui';
import { RequestAccessButton } from './request-access-button';

/** A policy denial in an answer (DESIGN.md › notice-denied, guardrail #4): the
 * fact, why it can't be widened here, the exact scope to ask for, and the way to
 * ask: the request dialog over the chat, prefilled with this resource. */
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
        <RequestAccessButton
          size="sm"
          to={deniedRequestPath(block.resource, block.label)}
          prefill={{ resource: block.resource, label: block.label }}
        />
      </div>
    </Notice>
  );
}
