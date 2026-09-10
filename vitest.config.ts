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
      reporter: ['text', 'lcov', 'html'],
      include: ['src/**/*.{ts,tsx}'],
      exclude: ['src/test/**', '**/*.test.*', '**/*.d.ts'],
      thresholds: { lines: 40, functions: 40, branches: 30, statements: 40 },
    },
  },
})
