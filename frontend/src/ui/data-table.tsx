// src/ui/data-table.tsx
import * as React from 'react';
import { ChevronRight } from 'lucide-react';
import { cn } from './utils';

export interface DataColumn<T> {
  key: string;
  header: React.ReactNode;
  cell: (row: T) => React.ReactNode;
  /** end: numeric columns, right-aligned. */
  align?: 'start' | 'end';
  /** Low-value columns may hide below 1200px. */
  hideBelowWide?: boolean;
}

export interface DataTableProps<T> {
  columns: readonly DataColumn<T>[];
  rows: readonly T[];
  rowKey: (row: T) => string;
  /** Accessible table name (rendered visually hidden). */
  caption: string;
  /** Clickable rows: focusable, open on click, Enter or Space. `label` names the
   * action for assistive tech, e.g. (u) => `Open ${u.name}`. */
  rowAction?: { label: (row: T) => string; onActivate: (row: T) => void };
  /** Expandable rows: detail (e.g. a DiffBlock) for the row whose key is `expandedKey`. */
  renderExpanded?: (row: T) => React.ReactNode;
  expandedKey?: string | null;
  onToggleExpand?: (key: string) => void;
  className?: string;
}

const CELL = 'px-3 first:pl-[18px] last:pr-[18px]';
const HIDE_MID = 'max-[1199px]:hidden';

interface RowProps<T> {
  row: T;
  id: string;
  columns: readonly DataColumn<T>[];
  expandable: boolean;
  open: boolean;
  onActivate?: () => void;
  /** Accessible name of a clickable row. */
  actionLabel?: string;
  detailId: string;
  detail: React.ReactNode;
}

function Row<T>(props: RowProps<T>) {
  const { row, id, columns, expandable, open, onActivate, actionLabel, detailId, detail } = props;
  const onKeyDown = (e: React.KeyboardEvent<HTMLTableRowElement>) => {
    if (e.target !== e.currentTarget || (e.key !== 'Enter' && e.key !== ' ')) return;
    e.preventDefault();
    onActivate?.();
  };
  return (
    <>
      <tr
        data-row-key={id}
        tabIndex={onActivate && !expandable ? 0 : undefined}
        aria-label={expandable ? undefined : actionLabel}
        onClick={onActivate}
        onKeyDown={onActivate && !expandable ? onKeyDown : undefined}
        className={cn(
          onActivate &&
            'cursor-pointer outline-none transition-colors duration-200 hover:bg-foreground/[0.03] focus-visible:bg-primary/5',
          open && '[&>td]:bg-card-2',
        )}
      >
        {expandable && (
          <td className={cn(CELL, 'w-6 py-[11px] text-muted-foreground')}>
            <button
              type="button"
              aria-expanded={open}
              aria-controls={open ? detailId : undefined}
              aria-label="Details"
              className="grid h-6 w-6 place-items-center rounded-full focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-primary/15"
            >
              <ChevronRight
                className={cn('h-3.5 w-3.5 transition-transform', open && 'rotate-90')}
              />
            </button>
          </td>
        )}
        {columns.map((c) => (
          <td
            key={c.key}
            className={cn(
              CELL,
              'py-[11px] align-middle text-body',
              c.align === 'end' && 'whitespace-nowrap text-right',
              c.hideBelowWide && HIDE_MID,
            )}
          >
            {c.cell(row)}
          </td>
        ))}
      </tr>
      {open && (
        <tr id={detailId}>
          <td className="bg-card-2" />
          <td colSpan={columns.length} className="bg-card-2 pb-3.5 pl-3 pr-[18px] pt-0">
            {detail}
          </td>
        </tr>
      )}
    </>
  );
}

/** Data table on a solid card (DESIGN.md › data-table): tabular figures, clickable
 * or expandable rows, and horizontal scroll below 1000px instead of squeezing. */
export function DataTable<T>({
  columns,
  rows,
  rowKey,
  caption,
  rowAction,
  renderExpanded,
  expandedKey = null,
  onToggleExpand,
  className,
}: DataTableProps<T>) {
  const tableId = React.useId();
  const expandable = Boolean(renderExpanded);
  const activate = (row: T, key: string) => {
    if (expandable) return () => onToggleExpand?.(key);
    return rowAction ? () => rowAction.onActivate(row) : undefined;
  };
  return (
    <div
      className={cn(
        'overflow-x-auto rounded-card bg-card shadow-[0_0_0_1px_hsl(var(--border)/0.6),0_1px_2px_rgba(0,0,0,0.04)]',
        className,
      )}
    >
      <table className="w-full border-collapse text-label tabular-nums max-[999px]:min-w-[760px]">
        <caption className="sr-only">{caption}</caption>
        <thead>
          <tr className="border-b border-border">
            {expandable && (
              <th scope="col" className={cn(CELL, 'w-6')}>
                <span className="sr-only">Details</span>
              </th>
            )}
            {columns.map((c) => (
              <th
                key={c.key}
                scope="col"
                className={cn(
                  CELL,
                  'whitespace-nowrap pb-2 pt-3 text-left text-xs font-medium text-muted-foreground',
                  c.align === 'end' && 'text-right',
                  c.hideBelowWide && HIDE_MID,
                )}
              >
                {c.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="[&>tr:not(:last-child)]:border-b [&>tr:not(:last-child)]:border-border/50">
          {rows.map((row) => {
            const key = rowKey(row);
            const open = expandable && key === expandedKey;
            return (
              <Row
                key={key}
                row={row}
                id={key}
                columns={columns}
                expandable={expandable}
                open={open}
                onActivate={activate(row, key)}
                actionLabel={rowAction?.label(row)}
                detailId={`${tableId}-${key.replace(/\s/g, '_')}-detail`}
                detail={open ? renderExpanded?.(row) : null}
              />
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
