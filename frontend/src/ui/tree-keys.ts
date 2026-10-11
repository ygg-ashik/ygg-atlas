// src/ui/tree-keys.ts
// Pure keyboard model for TreeList (WAI-ARIA tree pattern), kept apart so it can be
// tested without rendering.

export interface FlatNode {
  id: string;
  parentId: string | null;
  hasChildren: boolean;
}

export type TreeMove = { focus: string } | { toggle: string } | { activate: string };

function horizontal(key: string, node: FlatNode, next: FlatNode | undefined, expanded: boolean) {
  if (key === 'ArrowRight') {
    if (!node.hasChildren) return null;
    return expanded && next ? { focus: next.id } : { toggle: node.id };
  }
  if (node.hasChildren && expanded) return { toggle: node.id };
  return node.parentId ? { focus: node.parentId } : null;
}

/** What a key does on the node at `index` of the visible, flattened tree. */
export function treeMove(
  key: string,
  index: number,
  visible: readonly FlatNode[],
  isExpanded: (id: string) => boolean,
): TreeMove | null {
  const node = visible[index];
  if (!node) return null;
  const focus = (at: number) => {
    const target = visible[at];
    return target ? { focus: target.id } : null;
  };
  switch (key) {
    case 'ArrowDown':
      return focus(index + 1);
    case 'ArrowUp':
      return focus(index - 1);
    case 'Home':
      return focus(0);
    case 'End':
      return focus(visible.length - 1);
    case 'ArrowRight':
    case 'ArrowLeft':
      return horizontal(key, node, visible[index + 1], isExpanded(node.id));
    case 'Enter':
    case ' ':
      return { activate: node.id };
    default:
      return null;
  }
}
