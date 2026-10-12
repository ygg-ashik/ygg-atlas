import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { type CapabilityCatalog } from '@/api/access';
import { type MyAccessView } from '@/api/hooks/use-my-access';
import { accessView, PERSONAS } from '@/test/access-view';
import { MyAccessPage } from './my-access-page';

const state = vi.hoisted(() => ({ view: null as unknown as MyAccessView }));
vi.mock('@/api/hooks/use-my-access', () => ({ useMyAccess: () => state.view }));
const fetchCapabilityCatalog = vi.hoisted(() => vi.fn<() => Promise<CapabilityCatalog>>());
vi.mock('@/api/access', () => ({ fetchCapabilityCatalog }));

const CATALOG: CapabilityCatalog = {
  capabilities: [
    { code: 'chat:use', description: 'Ask Atlas questions in chat' },
    { code: 'mcp:use', description: 'Use Atlas from MCP clients' },
    { code: 'tokens:create', description: 'Create personal access tokens' },
  ],
  roles: [
    { name: 'viewer', capabilities: ['chat:use'] },
    { name: 'analyst', capabilities: ['chat:use', 'mcp:use', 'tokens:create'] },
  ],
  clearances: [
    { code: 'fields:business_names', description: 'See business names in clear' },
    { code: 'fields:people_names', description: "See people's names in clear" },
  ],
  label_classes: ['category', 'business_name', 'person_name'],
  mask_modes: ['pseudonymise', 'suppress', 'bucket'],
};

function renderPage(entry = '/settings/access') {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[entry]}>
        <MyAccessPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('MyAccessPage', () => {
  beforeEach(() => {
    fetchCapabilityCatalog.mockReset().mockResolvedValue(CATALOG);
  });

  it('a new viewer sees "No data access yet" with a way to request it', async () => {
    state.view = PERSONAS.newViewer;
    renderPage();
    expect(screen.getByRole('heading', { level: 2, name: 'My access' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'No data access yet' })).toBeInTheDocument();
    expect(screen.getByText('lina@yougotagift.com', { selector: 'b' })).toBeInTheDocument();
    const links = screen.getAllByRole('link', { name: /Request access/ });
    expect(links.map((l) => l.getAttribute('href'))).toContain('/settings/requests/new?kind=group');
    expect(screen.getByText('None yet. Groups decide what data you can see.')).toBeInTheDocument();
    // What the next role adds, with a role request.
    expect(await screen.findByText('tokens:create')).toBeInTheDocument();
    expect(screen.getAllByText(/Comes with analyst/)).toHaveLength(2);
    expect(screen.getByRole('link', { name: 'Request analyst' })).toHaveAttribute(
      'href',
      '/settings/requests/new?kind=role',
    );
  });

  it('with data access, lists capabilities and groups with their standing', async () => {
    state.view = accessView({
      has_data_access: true,
      groups: [
        { id: 'g1', name: 'marketing', standing: 'manager' },
        { id: 'g2', name: 'marketing-paid', standing: 'member' },
      ],
      pending_requests: 2,
    });
    renderPage();
    expect(screen.queryByText('No data access yet')).not.toBeInTheDocument();
    expect(await screen.findByText('Ask Atlas questions in chat')).toBeInTheDocument();
    const groups = screen.getByRole('list', { name: 'Groups' });
    const items = within(groups).getAllByRole('listitem');
    expect(items[0]).toHaveTextContent('marketingmanager');
    expect(items[1]).toHaveTextContent('marketing-paidmember');
    expect(screen.getByRole('link', { name: /2 pending requests/ })).toHaveAttribute(
      'href',
      '/settings/requests',
    );
  });

  it('lists the clearances from /me/access', () => {
    state.view = accessView({ has_data_access: true, clearances: ['fields:people_names'] });
    renderPage();
    expect(screen.queryByText('Arrives with row and field controls')).not.toBeInTheDocument();
    expect(screen.getByText('fields:people_names')).toBeInTheDocument();
  });

  it('no clearances: says names may show masked', () => {
    state.view = PERSONAS.viewer;
    renderPage();
    expect(screen.getByText(/None · names in answers may show masked/)).toBeInTheDocument();
  });

  it('a failed capability catalog says so with a retry; the codes still show', async () => {
    state.view = PERSONAS.viewer;
    fetchCapabilityCatalog.mockRejectedValue(new Error('503'));
    renderPage();
    expect(await screen.findByRole('alert')).toHaveTextContent(
      "Couldn't load capability descriptions",
    );
    expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument();
    expect(screen.getByText('chat:use')).toBeInTheDocument();
  });
});
