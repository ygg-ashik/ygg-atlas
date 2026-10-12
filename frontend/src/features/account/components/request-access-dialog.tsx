import { useState } from 'react';
import { useMyAccess } from '@/api/hooks/use-my-access';
import { type RequestPrefill } from '@/lib/routes';
import { Dialog, DialogContent, DialogDescription, DialogTitle } from '@/ui';
import { useRequestForm } from '../hooks/use-request-form';
import { initialRequest } from '../request-rules';
import { RequestForm } from './request-form';

interface RequestAccessDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** From a chat denial, a guard or ⌘K; read once when the dialog opens. */
  prefill?: RequestPrefill;
}

/** The New request form in a dialog, over whatever the user was doing (⌘K
 * quick action, a chat denial, the first-run empty state). Same form and hook
 * as the page, so the two never drift. */
export function RequestAccessDialog({ open, onOpenChange, prefill }: RequestAccessDialogProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[80vh] w-[min(560px,calc(100%-40px))] overflow-y-auto">
        {/* Content mounts on open and unmounts after its exit, so each opening starts fresh. */}
        <DialogBody prefill={prefill ?? {}} onClose={() => onOpenChange(false)} />
      </DialogContent>
    </Dialog>
  );
}

function DialogBody({ prefill, onClose }: { prefill: RequestPrefill; onClose: () => void }) {
  // Read once: the form owns its state after the first render.
  const [initial] = useState(() => initialRequest(prefill));
  const role = useMyAccess().access?.role ?? '';
  const form = useRequestForm(initial, role);
  return (
    <>
      <div className="pr-8">
        <DialogTitle>{initial.label ? `Request ${initial.label}` : 'Request access'}</DialogTitle>
        <DialogDescription className="mt-1">
          Approvers see your note. Nothing changes until someone approves it.
        </DialogDescription>
      </div>
      <RequestForm form={form} label={initial.label} currentRole={role} onCancel={onClose} />
    </>
  );
}
