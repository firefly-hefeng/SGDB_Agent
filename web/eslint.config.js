import js from '@eslint/js';
import globals from 'globals';
import reactHooks from 'eslint-plugin-react-hooks';
import reactRefresh from 'eslint-plugin-react-refresh';
import tseslint from 'typescript-eslint';
import { defineConfig, globalIgnores } from 'eslint/config';

export default defineConfig([
  globalIgnores(['dist', 'node_modules', 'web-reference']),
  {
    files: ['**/*.{ts,tsx}'],
    extends: [
      js.configs.recommended,
      tseslint.configs.recommended,
      reactHooks.configs.flat.recommended,
      reactRefresh.configs.vite,
    ],
    languageOptions: {
      ecmaVersion: 2022,
      globals: { ...globals.browser, __APP_VERSION__: 'readonly' },
    },
    rules: {
      // React-Compiler analytics rules: keep as warnings, not errors.
      // We have explicit useEffect-based data loading that the compiler
      // can't statically prove is safe; the runtime behaviour is fine.
      'react-hooks/set-state-in-effect': 'warn',
      'react-hooks/preserve-manual-memoization': 'warn',
      // Allow `_unused` placeholder names.
      '@typescript-eslint/no-unused-vars': [
        'error',
        { argsIgnorePattern: '^_', varsIgnorePattern: '^_' },
      ],
      // Empty catch blocks are sometimes the right call.
      'no-empty': ['warn', { allowEmptyCatch: true }],
    },
  },
  // Files that intentionally export non-component constants alongside
  // their public component(s). Fast-refresh would lose its warm path; we
  // accept that for these utility files.
  {
    files: [
      'src/components/ui/Toast.tsx',
      'src/main.tsx',
    ],
    rules: {
      'react-refresh/only-export-components': 'warn',
    },
  },
]);
