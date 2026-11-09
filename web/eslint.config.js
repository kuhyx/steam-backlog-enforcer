import js from '@eslint/js'
import astro from 'eslint-plugin-astro'
import globals from 'globals'
import tseslint from 'typescript-eslint'

// typescript-eslint strict + stylistic (type-checked) on .ts; .astro files get
// eslint-plugin-astro's recommended set (their scripts also pass astro check).
export default tseslint.config(
  { ignores: ['dist', 'coverage', '.astro', 'src/env.d.ts'] },
  { linterOptions: { reportUnusedDisableDirectives: 'error' } },
  js.configs.recommended,
  ...[...tseslint.configs.strictTypeChecked, ...tseslint.configs.stylisticTypeChecked].map((c) => ({
    ...c,
    files: ['**/*.ts'],
  })),
  ...astro.configs['flat/recommended'],
  {
    files: ['**/*.ts'],
    languageOptions: {
      globals: globals.browser,
      parserOptions: { project: './tsconfig.json', tsconfigRootDir: import.meta.dirname },
    },
    rules: {
      '@typescript-eslint/restrict-template-expressions': ['error', { allowNumber: true }],
    },
  },
  {
    files: ['**/*.test.ts', 'src/test/**'],
    rules: { '@typescript-eslint/unbound-method': 'off' },
  },
  {
    // The dev-only mock API and the configs run in Node, not the browser.
    files: ['mock/**/*.ts', '*.js', '*.mjs', 'vitest.config.ts'],
    languageOptions: { globals: globals.node },
  },
  { files: ['*.js', '*.mjs'], ...tseslint.configs.disableTypeChecked },
)
