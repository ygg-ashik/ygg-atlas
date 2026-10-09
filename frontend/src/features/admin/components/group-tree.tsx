import { type Group } from '@/api/admin-groups';
import { TreeList, type TreeNode } from '@/ui';
import { buildGroupTree, type GroupTreeNode } from '../group-tree';
import { CARD } from './surfaces';

const toNode = ({ group, children }: GroupTreeNode): TreeNode => ({
  id: group.id,
  label: <span className="font-mono text-[12.5px] text-ink">{group.name}</span>,
  children: children.map(toNode),
});

interface GroupTreeProps {
  groups: readonly Group[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}

/** The group tree on a solid card (DESIGN.md › tree-list). */
export function GroupTree({ groups, selectedId, onSelect }: GroupTreeProps) {
  return (
    <div className={`${CARD} self-start py-1.5`}>
      <p className="px-[18px] pb-0.5 pt-2.5 text-label font-medium text-ink">Groups</p>
      <TreeList
        label="Groups"
        nodes={buildGroupTree(groups).map(toNode)}
        selectedId={selectedId}
        onSelect={onSelect}
      />
    </div>
  );
}
