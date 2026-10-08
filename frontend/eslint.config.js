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
    // Engineering standards (ARCHITECTURE.md): size, complexity and type-safety limits.
    // Machine-enforced; a justified exception is a single-line disable with a reason.
    files: ['src/**/*.{ts,tsx}'],
    rules: {
      '@typescript-eslint/no-explicit-any': 'error',
      '@typescript-eslint/consistent-type-imports': ['error', { fixStyle: 'inline-type-imports' }],
      '@typescript-eslint/no-unused-vars': [
        'error',
        { argsIgnorePattern: '^_', varsIgnorePattern: '^_' },
      ],
      'max-lines': ['error', { max: 300, skipBlankLines: true, skipComments: true }],
      'max-lines-per-function': ['error', { max: 150, skipBlankLines: true, skipComments: true }],
      complexity: ['error', 12],
      'max-depth': ['error', 4],
      'max-params': ['error', 4],
      'no-console': ['error', { allow: ['warn', 'error'] }],
      eqeqeq: ['error', 'always'],
      'no-nested-ternary': 'error',
    },
  },
  {
    // Test files: long describe blocks are fine; everything else still applies.
    files: ['src/**/*.test.{ts,tsx}'],
    rules: {
      'max-lines-per-function': 'off',
      'max-lines': 'off',
    },
  },
  {
    // Features are self-contained silos: internal imports are relative (./x),
    // everything else comes from the api/lib/ui layers via @/.
    files: ['src/features/**/*.{ts,tsx}'],
    rules: {
      'no-restricted-syntax': [
        'error',
        {
          selector: 'Literal[value=/#[0-9a-fA-F]{3,8}\\b/]',
          message:
            'DESIGN.md: use design tokens (Tailwind token classes / CSS vars), never hex colors in features.',
        },
        {
          selector: 'TemplateElement[value.raw=/#[0-9a-fA-F]{3,8}\\b/]',
          message:
            'DESIGN.md: use design tokens (Tailwind token classes / CSS vars), never hex colors in features.',
        },
      ],
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
              message: 'Component standard: ui primitives may not depend on features, api, or lib.',
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
