import { useState } from 'react';
import { useLabelClasses, usePutLabelClass } from '@/api/hooks/use-row-field';
import { MAX_BUCKET_SIZE, type LabelClass, type MaskMode } from '@/api/row-field';
import { Button, ErrorNotice, Input, Select, SkeletonRegion, SkeletonRows } from '@/ui';
import { useReviewedWrite, type ReviewedWrite } from '../hooks/use-reviewed-write';
import { LABEL_CLASS_UPDATE, labelClassLines } from '../review-lines';
import { ReviewSlot } from './review-slot';
import { CARD } from './surfaces';

const MODES: { value: MaskMode; label: string }[] = [
  { value: 'suppress', label: 'Suppress' },
  { value: 'pseudonymise', label: 'Pseudonymise' },
  { value: 'bucket', label: 'Bucket' },
];

const isMaskMode = (value: string): value is MaskMode => MODES.some((m) => m.value === value);

interface RowProps {
  current: LabelClass;
  write: ReviewedWrite;
}

function LabelClassRow({ current, write }: RowProps) {
  const put = usePutLabelClass();
  const [mode, setMode] = useState<MaskMode>(current.mode);
  const [size, setSize] = useState(String(current.bucket_size));
  const bucket = Number(size);
  const sizeValid = Number.isInteger(bucket) && bucket >= 1 && bucket <= MAX_BUCKET_SIZE;
  const sizeChanged = mode === 'bucket' && bucket !== current.bucket_size;
  const changed = mode !== current.mode || sizeChanged;
  const slot = `label:${current.label_class}`;
  const stage = () => {
    const body = { mode, ...(sizeChanged ? { bucket_size: bucket } : {}) };
    write.open({
      slot,
      title: `Masking · ${current.label_class}`,
      auditAction: LABEL_CLASS_UPDATE,
      lines: labelClassLines(current, body),
      applyLabel: 'Apply masking',
      run: () => put.mutateAsync({ labelClass: current.label_class, body }),
    });
  };
  return (
    <li className="px-5 py-3 [&:not(:last-child)]:border-b border-border/50">
      <div className="flex flex-wrap items-center gap-2.5">
        <span className="min-w-[140px] font-mono text-label text-ink">{current.label_class}</span>
        <Select
          aria-label={`Mode for ${current.label_class}`}
          value={mode}
          onChange={(e) => {
            if (isMaskMode(e.target.value)) setMode(e.target.value);
            write.dismiss();
          }}
        >
          {MODES.map((m) => (
            <option key={m.value} value={m.value}>
              {m.label}
            </option>
          ))}
        </Select>
        {mode === 'bucket' && (
          <Input
            aria-label={`Bucket size for ${current.label_class}`}
            aria-invalid={!sizeValid || undefined}
            className="w-20 tabular-nums"
            type="number"
            min={1}
            max={MAX_BUCKET_SIZE}
            value={size}
            onChange={(e) => setSize(e.target.value)}
          />
        )}
        <Button
          variant="pill"
          size="sm"
          className="ml-auto"
          disabled={!changed || (mode === 'bucket' && !sizeValid)}
          onClick={stage}
        >
          Review change
        </Button>
      </div>
      <ReviewSlot write={write} slot={slot} />
    </li>
  );
}

/** How masked labels show to callers without the matching clearance. The rows
 * are exactly the classes the backend lets an admin set (`/admin/label-classes`);
 * every change is reviewed first. */
export function LabelClassesPanel() {
  const classes = useLabelClasses();
  const write = useReviewedWrite();
  return (
    <section aria-label="Label masking" className="mt-6">
      <h3 className="font-serif text-title text-ink">Label masking</h3>
      <p className="mb-3 mt-0.5 text-caption text-muted-foreground">
        How names show in breakdowns for people without the matching clearance. Suppress drops those
        rows, pseudonymise shows stable aliases, bucket shows Top 1..N and sums the rest into
        Others.
      </p>
      {classes.isPending && (
        <SkeletonRegion label="label classes" className={CARD}>
          <SkeletonRows count={2} />
        </SkeletonRegion>
      )}
      {classes.isError && (
        <ErrorNotice
          title="Couldn't load label classes"
          onRetry={() => void classes.refetch()}
          retrying={classes.isFetching}
        />
      )}
      {classes.data && (
        <ul aria-label="Label classes" className={CARD}>
          {classes.data.map((c) => (
            <LabelClassRow
              key={`${c.label_class}:${c.mode}:${c.bucket_size}`}
              current={c}
              write={write}
            />
          ))}
        </ul>
      )}
    </section>
  );
}
