import { defineConfig } from '@playwright/test'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

// UI-only tests intercept every API request; no Java, database or supplier is contacted.
const port = Number(process.env.UPLOAD_TEST_PORT ?? 4187)
const baseURL = `http://127.0.0.1:${port}`
export default defineConfig({
  testDir: './tests-upload',
  workers: 1,
  retries: 0,
  timeout: 30000,
  expect: { timeout: 5000 },
  outputDir:
    process.env.UPLOAD_TEST_ARTIFACTS ?? join(tmpdir(), 'workbench-upload-ac'),
  reporter: 'list',
  use: {
    baseURL,
    browserName: 'chromium',
    viewport: { width: 1440, height: 1000 },
    screenshot: 'only-on-failure',
    trace: 'off',
  },
  webServer: {
    command: `npm run dev -- --host 127.0.0.1 --port ${port} --strictPort`,
    url: baseURL,
    reuseExistingServer: false,
    env: {
      VITE_AUTH_MODE: 'production-local',
      VITE_ACCEPTANCE_MODE: 'mock-provider',
      DEV_API_TARGET: 'http://127.0.0.1:1',
    },
  },
})
