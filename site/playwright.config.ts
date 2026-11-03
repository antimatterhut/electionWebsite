import { defineConfig, devices } from '@playwright/test';

// Tests run against the production build served by `vite preview` (static output, same as GitHub Pages).
export default defineConfig({
  testDir: 'tests/e2e',
  timeout: 45_000,
  fullyParallel: true,
  reporter: [['list']],
  expect: { toHaveScreenshot: { maxDiffPixelRatio: 0.01 } }, // plan §11.4: tolerance 1%
  use: { baseURL: 'http://localhost:4180', trace: 'retain-on-failure' },
  webServer: { command: 'npx vite preview --port 4180 --strictPort', url: 'http://localhost:4180', reuseExistingServer: false, timeout: 60_000 },
  projects: [
    { name: 'desktop', testIgnore: /mobile\.spec\.ts/, use: { ...devices['Desktop Chrome'], viewport: { width: 1280, height: 900 } } },
    { name: 'mobile', use: { ...devices['Pixel 7'] }, testMatch: /mobile\.spec\.ts/ }
  ]
});
