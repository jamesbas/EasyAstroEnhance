import { expect, test } from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { resetBackend, showAllControls } from './helpers';

const fixture = (name: string) => path.join(path.dirname(fileURLToPath(import.meta.url)), 'fixtures', name);

test.describe('intake questions', () => {
  test.beforeEach(async ({ page, request }) => {
    await resetBackend(request);
    await showAllControls(page);
  });

  test('FITS: "How was this image saved?" - linear stack becomes ready and monochrome disables color', async ({ page }) => {
    await page.goto('/');
    await page.getByTestId('file-input').setInputFiles(fixture('mono-linear.fits'));
    const dialog = page.getByTestId('intake-dialog');
    await expect(dialog).toBeVisible({ timeout: 30_000 });
    await expect(dialog).toContainText('How was this image saved?');
    await expect(dialog.getByTestId('intake-option-linear')).toContainText('Linear stack');
    await expect(dialog.getByTestId('intake-option-rendered')).toContainText('Already processed');
    await expect(dialog.getByTestId('intake-option-unsure')).toContainText("I'm not sure");
    await dialog.getByTestId('intake-option-linear').click();
    await expect(dialog).toBeHidden();
    const status = page.getByTestId('asset-status');
    await expect(status).toHaveText('Ready', { timeout: 30_000 });
    await expect(page.getByTestId('label-original')).toHaveText('Original shown with a display stretch');
    await expect(page.getByTestId('slider-color')).toBeDisabled();
    await expect(page.locator('#look-color-hint')).toHaveText('Not available for monochrome images.');
    await expect(page.getByTestId('slider-star-color')).toBeDisabled();
    await expect(page.getByTestId('asset-card')).toContainText('Monochrome');
    await page.getByTestId('enhance-selected').click();
    await expect(status).toHaveText(/^Complete/, { timeout: 60_000 });
    await expect(page.getByTestId('result-note')).toBeVisible();
    await page.getByTestId('more-formats').click();
    await expect(page.getByTestId('export-fits')).toBeVisible();
    await expect(page.getByTestId('export-fits-full')).toContainText('Full-metadata FITS (includes location/observer details)');
  });

  test('"I\'m not sure" gives a labeled preview and keeps Enhance disabled', async ({ page }) => {
    await page.goto('/');
    await page.getByTestId('file-input').setInputFiles(fixture('mono-linear.fits'));
    await page.getByTestId('intake-option-unsure').click({ timeout: 30_000 });
    await expect(page.getByTestId('preview-only-note')).toBeVisible({ timeout: 30_000 });
    await expect(page.getByTestId('label-original')).toContainText('Preview only');
    await expect(page.getByTestId('enhance-selected')).toBeDisabled();
    await expect(page.getByTestId('enhance-all')).toBeDisabled();
    await expect(page.getByText('Enhancement is blocked until you confirm how this image was saved.')).toBeVisible();
    await page.getByRole('button', { name: 'How was this image saved?' }).click();
    await page.getByTestId('intake-option-rendered').click();
    await expect(page.getByTestId('asset-status')).toHaveText('Ready', { timeout: 30_000 });
    await expect(page.getByTestId('enhance-selected')).toBeEnabled();
  });

  test('several image HDUs: short selector with names, sizes and thumbnails', async ({ page }) => {
    await page.goto('/');
    await page.getByTestId('file-input').setInputFiles(fixture('two-hdu.fits'));
    const dialog = page.getByTestId('intake-dialog');
    await expect(dialog).toContainText('Which image should be used?', { timeout: 30_000 });
    await expect(dialog.locator('.intake-option')).toHaveCount(2);
    await expect(dialog).toContainText('SCI');
    await expect(dialog).toContainText('PREVIEW');
    await expect(dialog.locator('.intake-thumb').first()).toBeVisible();
    await dialog.locator('.intake-option', { hasText: 'SCI' }).click();
    await expect(page.getByTestId('intake-dialog')).toContainText('How was this image saved?', { timeout: 30_000 });
    await page.getByTestId('intake-option-rendered').click();
    await expect(page.getByTestId('asset-status')).toHaveText('Ready', { timeout: 30_000 });
  });

  test('Seestar-style headers give recommended answers that can be confirmed for all similar files at once', async ({ page }) => {
    await page.goto('/');
    const buffer = fs.readFileSync(fixture('seestar-like.fits'));
    await page.getByTestId('file-input').setInputFiles([
      { name: 'Stacked_12_A.fit', mimeType: 'application/octet-stream', buffer },
      { name: 'Stacked_12_B.fit', mimeType: 'application/octet-stream', buffer },
    ]);
    const dialog = page.getByTestId('intake-dialog');
    await expect(dialog).toContainText('Are these red, green and blue channels?', { timeout: 30_000 });
    await expect(dialog.getByTestId('intake-recommendation')).toContainText('Seestar S30');
    await expect(dialog.getByTestId('intake-option-layout-rgb_planes').getByTestId('recommended-badge')).toBeVisible();
    await expect(dialog.getByTestId('intake-option-layout-not_rgb').getByTestId('recommended-badge')).toHaveCount(0);
    // the bulk action covers every file that is waiting with recommendations (both, once both are inspected)
    await expect(dialog.getByTestId('intake-apply-recommended')).toHaveText('Use recommended answers for all 2 files', { timeout: 30_000 });
    await dialog.getByTestId('intake-apply-recommended').click();
    await expect(page.getByTestId('intake-dialog')).toHaveCount(0);
    await expect(page.getByTestId('asset-status')).toHaveText(['Ready', 'Ready'], { timeout: 30_000 });
    await expect(page.getByTestId('label-original')).toHaveText('Original shown with a display stretch');
  });

  test('unconfirmed RGB planes ask for layout confirmation', async ({ page }) => {
    await page.goto('/');
    await page.getByTestId('file-input').setInputFiles(fixture('rgb-planes.fits'));
    const dialog = page.getByTestId('intake-dialog');
    await expect(dialog).toContainText('Are these red, green and blue channels?', { timeout: 30_000 });
    await dialog.getByTestId('intake-option-layout-rgb_planes').click();
    await expect(page.getByTestId('intake-dialog')).toContainText('How was this image saved?', { timeout: 30_000 });
  });

  test('single-frame CFA FITS fails with the readable backend message while others stay ready', async ({ page }) => {
    await page.goto('/');
    await page.getByTestId('file-input').setInputFiles([fixture('bayer.fits'), fixture('synthetic-sky.jpg')]);
    const cards = page.getByTestId('asset-card');
    await expect(cards).toHaveCount(2);
    const bayer = cards.filter({ hasText: 'bayer.fits' });
    await expect(bayer.getByTestId('asset-status')).toHaveText('Failed');
    await expect(bayer.locator('.card-error')).toContainText('This file needs debayering or stacking first');
    await expect(cards.filter({ hasText: 'synthetic-sky.jpg' }).getByTestId('asset-status')).toHaveText('Ready');
    await expect(page.getByTestId('intake-dialog')).toHaveCount(0);
  });
});
