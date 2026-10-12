// src/features/layout/types.ts
// What App.tsx composes into the shell. Layout decides nothing about access:
// every list here is already filtered by the backend's `/me/access` answer.
import type { LucideIcon } from 'lucide-react';

export interface NavBadge {
  count: number;
  /** What is counted, for screen readers: "requests to decide". */
  label: string;
}

export interface NavItem {
  to: string;
  label: string;
  icon: LucideIcon;
  badge?: NavBadge;
}

/** A titled group of the settings rail ("You", "Organization"). */
export interface NavSection {
  title: string;
  items: NavItem[];
}

export interface ShellUser {
  name: string;
  email: string;
  avatar: string;
  /** The role from the backend's `/me/access`; omitted until it answers. */
  role?: string;
}

/** The account menu's Admin entry, offered to managers and admins only. */
export interface AdminEntry {
  to: string;
  /** Requests the viewer can decide; the chip shows a dot and the item a badge. */
  pendingApprovals: number;
}
