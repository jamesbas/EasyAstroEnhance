import { expect, test } from '@playwright/test';
import { readFileSync } from 'node:fs';
import { LARGE_JPEG, TEST_JPEG, collectConsoleErrors, enhanceAndWait, resetBackend, uploadAndWaitReady, withAnalysisFallback } from './helpers';

test.describe('upload, enhance, compare, download', () => {
  test.beforeEach(async ({ request }) => {
    await resetBackend(request);
  });

  test('full workflow with a JPEG', async ({ page, request }) => {
    const errors = collectConsoleErrors(page);
    await page.goto('/');
    await uploadAndWaitReady(page, TEST_JPEG);

    const card = page.getByTestId('asset-card').first();
    await expect(card).toContainText('RGB');
    await expect(card).toContainText('JPEG');
    const thumb = card.getByTestId('asset-thumb');
    await expect(thumb).toBeVisible();
    await expect.poll(() => thumb.evaluate((img: HTMLImageElement) => img.naturalWidth)).toBeGreaterThan(0);

    await expect(page.getByTestId('compare-viewer')).toBeVisible();
    await expect(page.getByTestId('label-original')).toHaveText('Original view');
    await expect(page.getByTestId('enhance-selected')).toContainText('1 selected');
    await expect(page.getByTestId('preset-select')).toHaveValue('natural');

    await enhanceAndWait(page);
    await expect(page.getByTestId('result-note')).toContainText('Noise reduced');
    await expect(page.getByTestId('label-enhanced')).toHaveText('Enhanced');

    // Divider is a keyboard-accessible slider.
    const divider = page.getByTestId('comparison-divider');
    await expect(divider).toHaveAttribute('role', 'slider');
    await divider.focus();
    await expect(divider).toHaveAttribute('aria-valuenow', '50');
    await page.keyboard.press('ArrowRight');
    await expect(divider).toHaveAttribute('aria-valuenow', '52');
    await page.keyboard.press('Shift+ArrowLeft');
    await expect(divider).toHaveAttribute('aria-valuenow', '42');
    await page.keyboard.press('Home');
    await expect(divider).toHaveAttribute('aria-valuenow', '0');
    await page.keyboard.press('End');
    await expect(divider).toHaveAttribute('aria-valuenow', '100');

    // Viewer modes and zoom controls.
    await page.getByTestId('mode-side').click();
    await expect(page.getByTestId('compare-viewer').locator('.pane')).toHaveCount(2);
    await page.getByTestId('mode-divider').click();
    await page.getByTestId('compare-viewer').getByTestId('viewer-pane').hover();
    await page.keyboard.press('b');
    await expect(page.getByTestId('mode-blink')).toHaveAttribute('aria-pressed', 'true');
    await page.getByTestId('mode-divider').click();
    await page.getByTestId('zoom-100-button').click();
    await expect(page.locator('.zoom-readout')).toHaveText('100%');
    await page.getByTestId('fit-button').click();
    await expect(page.locator('.zoom-readout')).not.toHaveText('100%');

    // Download PNG link works and returns a real PNG.
    const link = page.getByTestId('download-png');
    await expect(link).toHaveAttribute('href', /\/api\/v1\/runs\/run_[^/]+\/exports\/png$/);
    const href = (await link.getAttribute('href')) as string;
    const res = await request.get(href);
    expect(res.status()).toBe(200);
    expect(res.headers()['content-type']).toContain('image/png');
    const [download] = await Promise.all([page.waitForEvent('download'), link.click()]);
    expect(download.suggestedFilename()).toMatch(/\.png$/);

    // More formats lists the run's exports.
    await page.getByTestId('more-formats').click();
    await expect(page.getByTestId('export-tiff')).toBeVisible();
    await expect(page.getByTestId('export-report')).toBeVisible();
    await page.keyboard.press('Escape');

    expect(errors).toEqual([]);
  });

  test('tone controls, settings changed and reprocess', async ({ page }) => {
    await page.goto('/');
    await uploadAndWaitReady(page);
    await enhanceAndWait(page);
    await expect(page.getByTestId('settings-changed')).toHaveCount(0);

    await page.getByTestId('tone-disclosure').locator('summary').click();
    const brightness = page.getByTestId('slider-brightness');
    await expect(brightness).toHaveValue('0');
    await brightness.fill('0.5');
    await expect(page.getByLabel('Brightness value')).toHaveValue('0.50');
    await expect(page.getByTestId('preset-select')).toHaveValue('custom');
    await expect(page.getByTestId('settings-changed')).toBeVisible();

    await page.getByTestId('slider-black-point').fill('0.05');
    await expect(page.getByTestId('clip-estimate')).toContainText('will clip');
    await page.getByTestId('slider-shadows').fill('-0.4');
    await page.getByTestId('slider-highlights').fill('0.3');

    await page.getByTestId('reset-tone').click();
    for (const id of ['brightness', 'shadows', 'highlights', 'black-point']) {
      await expect(page.getByTestId(`slider-${id}`)).toHaveValue('0');
    }
    await expect(page.getByTestId('settings-changed')).toHaveCount(0); // identical settings again: nothing to reprocess

    await page.getByTestId('slider-brightness').fill('-0.5');
    await page.getByTestId('reprocess-button').click();
    await expect(page.getByTestId('run-select').locator('option')).toHaveCount(2, { timeout: 60_000 });
    await expect(page.getByTestId('settings-changed')).toHaveCount(0);
    await page.getByTestId('show-clipping').check();
    await expect(page.locator('.stage-overlay').first()).toBeVisible();
  });

  test('presets can be saved, renamed, duplicated and deleted', async ({ page }) => {
    await page.goto('/');
    await uploadAndWaitReady(page);
    await expect(page.getByTestId('preset-select')).toHaveValue('natural');
    await expect(page.getByTestId('look-controls')).toBeVisible();
    await page.getByTestId('preset-select').selectOption('vivid');
    await expect(page.getByTestId('value-color')).toHaveText('0.60');
    await expect(page.getByTestId('value-background-level')).toHaveText('0.10');
    await expect(page.getByTestId('preset-description')).toContainText('pop');

    await page.getByTestId('slider-detail').fill('0.8');
    await expect(page.getByTestId('preset-select')).toHaveValue('custom');
    await page.getByTestId('save-preset').click();
    await page.getByTestId('preset-name').fill('My contrast');
    await page.getByTestId('confirm-save-preset').click();
    await expect(page.getByTestId('preset-select').locator('option', { hasText: 'My contrast' })).toHaveCount(1);
    await expect(page.getByTestId('preset-select')).not.toHaveValue('custom');

    await page.getByText('Manage presets').click();
    await page.getByRole('button', { name: 'Rename' }).click();
    await page.getByLabel('New preset name').fill('Renamed contrast');
    await page.getByRole('button', { name: 'Rename', exact: true }).click();
    await expect(page.getByTestId('preset-select').locator('option', { hasText: 'Renamed contrast' })).toHaveCount(1);
    await page.getByRole('button', { name: 'Duplicate' }).click();
    await expect(page.getByTestId('preset-select').locator('option', { hasText: 'Renamed contrast copy' })).toHaveCount(1);
    await page.getByRole('button', { name: 'Delete' }).first().click();
    await page.getByRole('button', { name: 'Delete' }).first().click();
    await expect(page.getByTestId('preset-select').locator('option', { hasText: 'contrast' })).toHaveCount(0);
  });

  test('one corrupt file never blocks the others', async ({ page }) => {
    await page.goto('/');
    await page.getByTestId('file-input').setInputFiles([
      { name: 'broken.jpg', mimeType: 'image/jpeg', buffer: Buffer.from('this is not an image at all') },
      { name: 'synthetic-sky.jpg', mimeType: 'image/jpeg', buffer: readFileSync(TEST_JPEG) },
    ]);
    const cards = page.getByTestId('asset-card');
    await expect(cards).toHaveCount(2);
    await expect(cards.filter({ hasText: 'broken.jpg' }).getByTestId('asset-status')).toHaveText('Failed');
    await expect(cards.filter({ hasText: 'broken.jpg' }).locator('.card-error')).not.toBeEmpty();
    const good = cards.filter({ hasText: 'synthetic-sky.jpg' });
    await expect(good.getByTestId('asset-status')).toHaveText('Ready');
    await page.getByTestId('enhance-all').click();
    await expect(good.getByTestId('asset-status')).toHaveText(/^Complete/, { timeout: 60_000 });
  });

  test('cancel stops queued images and keeps originals', async ({ page }) => {
    await page.goto('/');
    await page.getByTestId('file-input').setInputFiles([LARGE_JPEG, LARGE_JPEG, LARGE_JPEG, LARGE_JPEG]);
    const cards = page.getByTestId('asset-card');
    await expect(cards).toHaveCount(4);
    await expect(cards.last().getByTestId('asset-status')).toHaveText('Ready', { timeout: 30_000 });
    for (const i of [0, 1, 2]) await expect(cards.nth(i).getByTestId('asset-status')).toHaveText('Ready');
    await page.getByTestId('enhance-all').click();
    await expect(page.getByTestId('cancel-job')).toBeVisible();
    await page.getByTestId('cancel-job').click();
    await expect(page.getByTestId('cancel-job')).toHaveCount(0, { timeout: 60_000 });
    const labels = await cards.getByTestId('asset-status').allTextContents();
    expect(labels.some((l) => l === 'Cancelled')).toBeTruthy();

    // Manual retry resumes the cancelled items.
    const retry = page.getByTestId('retry-button');
    await expect(retry.first()).toBeVisible();
    await retry.first().click();
    await expect(page.getByTestId('retry-button')).toHaveCount(0, { timeout: 90_000 });
    for (let i = 0; i < 4; i++) {
      await expect(cards.nth(i).getByTestId('asset-status')).toHaveText(/^Complete/, { timeout: 90_000 });
    }
  });

  test('reloading during processing re-attaches to the running job', async ({ page }) => {
    await page.goto('/');
    await page.getByTestId('file-input').setInputFiles([LARGE_JPEG, LARGE_JPEG, LARGE_JPEG, LARGE_JPEG]);
    const cards = page.getByTestId('asset-card');
    await expect(cards).toHaveCount(4);
    for (let i = 0; i < 4; i++) await expect(cards.nth(i).getByTestId('asset-status')).toHaveText('Ready', { timeout: 30_000 });
    await page.getByTestId('enhance-all').click();
    await expect(page.getByTestId('cancel-job')).toBeVisible();
    await page.reload();
    await expect(page.getByTestId('asset-card')).toHaveCount(4);
    await expect(page.getByTestId('job-status')).toContainText('Enhancing', { timeout: 10_000 });
    for (let i = 0; i < 4; i++) {
      await expect(page.getByTestId('asset-card').nth(i).getByTestId('asset-status')).toHaveText(/^Complete/, { timeout: 90_000 });
    }
  });

  test('queue: select, remove with confirmation', async ({ page }) => {
    await page.goto('/');
    await page.getByTestId('file-input').setInputFiles([TEST_JPEG, LARGE_JPEG]);
    const cards = page.getByTestId('asset-card');
    await expect(cards).toHaveCount(2);
    await expect(cards.nth(0).getByTestId('asset-status')).toHaveText('Ready');
    await expect(cards.nth(1).getByTestId('asset-status')).toHaveText('Ready');
    await cards.nth(1).getByRole('checkbox').check();
    await expect(page.getByTestId('enhance-selected')).toContainText('2 selected');
    await expect(page.getByTestId('enhance-all')).toContainText('2 ready');
    await cards.nth(0).getByRole('button', { name: /^Remove / }).click();
    await expect(page.getByTestId('remove-dialog')).toContainText('your original file elsewhere');
    await page.getByRole('button', { name: 'Remove image' }).click();
    await expect(cards).toHaveCount(1);
  });

  test('full-resolution tiles appear when zooming a large image', async ({ page }) => {
    await page.goto('/');
    await uploadAndWaitReady(page, LARGE_JPEG);
    await expect(page.getByTestId('downsample-note')).toContainText('Preview downsampled to 2048 px');
    await enhanceAndWait(page);
    await page.getByTestId('zoom-100-button').click();
    await expect(page.locator('.stage-tile')).toHaveCount(2, { timeout: 20_000 });
    await expect(page.locator('.stage-tile').first()).toBeVisible();
  });

  test('background: suggested regions need confirmation, then can be applied or skipped', async ({ page }) => {
    await withAnalysisFallback(page);
    await page.goto('/');
    await uploadAndWaitReady(page);
    await page.getByTestId('switch-background').check();
    const panel = page.getByTestId('background-panel');
    await expect(panel).toContainText('Overall balance');
    await expect(panel).toContainText('Uneven sky (gradient)');
    await expect(panel.getByTestId('skip-background')).toBeVisible();
    await expect(page.getByTestId('bg-status')).toContainText('Pending');
    await expect(page.getByTestId('asset-card').getByText('Background pending')).toBeVisible();
    await panel.getByTestId('suggest-regions').click();
    await expect(page.getByTestId('suggestions')).toBeVisible({ timeout: 60_000 });
    await page.getByTestId('suggestions').getByRole('button', { name: 'Accept all' }).click();
    await expect(page.getByTestId('sample-list').locator('li').first()).toBeVisible();
    await panel.getByTestId('check-model').click();
    await expect(page.getByTestId('bg-result')).toBeVisible({ timeout: 60_000 });
    await expect(page.getByTestId('apply-correction')).toBeEnabled();
    await page.getByTestId('apply-correction').click();
    await expect(page.getByTestId('bg-status')).toContainText('Confirmed for this image', { timeout: 30_000 });
    await expect(page.getByTestId('asset-card').getByText('Background pending')).toHaveCount(0);
    await panel.getByTestId('skip-background').click();
    await expect(page.getByTestId('background-panel')).toHaveCount(0);
  });

  test('label region and star mask in advanced', async ({ page }) => {
    await withAnalysisFallback(page);
    await page.goto('/');
    await uploadAndWaitReady(page);
    await page.getByTestId('label-start').click();
    await expect(page.getByTestId('label-confirm')).toBeVisible();
    await page.getByTestId('label-confirm').click();
    await expect(page.getByText('Label band protected')).toBeVisible();
    await page.getByTestId('advanced-disclosure').locator('summary').click();
    await page.getByTestId('show-star-mask').check();
    await expect(page.getByTestId('show-star-mask')).toBeChecked();
    await expect(page.getByTestId('show-star-mask')).toBeEnabled({ timeout: 60_000 });
  });
});
