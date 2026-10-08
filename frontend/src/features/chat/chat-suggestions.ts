// Preset analyses for the empty chat (Higgsfield-style gallery). Static and
// curated; each preset sends its question.
import type { PresetPreview } from '@/ui';

export interface ChatPreset {
  title: string;
  description: string;
  preview: PresetPreview;
  question: string;
}

export const CHAT_PRESETS: ChatPreset[] = [
  {
    title: 'Revenue review',
    description: 'Last week, with drivers',
    preview: 'line',
    question: 'What was revenue last week?',
  },
  {
    title: 'Account health',
    description: 'Who is at risk',
    preview: 'bars',
    question: 'How many accounts are currently at risk?',
  },
  {
    title: 'CSM workload',
    description: 'Open tasks by CSM',
    preview: 'bars',
    question: 'How are open tasks distributed across CSMs?',
  },
  {
    title: 'Checkout funnel',
    description: 'Where users drop off',
    preview: 'funnel',
    question: 'Where do users drop off in checkout?',
  },
];
