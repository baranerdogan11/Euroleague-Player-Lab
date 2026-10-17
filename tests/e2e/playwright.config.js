// Browser tests for the built site (tests/e2e). The site is served from the repository root exactly as GitHub Pages
// serves it. Chrome comes from $CHROME (CI sets it to the runner's Chrome, the same one tests/test_site.py uses), so
// nothing is downloaded; without $CHROME, Playwright's own Chromium is used (npx playwright install chromium).
// Run: npm run test:e2e   (screenshots of every page land in test-results/, and in the CI run's artifacts)
import {defineConfig} from '@playwright/test';

const PORT = 8137;
export default defineConfig({
  testDir: '.',
  outputDir: '../../test-results',
  timeout: 120_000,
  expect: {timeout: 15_000},
  fullyParallel: true,
  workers: process.env.CI ? 2 : undefined,
  forbidOnly: !!process.env.CI,
  reporter: process.env.CI ? [['list'], ['html', {outputFolder: '../../playwright-report', open: 'never'}]] : 'list',
  use: {
    baseURL: `http://127.0.0.1:${PORT}/`,
    launchOptions: process.env.CHROME ? {executablePath: process.env.CHROME} : {},
    serviceWorkers: 'block',
  },
  webServer: {
    command: `python3 -m http.server ${PORT} --bind 127.0.0.1`,
    cwd: '../..',
    url: `http://127.0.0.1:${PORT}/index.html`,
    reuseExistingServer: !process.env.CI,
    stderr: 'ignore',   // the request log
  },
});
