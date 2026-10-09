import { useState } from 'react';
import { SegmentedControl, tabId, tabPanelId } from '@/ui';
import { AdminPage } from './admin-page';
import { AuditSummary } from './audit-summary';
import { ChangesTable } from './changes-table';
import { CredentialsTable } from './credentials-table';
import { DecisionsTable } from './decisions-table';

type Tab = 'changes' | 'decisions' | 'credentials' | 'summary';
const TABS_ID = 'audit';
const TABS = [
  { value: 'changes', label: 'Changes' },
  { value: 'decisions', label: 'Decisions' },
  { value: 'credentials', label: 'Credentials' },
  { value: 'summary', label: 'Summary' },
] as const;

/** Only the open tab mounts, so only its log is fetched. */
function Panel({ tab }: { tab: Tab }) {
  switch (tab) {
    case 'changes':
      return <ChangesTable />;
    case 'decisions':
      return <DecisionsTable />;
    case 'credentials':
      return <CredentialsTable />;
    case 'summary':
      return <AuditSummary />;
  }
}

/** Screen 11 · Audit (admin:audit): who changed access, every allow or deny
 * the atlas tools made, credential events and a deny summary. */
export function AuditPage() {
  const [tab, setTab] = useState<Tab>('changes');
  return (
    <AdminPage
      title="Audit"
      heading="Audit"
      sub="Who changed access, and every allow or deny the atlas tools made. Times are UTC."
    >
      <SegmentedControl
        className="mb-3.5"
        label="Audit logs"
        idBase={TABS_ID}
        value={tab}
        onChange={setTab}
        options={TABS}
      />
      <div role="tabpanel" id={tabPanelId(TABS_ID, tab)} aria-labelledby={tabId(TABS_ID, tab)}>
        <Panel tab={tab} />
      </div>
    </AdminPage>
  );
}
