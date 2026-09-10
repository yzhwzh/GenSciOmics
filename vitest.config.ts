import { defineConfig, configDefaults } from 'vitest/config'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    globals: true,
    css: false,
    // Without this, vitest's glob also picks up e2e/*.spec.ts — those are Playwright
    // specs and blow up with "Playwright Test did not expect test.describe() here",
    // which fails `npm test` even when every unit test passes. Spreading
    // configDefaults keeps vitest's own excludes, which setting `exclude` replaces.
    exclude: [...configDefaults.exclude, 'e2e/**'],
    coverage: {
      provider: 'v8',
      // NOT the default './coverage'. This shell exports PYTHONPATH with a
      // leading ':', which puts the cwd on sys.path — so a directory named
      // `coverage/` at the repo root is imported by Python as an empty
      // namespace package, shadowing the real `coverage` module that
      // numba (via scanpy) needs. `python3 server/main.py` then dies at import
      // with "AttributeError: module 'coverage' has no attribute 'types'" and
      // the backend never starts. Any report dir name that isn't a Python
      // module name avoids this; see B29.
      reportsDirectory: './coverage-report',
      reporter: ['text', 'lcov', 'html'],
      include: ['src/**/*.{ts,tsx}'],
      exclude: ['src/test/**', '**/*.test.*', '**/*.d.ts'],
      // No `thresholds` on purpose. Measured 2026-09-10: lines 17.67%, branches 16.35%,
      // functions 15.94% — the tests concentrate on the analysis containers and hit 0%
      // on every page and most of the visualisation components. Any threshold here fails
      // on every single run, which just trains people to ignore the command. Coverage is
      // a measurement, not a gate. Note it also says nothing about server/ — the Python
      // backend has no coverage tooling at all.
    },
  },
})
