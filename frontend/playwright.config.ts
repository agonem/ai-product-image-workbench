import { defineConfig } from '@playwright/test'

if (!process.env.T06_BASE_URL || !process.env.T06_PASSWORD)
  throw new Error(
    'Run python scripts/check_db.py --t06-only; no real account is used.',
  )

export default defineConfig({
  testDir: './tests',
  workers: 1,
  retries: 0,
  timeout: 90000,
  outputDir: process.env.T06_ARTIFACTS ?? '../.artifacts/t06-browser',
  reporter: 'list',
  use: {
    baseURL: process.env.T06_BASE_URL,
    browserName: 'chromium',
    viewport: { width: 1440, height: 1000 },
    screenshot: 'only-on-failure',
    trace: 'off',
  },
})
