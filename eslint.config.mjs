// ESLint for the TypeScript half of the monorepo (Python is ruff — see apps/api).
//
// Two things this config is deliberately opinionated about, because both map onto
// requirements in the spec rather than to taste:
//
//   * `no-restricted-imports` blocks the two mistakes that would quietly break spec
//     section 25 (no keys on the client) and section 22 (provenance labels): reaching
//     for `process.env` outside the config module, and importing a screen's internals
//     from another screen.
//   * `no-restricted-syntax` blocks bare colour literals in styles. Spec section 19
//     defines the palette in `@papermatch/design-tokens`, and a hard-coded `#22c55e`
//     is how the colour-blind-safe pairing gets lost one component at a time.
//
// Formatting is Prettier's job, not ESLint's; `eslint-config-prettier` last turns off
// every stylistic rule so the two never disagree.

import expoConfig from 'eslint-config-expo/flat.js';
import prettierConfig from 'eslint-config-prettier';
import tseslint from 'typescript-eslint';

export default tseslint.config(
  {
    ignores: [
      '**/node_modules/**',
      '**/.expo/**',
      '**/dist/**',
      '**/build/**',
      '**/coverage/**',
      'apps/api/**',
      'fixtures/**',
      // Generated: 650KB of minified KaTeX, regenerated and diffed by CI.
      'apps/mobile/src/math/katexRuntime.ts',
    ],
  },

  ...expoConfig,

  {
    files: ['**/*.{ts,tsx}'],
    languageOptions: {
      parserOptions: {
        projectService: true,
        tsconfigRootDir: import.meta.dirname,
      },
    },
    rules: {
      // Unused code is either a mistake or a leftover; `_`-prefixed names are the
      // documented way to say "intentionally ignored".
      '@typescript-eslint/no-unused-vars': [
        'error',
        {
          argsIgnorePattern: '^_',
          varsIgnorePattern: '^_',
          caughtErrorsIgnorePattern: '^_',
        },
      ],

      // `any` erases exactly the distinctions the data model exists to keep: original
      // text vs machine translation vs AI explanation (spec section 3). A warning, not
      // an error, so it shows up in review without blocking an unrelated change.
      '@typescript-eslint/no-explicit-any': 'warn',

      '@typescript-eslint/consistent-type-imports': [
        'error',
        { prefer: 'type-imports', fixStyle: 'inline-type-imports' },
      ],

      eqeqeq: ['error', 'always', { null: 'ignore' }],
      'no-console': ['warn', { allow: ['warn', 'error'] }],
    },
  },

  {
    files: ['apps/mobile/**/*.{ts,tsx}'],
    ignores: ['apps/mobile/src/config/**'],
    rules: {
      'no-restricted-imports': [
        'error',
        {
          patterns: [
            {
              group: ['**/app/**'],
              message:
                'Screens are entry points, not modules. Move the shared part into src/ and import that.',
            },
          ],
        },
      ],
    },
  },

  {
    files: ['apps/mobile/**/*.{ts,tsx}', 'packages/**/*.{ts,tsx}'],
    ignores: ['**/__tests__/**', '**/*.test.{ts,tsx}', 'packages/design-tokens/**'],
    rules: {
      'no-restricted-syntax': [
        'error',
        {
          // Spec section 19 puts the palette in one place, and section 20 requires the
          // colour-blind-safe pairings to hold everywhere. A literal here is how that
          // guarantee erodes without anyone deciding to drop it.
          selector: 'Literal[value=/^#(?:[0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$/]',
          message:
            'Use a token from @papermatch/design-tokens instead of a hex literal (spec section 19).',
        },
      ],
    },
  },

  {
    files: ['**/__tests__/**/*.{ts,tsx}', '**/*.test.{ts,tsx}', 'scripts/**/*.mjs'],
    rules: {
      'no-console': 'off',
      '@typescript-eslint/no-explicit-any': 'off',
    },
  },

  prettierConfig,
);
