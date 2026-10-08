import { useNavigate, useSearchParams } from 'react-router-dom';
import { useOverview } from '@/api/hooks/use-overview';
import type { Overview, OverviewDays } from '@/api/overview';
import { PresetCard, type PresetPreview, Toolbar } from '@/ui';
import { BreakdownCard } from './breakdown-card';
import { KpiCard } from './kpi-card';
import { RangeSwitch } from './range-switch';

interface Preset {
  title: string;
  description: string;
  preview: PresetPreview;
  question: string;
}

const PRESETS: readonly Preset[] = [
  {
    title: 'Revenue review',
    description: 'Trend, drivers, top accounts',
    preview: 'line',
    question: 'What drove revenue over the last 30 days?',
  },
  {
    title: 'Campaign ROAS',
    description: 'By channel and creative',
    preview: 'bars',
    question: 'What was ROAS by channel over the last 30 days?',
  },
  {
    title: 'Redemption funnel',
    description: 'Where gift cards drop off',
    preview: 'funnel',
    question: 'Where do users drop off in checkout over the last 30 days?',
  },
  {
    title: 'Account health',
    description: 'Churn risk and CSM load',
    preview: 'line',
    question: 'How many accounts are currently at risk?',
  },
];

const DEFAULT_DAYS: OverviewDays = 30;
const SKELETON_CARDS = 4;

/** `?days=` is the shareable source of truth; anything unknown falls back to 30. */
function parseDays(raw: string | null): OverviewDays {
  const n = Number(raw);
  return n === 7 || n === 30 || n === 90 ? n : DEFAULT_DAYS;
}

function greeting(now = new Date()): string {
  const h = now.getHours();
  if (h < 12) return 'Good morning';
  if (h < 18) return 'Good afternoon';
  return 'Good evening';
}

function subline(data: Overview | undefined, isError: boolean): string {
  if (data) return `${data.start_date} → ${data.end_date} across all connected sources.`;
  if (isError) return "Couldn't load the latest numbers. Refresh the page to try again.";
  return 'Loading the latest numbers…';
}

/** Overview dashboard (DESIGN.md › Dashboard). Data on solid cards, chrome on glass. */
export function OverviewPage({ userName }: { userName: string }) {
  const [params, setParams] = useSearchParams();
  const days = parseDays(params.get('days'));
  const { data, isLoading, isError } = useOverview(days);
  const navigate = useNavigate();
  const first = userName.split(' ')[0] || 'there';

  return (
    <div className="relative h-full">
      <Toolbar title="Overview">
        <RangeSwitch
          value={days}
          onChange={(d) => setParams({ days: String(d) }, { replace: true })}
        />
      </Toolbar>
      <div className="absolute inset-0 overflow-y-auto">
        <div className="mx-auto max-w-[1080px] px-7 pb-20 pt-[84px] max-sm:px-4">
          <h2 className="mt-1.5 font-serif text-display text-ink">
            {greeting()}, {first}
          </h2>
          <p className="mb-5 mt-0.5 text-muted-foreground">{subline(data, isError)}</p>

          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            {isLoading && !data
              ? Array.from({ length: SKELETON_CARDS }, (_, i) => (
                  <div key={i} className="h-[118px] animate-pulse rounded-card bg-card-2" />
                ))
              : data?.kpis.map((k) => <KpiCard key={k.metric_id} kpi={k} />)}
          </div>

          {data?.breakdown && (
            <div className="mt-3 grid gap-3 lg:grid-cols-[1.6fr_1fr]">
              <BreakdownCard breakdown={data.breakdown} />
            </div>
          )}

          <h3 className="mb-1 mt-7 font-serif text-[20px] text-ink">Start an analysis</h3>
          <p className="mb-3 text-label text-muted-foreground">
            Presets for common questions. Hover a card to preview what you&apos;ll get.
          </p>
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            {PRESETS.map((p) => (
              <PresetCard
                key={p.title}
                title={p.title}
                description={p.description}
                preview={p.preview}
                onSelect={() => navigate(`/ask?q=${encodeURIComponent(p.question)}`)}
              />
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
