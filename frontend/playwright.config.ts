import { defineConfig } from '@playwright/test';

// The caller starts the backend (serving frontend/dist) at 127.0.0.1:8765; no webServer is configured here.
export default defineConfig({
  testDir: './tests',
  timeout: 90_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [['list']],
  use: {
    baseURL: process.env.EAE_BASE_URL ?? 'http://127.0.0.1:8765',
    channel: 'msedge',
    headless: true,
    viewport: { width: 1440, height: 900 },
    trace: 'retain-on-failure',
    acceptDownloads: true,
  },
});
