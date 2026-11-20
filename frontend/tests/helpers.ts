import { expect } from '@playwright/test';
import type { APIRequestContext, Page } from '@playwright/test';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));

// A synthetic star-field JPEG; set EAE_TEST_JPEG to use a real photo instead.
export const TEST_JPEG = process.env.EAE_TEST_JPEG ?? path.join(here, 'fixtures', 'synthetic-sky.jpg');
// Larger than the 2048 px preview limit (3200 x 2133) to exercise ROI tiles.
export const LARGE_JPEG = path.join(here, 'fixtures', 'synthetic-large.jpg');

// Starts every spec from a clean backend: clears history through the API with the session token.
export async function resetBackend(request: APIRequestContext): Promise<void> {
  const session = await (await request.get('/api/v1/session')).json();
  const res = await request.delete('/api/v1/history', {
    headers: { 'X-EAE-Token': session.token },
    data: { confirm: true },
  });
  expect(res.ok(), 'history cleared').toBeTruthy();
}

// The panel starts in Simple mode; specs that exercise the detailed controls open All controls (a stored UI choice).
export async function showAllControls(page: Page): Promise<void> {
  await page.addInitScript(() => window.localStorage.setItem('eae.panel', 'all'));
}

export async function uploadAndWaitReady(page: Page, file: string = TEST_JPEG): Promise<void> {
  await page.getByTestId('file-input').setInputFiles(file);
  const card = page.getByTestId('asset-card').first();
  await expect(card).toBeVisible();
  await expect(card.getByTestId('asset-status')).toHaveText('Ready');
}

export async function enhanceAndWait(page: Page): Promise<void> {
  await page.getByTestId('enhance-selected').click();
  await expect(page.getByTestId('asset-status').first()).toHaveText(/^Complete/, { timeout: 60_000 });
  await expect(page.getByTestId('result-note')).toBeVisible();
}

// Analysis endpoints are served by the real backend (no stand-ins); kept as a no-op so specs read the same.
export async function withAnalysisFallback(_page: Page): Promise<{ usedFallback: () => boolean }> {
  return { usedFallback: () => false };
}

export function collectConsoleErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on('console', (m) => {
    if (m.type() === 'error') errors.push(m.text());
  });
  page.on('pageerror', (e) => errors.push(e.message));
  return errors;
}

