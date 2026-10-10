// Public interface of the ui layer — shadcn-style primitives + cn().
export { cn } from './utils';
export { Button, buttonVariants, type ButtonProps } from './button';
export { Input, type InputProps } from './input';
export { Separator } from './separator';
export { Tooltip, TooltipTrigger, TooltipContent, TooltipProvider } from './tooltip';
export {
  Dialog,
  DialogTrigger,
  DialogPortal,
  DialogClose,
  DialogOverlay,
  DialogContent,
  DialogBareOverlay,
  DialogBareContent,
  DialogHeader,
  DialogFooter,
  DialogTitle,
  DialogDescription,
} from './dialog';
export {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuGroup,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuCheckboxItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
} from './dropdown-menu';
export { ScrollArea, ScrollBar } from './scroll-area';
export { BrandMark, type BrandMarkProps } from './brand-mark';
export { Glass, type GlassProps } from './glass';
export { Toolbar, ToolbarCrumb } from './toolbar';
export { Popover, PopoverTrigger, PopoverAnchor, PopoverContent } from './popover';
export { Toaster, toast } from './toaster';
export {
  EASE_OUT,
  EASE_SHEET,
  durations,
  materialize,
  springDefault,
  springMomentum,
  withReducedMotion,
} from './motion';
export { PresetCard, type PresetPreview } from './preset-card';

// Admin and self-service primitives (DESIGN.md › Admin and self-service).
export { StatusPill, StandingPill, type StatusPillProps, type StatusTone } from './status-pill';
export { RolePill } from './role-pill';
export { Tag, type TagProps } from './tag';
export { DataTable, type DataColumn, type DataTableProps } from './data-table';
export { FilterBar, type FilterBarProps } from './filter-bar';
export { Field, FieldError, type FieldProps } from './field';
export { Select } from './select';
export { Textarea } from './textarea';
export { Checkbox, type CheckboxProps } from './checkbox';
export { DateField, isIsoDate, type DateFieldProps } from './date-field';
export {
  SegmentedControl,
  tabId,
  tabPanelId,
  type SegmentOption,
  type SegmentedControlProps,
} from './segmented-control';
export { RadioList, type RadioListOption, type RadioListProps } from './radio-list';
export { TreeList, type TreeNode, type TreeListProps } from './tree-list';
export { Morph, type MorphProps } from './morph';
export { DiffBlock, type DiffKind, type DiffLine } from './diff-block';
export { ReviewCard, type ReviewCardProps, type ReviewStatus } from './review-card';
export { SecretReveal, type SecretRevealProps } from './secret-reveal';
export { EmptyState, type EmptyStateProps } from './empty-state';
export { Skeleton, SkeletonRegion, SkeletonRows, type SkeletonProps } from './skeleton';
export { Notice, type NoticeProps } from './notice';
export { ErrorNotice, type ErrorNoticeProps } from './error-notice';
export { RouteGuardPage, type RouteGuardPageProps } from './route-guard-page';
export { CatalogCombobox, type CatalogOption, type CatalogComboboxProps } from './catalog-combobox';
export { Avatar, initials, type AvatarProps } from './avatar';
export { SidebarSectionHeader } from './sidebar-section-header';
export { CountBadge, type CountBadgeProps } from './count-badge';
export { UserChip, type UserChipProps } from './user-chip';
export { actionToast, type ActionToastOptions } from './action-toast';
export { SeriesSwatch, seriesFill, type Series } from './series-swatch';
