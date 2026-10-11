import { render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { createQueryWrapper } from '@/api/hooks/test-query-wrapper';
import { type LabelClass } from '@/api/row-field';
import { apiMock } from '@/api/test-api-mock';
import { diffLines, fast } from './test-fixtures';
import { LabelClassesPanel } from './label-classes-panel';

vi.mock('@/api/axios-instance', () => apiMock);
const listLabelClasses = vi.hoisted(() => vi.fn());
const putLabelClass = vi.hoisted(() => vi.fn());
vi.mock('@/api/row-field', async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  listLabelClasses,
  putLabelClass,
}));

const label = (label_class: string, overrides: Partial<LabelClass> = {}): LabelClass => ({
  label_class,
  mode: 'suppress',
  bucket_size: 5,
  updated_at: '2026-10-01T00:00:00Z',
  ...overrides,
});

function renderPanel() {
  const { wrapper: Wrapper } = createQueryWrapper();
  render(
    <Wrapper>
      <LabelClassesPanel />
    </Wrapper>,
  );
  return fast();
}

describe('LabelClassesPanel', () => {
  beforeEach(() => {
    listLabelClasses
      .mockReset()
      .mockResolvedValue([label('business_name', { mode: 'pseudonymise' }), label('person_name')]);
    putLabelClass.mockReset().mockResolvedValue(label('person_name', { mode: 'bucket' }));
  });

  it('offers only the classes the backend lists (never category)', async () => {
    renderPanel();
    const list = await screen.findByRole('list', { name: 'Label classes' });
    expect(within(list).getAllByRole('listitem')).toHaveLength(2);
    expect(screen.getByRole('combobox', { name: 'Mode for business_name' })).toHaveValue(
      'pseudonymise',
    );
    expect(screen.getByRole('combobox', { name: 'Mode for person_name' })).toHaveValue('suppress');
    expect(screen.queryByText('category')).not.toBeInTheDocument();
  });

  it('a mode change is reviewed as label_class.update, then PUT', async () => {
    const user = renderPanel();
    const mode = await screen.findByRole('combobox', { name: 'Mode for person_name' });
    const [, review] = screen.getAllByRole('button', { name: 'Review change' });
    expect(review).toBeDisabled();
    await user.selectOptions(mode, 'bucket');
    const size = screen.getByRole('spinbutton', { name: 'Bucket size for person_name' });
    await user.clear(size);
    await user.type(size, '3');
    await user.click(screen.getAllByRole('button', { name: 'Review change' })[1]!);
    const card = screen.getByRole('region', { name: 'Masking · person_name' });
    expect(diffLines(card)).toEqual([
      ['context', 'label_class.update  person_name'],
      ['remove', 'mode      suppress'],
      ['add', 'mode      bucket'],
      ['remove', 'bucket    5'],
      ['add', 'bucket    3'],
      ['context', 'applies to every caller without the matching clearance'],
    ]);
    expect(putLabelClass).not.toHaveBeenCalled();
    await user.click(within(card).getByRole('button', { name: 'Apply masking' }));
    await waitFor(() =>
      expect(putLabelClass).toHaveBeenCalledWith('person_name', { mode: 'bucket', bucket_size: 3 }),
    );
  });

  it('an out-of-range bucket size cannot be reviewed', async () => {
    const user = renderPanel();
    await user.selectOptions(
      await screen.findByRole('combobox', { name: 'Mode for person_name' }),
      'bucket',
    );
    const size = screen.getByRole('spinbutton', { name: 'Bucket size for person_name' });
    await user.clear(size);
    await user.type(size, '51');
    expect(size).toHaveAttribute('aria-invalid', 'true');
    expect(screen.getAllByRole('button', { name: 'Review change' })[1]).toBeDisabled();
  });

  it('a load failure is stated with Retry', async () => {
    listLabelClasses.mockRejectedValue(new Error('down'));
    renderPanel();
    expect(await screen.findByText("Couldn't load label classes")).toBeInTheDocument();
  });
});
