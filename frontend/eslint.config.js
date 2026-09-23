import js from '@eslint/js';
import tseslint from 'typescript-eslint';
import reactHooks from 'eslint-plugin-react-hooks';

// Enforces the component standard from CLAUDE.md:
//   - dependency direction flows features → api/lib → ui only
//   - features never import other features (self-contained modules)
//   - no relative-path climbing out of a module (../../)
export default tseslint.config(
  { ignores: ['dist/**', 'node_modules/**', 'coverage/**'] },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    files: ['**/*.{ts,tsx}'],
    plugins: {
      'react-hooks': reactHooks,
    },
    rules: {
      ...reactHooks.configs.recommended.rules,
      'no-restricted-imports': [
        'error',
        {
          patterns: [
            {
              group: ['../../*'],
              message:
                'Component standard: no climbing out of a module with ../../ — use the @/ alias.',
            },
          ],
        },
      ],
    },
  },
  {
    // Features are self-contained silos: internal imports are relative (./x),
    // everything else comes from the api/lib/ui layers via @/.
    files: ['src/features/**/*.{ts,tsx}'],
    rules: {
      'no-restricted-imports': [
        'error',
        {
          patterns: [
            {
              group: ['@/features/*'],
              message:
                'Component standard: features may not import other features. Compose them in App.tsx.',
            },
            {
              group: ['../../*'],
              message:
                'Component standard: no climbing out of a module with ../../ — use the @/ alias.',
            },
          ],
        },
      ],
    },
  },
  {
    // api and lib sit below features: they may never reach up.
    files: ['src/api/**/*.{ts,tsx}', 'src/lib/**/*.{ts,tsx}'],
    rules: {
      'no-restricted-imports': [
        'error',
        {
          patterns: [
            {
              group: ['@/features/*'],
              message: 'Component standard: api/lib may not import features.',
            },
            {
              group: ['../../*'],
              message:
                'Component standard: no climbing out of a module with ../../ — use the @/ alias.',
            },
          ],
        },
      ],
    },
  },
  {
    // ui is the lowest layer: pure presentational primitives only.
    files: ['src/ui/**/*.{ts,tsx}'],
    rules: {
      'no-restricted-imports': [
        'error',
        {
          patterns: [
            {
              group: ['@/features/*', '@/api/*', '@/lib/*'],
              message:
                'Component standard: ui primitives may not depend on features, api, or lib.',
            },
            {
              group: ['../../*'],
              message:
                'Component standard: no climbing out of a module with ../../ — use the @/ alias.',
            },
          ],
        },
      ],
    },
  },
);
