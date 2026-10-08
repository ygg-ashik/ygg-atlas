/** @type {import('tailwindcss').Config} */
import animate from 'tailwindcss-animate';

// Token → Tailwind color with opacity-modifier support (bg-primary/15 etc.).
const v = (name) => `hsl(var(--${name}) / <alpha-value>)`;

export default {
  darkMode: ['class'],
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}', './node_modules/streamdown/dist/*.js'],
  theme: {
    extend: {
      colors: {
        border: v('border'),
        input: v('input'),
        ring: v('ring'),
        background: v('background'),
        foreground: v('foreground'),
        primary: {
          DEFAULT: v('primary'),
          foreground: v('primary-foreground'),
          text: v('primary-text'),
        },
        secondary: { DEFAULT: v('secondary'), foreground: v('secondary-foreground') },
        destructive: { DEFAULT: v('destructive'), foreground: v('destructive-foreground') },
        muted: { DEFAULT: v('muted'), foreground: v('muted-foreground') },
        accent: { DEFAULT: v('accent'), foreground: v('accent-foreground') },
        popover: { DEFAULT: v('popover'), foreground: v('popover-foreground') },
        card: { DEFAULT: v('card'), foreground: v('card-foreground'), 2: v('card-2') },
        canvas: v('canvas'),
        surface: v('surface'),
        ink: v('ink'),
        body: v('body'),
        'muted-2': v('muted-2'),
        positive: v('positive'),
        negative: v('negative'),
        warning: v('warning'),
        glass: { DEFAULT: 'var(--glass)', heavy: 'var(--glass-heavy)', edge: 'var(--glass-edge)' },
      },
      fontFamily: {
        sans: [
          '"Inter Variable"',
          '-apple-system',
          'BlinkMacSystemFont',
          'system-ui',
          'sans-serif',
        ],
        serif: ['"Source Serif 4 Variable"', 'Georgia', 'serif'],
        mono: ['"JetBrains Mono Variable"', 'ui-monospace', 'Menlo', 'monospace'],
      },
      fontSize: {
        display: ['32px', { lineHeight: '1.15', letterSpacing: '-0.01em' }],
        title: ['23px', { lineHeight: '1.25', letterSpacing: '-0.01em' }],
        section: ['19px', { lineHeight: '1.3', letterSpacing: '-0.005em' }],
        answer: ['15.5px', { lineHeight: '1.65' }],
        label: ['13px', { lineHeight: '1.4' }],
        caption: ['11.5px', { lineHeight: '1.4', letterSpacing: '0.005em' }],
        'metric-xl': ['32px', { lineHeight: '1.1', letterSpacing: '-0.03em' }],
        'metric-lg': ['27px', { lineHeight: '1.1', letterSpacing: '-0.025em' }],
      },
      borderRadius: {
        sm: '8px',
        md: '12px',
        lg: '16px',
        card: '18px',
        shell: '22px',
        feature: '24px',
        glass: '26px',
      },
      transitionTimingFunction: {
        out: 'cubic-bezier(.22,1,.36,1)',
        sheet: 'cubic-bezier(.32,.72,0,1)',
      },
      keyframes: {
        'materialize-in': {
          from: { opacity: '0', transform: 'scale(.94)', filter: 'blur(6px)' },
          to: { opacity: '1', transform: 'scale(1)', filter: 'blur(0)' },
        },
        'materialize-out': {
          from: { opacity: '1', transform: 'scale(1)', filter: 'blur(0)' },
          to: { opacity: '0', transform: 'scale(.96)', filter: 'blur(6px)' },
        },
        shimmer: { from: { backgroundPosition: '120% 0' }, to: { backgroundPosition: '-80% 0' } },
        'caret-pulse': { '50%': { transform: 'scale(.6)', opacity: '.5' } },
        grow: { from: { transform: 'scaleX(0)' }, to: { transform: 'scaleX(1)' } },
      },
      animation: {
        'materialize-in': 'materialize-in 320ms cubic-bezier(.22,1,.36,1) both',
        'materialize-out': 'materialize-out 220ms cubic-bezier(.22,1,.36,1) both',
        shimmer: 'shimmer 1.6s linear infinite',
        'caret-pulse': 'caret-pulse 1s ease-in-out infinite',
      },
    },
  },
  plugins: [animate],
};
