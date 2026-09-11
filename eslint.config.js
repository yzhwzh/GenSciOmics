
  import js from '@eslint/js'
  import globals from 'globals'
  import reactHooks from 'eslint-plugin-react-hooks'
  import reactRefresh from 'eslint-plugin-react-refresh'
  import tseslint from 'typescript-eslint'

  // Flat config. This file was missing while every dependency it needs was
  // already in package.json, so `npm run lint` (CLAUDE.md lists it as a routine
  // command) failed with ESLint's "no configuration found" exit, and none of the
  // rules below had ever run — including react-hooks/exhaustive-deps.
  export default tseslint.config(
    { ignores: ['dist', 'coverage', 'coverage-report', 'node_modules'] },

    // Frontend sources.
    {
      files: ['src/**/*.{ts,tsx}'],
      extends: [js.configs.recommended, ...tseslint.configs.recommended],
      languageOptions: {
        ecmaVersion: 2022,
        globals: globals.browser,
      },
      plugins: {
        'react-hooks': reactHooks,
        'react-refresh': reactRefresh,
      },
      rules: {
        // Only the two rules the project actually holds itself to. Both presets
        // eslint-plugin-react-hooks v7 ships (recommended, recommended-latest)
        // also enable the React Compiler diagnostics — set-state-in-effect,
        // purity, immutability — which flag the effect-based data fetching used
        // throughout src/ and cannot be satisfied without adopting the compiler.
        // Listing the two explicitly keeps the signal that matters (stale
        // closures) and drops 25 false alarms.
        'react-hooks/rules-of-hooks': 'error',
        'react-hooks/exhaustive-deps': 'error',
        'react-refresh/only-export-components': ['warn', { allowConstantExport: true }],
      },
    },

    // vite.config.ts and eslint.config.js itself run in Node, not the browser.
    // './' anchors the pattern to this config's own directory. Without it ESLint
    // matches the basename at ANY depth, which is how the generated
    // coverage-report/ HTML came to be parsed as source.
    {
      files: ['./*.{ts,js}'],
      extends: [js.configs.recommended],
      languageOptions: { globals: globals.node },
    },
  )

