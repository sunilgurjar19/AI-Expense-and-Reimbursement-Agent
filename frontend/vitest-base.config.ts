import { defineConfig } from 'vitest/config';

/**
 * Extra Vitest options, merged by the Angular unit-test builder (angular.json → test.runnerConfig).
 *
 * `isolate: true` - run every spec file in a fresh module graph. The builder defaults to
 * `isolate: false`, but with --coverage @angular/build loads user `setupFiles` through a wrapper
 * module, so Vitest's per-file re-run of setup files only re-executes the wrapper: the code in
 * testing/test-setup.ts then runs once per worker and its afterEach hygiene silently stops
 * applying to later spec files. Isolation makes test state identical with and without coverage.
 */
export default defineConfig({
  test: {
    isolate: true,
  },
});
