import { useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useMyAccess } from '@/api/hooks/use-my-access';
import { useRequestForm } from '../hooks/use-request-form';
import { initialRequest, prefillFromParams } from '../request-rules';
import { AccountPage } from './account-page';
import { RequestForm } from './request-form';
import { ROUTES } from '@/lib/routes';

/** Screen 2 · New request. Honours `?kind=` (the consent denial sends `role`)
 * and `?resource=&label=` (a chat denial). */
export function NewRequestPage() {
  const [params] = useSearchParams();
  // Read once: the form owns its state after the first render.
  const [initial] = useState(() => initialRequest(prefillFromParams(params)));
  const role = useMyAccess().access?.role ?? '';
  const form = useRequestForm(initial, role);
  return (
    <AccountPage
      title="New request"
      crumb={{ to: ROUTES.requests, label: 'Requests' }}
      heading="Request access"
      sub="Requests go to the people who can decide them. You'll see the answer under Requests."
    >
      <RequestForm form={form} label={initial.label} currentRole={role} />
    </AccountPage>
  );
}
