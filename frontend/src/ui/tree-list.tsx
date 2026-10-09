// src/ui/tree-list.tsx
import * as React from 'react';
import { ChevronRight, Lock } from 'lucide-react';
import { type FlatNode, treeMove } from './tree-keys';
import { cn } from './utils';

export interface TreeNode {
  id: string;
  label: React.ReactNode;
  /** Muted text after the label (catalog names). */
  detail?: React.ReactNode;
  /** Mono count on the right (e.g. "4 · 2" members · grants). */
  count?: string;
  /** Right-aligned slot (e.g. an allow/deny pill with its origin). */
  trailing?: React.ReactNode;
  /** Visible but outside the viewer's scope: dimmed, lock glyph, not selectable. */
  locked?: boolean;
  children?: readonly TreeNode[];
}

export interface TreeListProps {
  nodes: readonly TreeNode[];
  /** Accessible name of the tree. */
  label: string;
  /** select: group tree (indent, selection) · outline: read-only catalog with guide lines. */
  variant?: 'select' | 'outline';
  selectedId?: string | null;
  onSelect?: (id: string) => void;
  className?: string;
}

function flatten(
  nodes: readonly TreeNode[],
  collapsed: ReadonlySet<string>,
  parentId: string | null = null,
): FlatNode[] {
  return nodes.flatMap((n) => {
    const kids = n.children ?? [];
    const self = { id: n.id, parentId, hasChildren: kids.length > 0 };
    return collapsed.has(n.id) ? [self] : [self, ...flatten(kids, collapsed, n.id)];
  });
}

interface Ctx {
  idBase: string;
  variant: 'select' | 'outline';
  selectedId: string | null;
  focusId: string | null;
  collapsed: ReadonlySet<string>;
  toggle: (id: string) => void;
  activate: (id: string) => void;
  setFocus: (id: string) => void;
  register: (id: string, el: HTMLLIElement | null) => void;
}

const ROW =
  'relative flex items-center gap-2 rounded-md px-2.5 py-[7px] text-[13.5px] text-body transition-[background-color,transform] duration-200';

function Disclosure({ node, expanded, ctx }: { node: TreeNode; expanded?: boolean; ctx: Ctx }) {
  const parent = (node.children ?? []).length > 0;
  return (
    <span
      aria-hidden
      className="grid w-3 shrink-0 place-items-center text-muted-2"
      onClick={(e) => {
        if (!parent) return;
        e.stopPropagation();
        ctx.toggle(node.id);
      }}
    >
      {parent ? (
        <ChevronRight className={cn('h-3 w-3 transition-transform', expanded && 'rotate-90')} />
      ) : (
        '·'
      )}
    </span>
  );
}

function RowContent({ node, labelId }: { node: TreeNode; labelId: string }) {
  return (
    <>
      <span id={labelId} className="min-w-0 truncate">
        {node.label}
      </span>
      {node.detail && (
        <span id={`${labelId}-detail`} className="truncate text-[12.5px] text-muted-foreground">
          {node.detail}
        </span>
      )}
      {node.locked && <Lock aria-hidden className="h-2.5 w-2.5 shrink-0 text-muted-foreground" />}
      {(node.count || node.trailing) && (
        <span className="ml-auto flex shrink-0 items-center gap-2">
          {node.trailing}
          {node.count && (
            <span className="font-mono text-[11px] text-muted-foreground">{node.count}</span>
          )}
        </span>
      )}
    </>
  );
}

function rowClass(node: TreeNode, ctx: Ctx): string {
  const select = ctx.variant === 'select';
  return cn(
    ROW,
    select && !node.locked && 'cursor-pointer hover:bg-foreground/[0.04] active:scale-[.98]',
    select && node.id === ctx.selectedId && 'bg-primary/10 text-ink hover:bg-primary/10',
    node.locked && 'cursor-default opacity-55',
  );
}

function Item({ node, depth, ctx }: { node: TreeNode; depth: number; ctx: Ctx }) {
  const kids = node.children ?? [];
  const expanded = kids.length > 0 ? !ctx.collapsed.has(node.id) : undefined;
  const select = ctx.variant === 'select';
  // Name the item by its own label (and detail) only, never its counts or subtree.
  const labelId = `${ctx.idBase}-${node.id.replace(/\s/g, '_')}`;
  return (
    <li
      ref={(el) => ctx.register(node.id, el)}
      role="treeitem"
      aria-labelledby={node.detail ? `${labelId} ${labelId}-detail` : labelId}
      aria-level={depth + 1}
      aria-expanded={expanded}
      aria-selected={select ? node.id === ctx.selectedId : undefined}
      aria-disabled={node.locked || undefined}
      aria-describedby={node.locked ? `${ctx.idBase}-locked` : undefined}
      tabIndex={node.id === ctx.focusId ? 0 : -1}
      onFocus={(e) => {
        e.stopPropagation();
        ctx.setFocus(node.id);
      }}
      onClick={(e) => {
        e.stopPropagation();
        ctx.activate(node.id);
      }}
      className="outline-none [&:focus-visible>div]:ring-4 [&:focus-visible>div]:ring-primary/15"
    >
      <div
        style={select ? { paddingLeft: 10 + depth * 18 } : undefined}
        className={rowClass(node, ctx)}
      >
        <Disclosure node={node} expanded={expanded} ctx={ctx} />
        <RowContent node={node} labelId={labelId} />
      </div>
      {expanded && (
        <ul
          role="group"
          className={cn(ctx.variant === 'outline' && 'ml-4 border-l border-border pl-1')}
        >
          {kids.map((k) => (
            <Item key={k.id} node={k} depth={depth + 1} ctx={ctx} />
          ))}
        </ul>
      )}
    </li>
  );
}

function lockedIds(nodes: readonly TreeNode[]): Set<string> {
  return new Set(
    nodes.flatMap((n) => [...(n.locked ? [n.id] : []), ...lockedIds(n.children ?? [])]),
  );
}

/** Tree list (DESIGN.md › tree-list): the group tree and the catalog outline.
 * Arrow keys follow the WAI-ARIA tree pattern; Enter/Space selects. */
export function TreeList({
  nodes,
  label,
  variant = 'select',
  selectedId = null,
  onSelect,
  className,
}: TreeListProps) {
  const idBase = React.useId();
  const [collapsed, setCollapsed] = React.useState<ReadonlySet<string>>(new Set());
  const [focused, setFocused] = React.useState<string | null>(null);
  const els = React.useRef(new Map<string, HTMLLIElement>());
  const visible = flatten(nodes, collapsed);
  const locked = React.useMemo(() => lockedIds(nodes), [nodes]);
  const ids = visible.map((n) => n.id);
  const fallback = selectedId && ids.includes(selectedId) ? selectedId : (ids[0] ?? null);
  const focusId = focused && ids.includes(focused) ? focused : fallback;

  const toggle = (id: string) =>
    setCollapsed((prev) => {
      const next = new Set(prev);
      if (!next.delete(id)) next.add(id);
      return next;
    });
  const activate = (id: string) => {
    if (variant === 'select' && !locked.has(id)) onSelect?.(id);
  };
  const ctx: Ctx = {
    idBase,
    variant,
    selectedId,
    focusId,
    collapsed,
    toggle,
    activate,
    setFocus: setFocused,
    register: (id, el) => {
      if (el) els.current.set(id, el);
      else els.current.delete(id);
    },
  };
  const onKeyDown = (e: React.KeyboardEvent) => {
    const move = treeMove(e.key, ids.indexOf(focusId ?? ''), visible, (id) => !collapsed.has(id));
    if (!move) return;
    e.preventDefault();
    if ('focus' in move) els.current.get(move.focus)?.focus();
    else if ('toggle' in move) toggle(move.toggle);
    else activate(move.activate);
  };
  return (
    <>
      <ul role="tree" aria-label={label} onKeyDown={onKeyDown} className={cn('p-2', className)}>
        {nodes.map((n) => (
          <Item key={n.id} node={n} depth={0} ctx={ctx} />
        ))}
      </ul>
      {locked.size > 0 && (
        <span id={`${idBase}-locked`} className="sr-only">
          Outside your scope
        </span>
      )}
    </>
  );
}
