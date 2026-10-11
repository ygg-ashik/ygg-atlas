import { render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { type CatalogResources } from '@/api/catalog-admin';
import { createQueryWrapper } from '@/api/hooks/test-query-wrapper';
import { type ScopeDimension } from '@/api/row-field';
import { httpError } from '@/api/test-support';
import { plusDays, todayUtc } from '../grant-rules';
import { CATALOG, diffLines, fast, grant } from './test-fixtures';
import { GrantEditor, type GrantEditorProps } from './grant-editor';

const createGrant = vi.hoisted(() => vi.fn());
vi.mock('@/api/admin-groups', () => ({ createGrant }));
const fetchCatalogResources = vi.hoisted(() => vi.fn());
vi.mock('@/api/catalog-admin', () => ({ fetchCatalogResources }));
const listScopeDimensions = vi.hoisted(() => vi.fn());
vi.mock('@/api/row-field', () => ({ listScopeDimensions }));
const fetchCapabilityCatalog = vi.hoisted(() => vi.fn());
vi.mock('@/api/access', () => ({ fetchCapabilityCatalog }));

const RESOURCES: CatalogResources = {
  sources: [
    {
      id: 'demo',
      name: 'Demo commerce',
      entities: [
        {
          path: 'demo/checkout',
          name: 'Checkout journey',
          items: [
            {
              path: 'demo/checkout/checkout_funnel',
              id: 'checkout_funnel',
              name: 'Checkout funnel',
              kind: 'funnel',
            },
          ],
        },
      ],
    },
  ],
};

const DIMENSIONS: ScopeDimension[] = [
  {
    source: 'demo',
    entity: 'checkout',
    dimension: 'country',
    self_attribute: null,
    description: 'Shopper country',
  },
  {
    source: 'demo',
    entity: 'order',
    dimension: 'csm',
    self_attribute: 'csm',
    description: 'Account manager',
  },
];

const GROUP: GrantEditorProps = {
  subject: { type: 'group', id: 'g-m', label: 'group:marketing' },
  reach: 'reaches 5 members + marketing-paid',
  denyNotice: 'Everyone in marketing and its subgroups',
  restrictCount: 5,
  onClose: () => {},
};
const USER: GrantEditorProps = {
  subject: { type: 'user', id: 'omar', label: 'user:omar@' },
  onClose: () => {},
};

function renderEditor(props: GrantEditorProps = GROUP) {
  const { wrapper: Wrapper } = createQueryWrapper();
  render(
    <Wrapper>
      <GrantEditor {...props} />
    </Wrapper>,
  );
}

async function pickTarget(text: string, option: RegExp) {
  await fast().click(await screen.findByRole('combobox', { name: 'Target' }));
  await fast().paste(text);
  await fast().click(await screen.findByRole('option', { name: option }));
}

const review = () => screen.getByRole('button', { name: 'Review change' });

describe('GrantEditor', () => {
  beforeEach(() => {
    createGrant.mockReset();
    createGrant.mockResolvedValue(grant('new'));
    fetchCatalogResources.mockResolvedValue(RESOURCES);
    listScopeDimensions.mockResolvedValue(DIMENSIONS);
    fetchCapabilityCatalog.mockResolvedValue(CATALOG);
  });

  it('needs a catalog target, then shows the exact grant.create before applying', async () => {
    renderEditor();
    expect(review()).toBeDisabled();
    await pickTarget('checkout', /Checkout journey · all/);
    await fast().click(review());
    const card = screen.getByRole('region', { name: 'Add grant · group:marketing' });
    const expiry = plusDays(todayUtc(), 90);
    expect(diffLines(card)).toEqual([
      ['context', 'grant.create  group:marketing'],
      ['add', 'effect    allow'],
      ['add', 'target    demo/checkout/*'],
      ['add', `expires   ${expiry}`],
      ['context', 'scope     all rows'],
      ['context', 'reaches 5 members + marketing-paid'],
    ]);
    expect(createGrant).not.toHaveBeenCalled();
    await fast().click(within(card).getByRole('button', { name: 'Apply grant' }));
    expect(createGrant).toHaveBeenCalledWith({
      subject_type: 'group',
      subject_id: 'g-m',
      effect: 'allow',
      target_kind: 'resource',
      target: 'demo/checkout/*',
      reason: '',
      expires_at: `${expiry}T00:00:00Z`,
    });
    await waitFor(() => expect(card).toHaveAttribute('data-status', 'applied'));
  });

  it('a deny needs explicit confirmation', async () => {
    renderEditor();
    await pickTarget('checkout', /Checkout journey · all/);
    await fast().click(screen.getByRole('radio', { name: /Deny/ }));
    expect(screen.getByText('A deny wins over every allow')).toBeInTheDocument();
    expect(review()).toBeDisabled();
    await fast().click(
      screen.getByRole('checkbox', { name: 'I understand this restricts 5 members' }),
    );
    expect(review()).toBeEnabled();
  });

  it('a direct user grant needs a reason', async () => {
    renderEditor(USER);
    await pickTarget('funnel', /Checkout funnel/);
    await fast().click(review());
    expect(screen.getByText('Direct user grants need a reason.')).toBeInTheDocument();
    expect(screen.queryByRole('region', { name: /Add grant ·/ })).not.toBeInTheDocument();
    await fast().type(screen.getByRole('textbox', { name: /Reason/ }), 'Funnel QA');
    await fast().click(review());
    expect(screen.getByRole('region', { name: 'Add grant · user:omar@' })).toBeInTheDocument();
  });

  it('the expiry must be a future date', async () => {
    renderEditor();
    await pickTarget('checkout', /Checkout journey · all/);
    const expiry = screen.getByRole('textbox', { name: /Expiry/ });
    await fast().clear(expiry);
    await fast().type(expiry, '2020-01-01');
    await fast().click(review());
    expect(screen.getByText('The expiry must be in the future.')).toBeInTheDocument();
    await fast().click(screen.getByRole('button', { name: 'Never' }));
    await fast().click(review());
    expect(diffLines(screen.getByRole('region', { name: /Add grant ·/ }))).toContainEqual([
      'add',
      'expires   —',
    ]);
  });

  it('a duplicate grant (409) is final: the sentence, no Retry', async () => {
    createGrant.mockRejectedValue(httpError(409, { detail: 'That grant already exists.' }));
    renderEditor();
    await pickTarget('checkout', /Checkout journey · all/);
    await fast().click(review());
    const card = screen.getByRole('region', { name: /Add grant ·/ });
    await fast().click(within(card).getByRole('button', { name: 'Apply grant' }));
    expect(await within(card).findByText('That grant already exists.')).toBeInTheDocument();
    expect(card).toHaveAttribute('data-status', 'open');
  });

  it('a row scope from /meta/scope-dimensions rides on a resource allow', async () => {
    renderEditor();
    await pickTarget('checkout', /Checkout journey · all/);
    expect(screen.queryByText('Arrives with row and field controls')).not.toBeInTheDocument();
    const dimension = await screen.findByRole('combobox', { name: 'Dimension' });
    expect(
      within(dimension)
        .getAllByRole('option')
        .map((o) => o.textContent),
    ).toEqual(['Dimension', 'country', 'csm']);
    await fast().selectOptions(dimension, 'country');
    await fast().type(screen.getByRole('textbox', { name: 'Values' }), 'AE, SA, AE');
    await fast().click(screen.getByRole('button', { name: 'Add' }));
    await fast().click(review());
    const card = screen.getByRole('region', { name: 'Add grant · group:marketing' });
    expect(diffLines(card)).toContainEqual(['add', 'scope     country=AE,SA']);
    await fast().click(within(card).getByRole('button', { name: 'Apply grant' }));
    expect(createGrant).toHaveBeenCalledWith(
      expect.objectContaining({ target: 'demo/checkout/*', row_scope: { country: ['AE', 'SA'] } }),
    );
  });

  it('a deny carries no row scope: the builder is replaced by a note', async () => {
    renderEditor();
    await screen.findByRole('combobox', { name: 'Dimension' });
    await fast().click(screen.getByRole('radio', { name: /Deny/ }));
    expect(screen.queryByRole('combobox', { name: 'Dimension' })).not.toBeInTheDocument();
    expect(screen.getByText(/Row scope narrows a resource allow only/)).toBeInTheDocument();
  });

  it('a clearance picker whose catalog fails says so with Retry', async () => {
    fetchCapabilityCatalog.mockRejectedValue(httpError(503));
    renderEditor();
    expect(await screen.findByText("Couldn't load clearances")).toBeInTheDocument();
  });

  it('a clearance grant comes from the catalog and is reviewed as a clearance', async () => {
    renderEditor();
    const picker = await screen.findByRole('combobox', { name: 'Clearance' });
    await waitFor(() => expect(picker).toBeEnabled());
    await fast().selectOptions(picker, 'fields:people_names');
    expect(screen.getByText("See people's names in clear")).toBeInTheDocument();
    await fast().click(review());
    const card = screen.getByRole('region', { name: 'Add grant · group:marketing' });
    expect(diffLines(card)).toContainEqual(['add', 'clearance fields:people_names']);
    await fast().click(within(card).getByRole('button', { name: 'Apply grant' }));
    expect(createGrant).toHaveBeenCalledWith(
      expect.not.objectContaining({ row_scope: expect.anything() }),
    );
    expect(createGrant).toHaveBeenCalledWith(
      expect.objectContaining({ target_kind: 'clearance', target: 'fields:people_names' }),
    );
  });

  it('scope dimensions that fail to load: Retry, and a resource allow cannot be staged', async () => {
    listScopeDimensions.mockRejectedValue(httpError(503));
    renderEditor();
    await pickTarget('checkout', /Checkout journey · all/);
    expect(await screen.findByText("Couldn't load scope dimensions")).toBeInTheDocument();
    expect(review()).toBeDisabled();
    await fast().click(screen.getByRole('radio', { name: /Deny/ }));
    await fast().click(
      screen.getByRole('checkbox', { name: 'I understand this restricts 5 members' }),
    );
    expect(review()).toBeEnabled();
  });

  it('while scope dimensions load, a resource allow cannot be staged', async () => {
    listScopeDimensions.mockReturnValue(new Promise(() => {}));
    renderEditor();
    await pickTarget('checkout', /Checkout journey · all/);
    expect(review()).toBeDisabled();
  });
});
