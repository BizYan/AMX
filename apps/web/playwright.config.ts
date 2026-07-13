/** Playwright E2E Configuration */
import { defineConfig, devices } from '@playwright/test'

const runRealBrowserDelivery = process.env.RUN_REAL_BROWSER_DELIVERY_TEST === 'true'

export default defineConfig({
  testDir: './tests/e2e/playwright',
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: 1,
  reporter: 'list',
  timeout: 60000,

  use: {
    baseURL: process.env.E2E_BASE_URL || 'http://localhost:3000',
    // Real-runtime credentials must never be captured in automatic login artifacts.
    trace: runRealBrowserDelivery ? 'off' : 'on-first-retry',
    screenshot: runRealBrowserDelivery ? 'off' : 'only-on-failure',
    video: runRealBrowserDelivery ? 'off' : 'retain-on-failure',
  },

  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],

  webServer: process.env.E2E_BASE_URL || process.env.E2E_SKIP_WEBSERVER
    ? undefined
    : {
        command: 'npm run dev',
        url: 'http://localhost:3000',
        reuseExistingServer: !process.env.CI,
        timeout: 120000,
      },
})
