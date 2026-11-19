import { expect, test } from '@playwright/test';
import path from 'node:path';
import { resetBackend } from './helpers';

const dir = process.env.EAE_COLOR_DIR;

test.describe('optional color workflow', () => {
  test.skip(!dir, 'The browser runner prepares the synthetic color fixtures.');

  test.beforeEach(async ({ request }) => { await resetBackend(request); });

  test('preview a hue mask, import a local catalog, and enhance with manual focus', async ({ page }) => {
    await page.goto('/');
    await page.getByTestId('file-input').setInputFiles(path.join(dir!, 'solved-rgb.fits'));
    await page.getByTestId('intake-option-linear').click();
    await expect(page.getByTestId('asset-status')).toHaveText('Ready');
    await page.getByText('Object Color', { exact: true }).click();
    await page.getByLabel('Blue / violet', { exact: true }).fill('0.8');
    await expect(page.getByRole('img', { name: 'Object color preview' })).toBeVisible();
    await page.getByLabel('Show color mask').check();
    await expect(page.getByRole('img', { name: 'Object color mask' })).toBeVisible();
    await page.getByText('Catalog color', { exact: true }).click();
    await page.getByLabel('Reference star CSV').setInputFiles(path.join(dir!, 'reference.csv'));
    await expect(page.getByText(/reference.csv \(16 stars\)/)).toBeVisible();
    await page.getByText('Stretch method', { exact: true }).click();
    await page.getByLabel('Linear stretch method').selectOption('focused');
    await page.getByTestId('enhance-selected').click();
    await expect(page.getByTestId('asset-status')).toHaveText(/^Complete/);
    await expect(page.getByTestId('result-note')).toBeVisible();
  });

  test('maps HOO channels to a new unenhanced FITS asset', async ({ page }) => {
    await page.goto('/');
    await page.getByTestId('file-input').setInputFiles([path.join(dir!, 'ha.fits'), path.join(dir!, 'oiii.fits')]);
    await page.getByTestId('intake-option-linear').click();
    await page.getByTestId('intake-option-linear').click();
    await page.getByRole('button', { name: 'Combine channels…' }).click();
    await page.getByLabel('Color mix').selectOption('HOO');
    const dialog = page.getByRole('dialog', { name: 'Combine channels' });
    await dialog.getByRole('combobox', { name: 'Ha', exact: true }).selectOption({ label: 'ha.fits' });
    await dialog.getByRole('combobox', { name: 'OIII', exact: true }).selectOption({ label: 'oiii.fits' });
    await page.getByRole('button', { name: 'Create color master' }).click();
    const mixed = page.getByTestId('asset-card').filter({ hasText: 'ha - HOO.fits' });
    await expect(mixed.getByTestId('asset-status')).toHaveText('Ready');
    await expect(page.getByTestId('asset-card')).toHaveCount(3);
    await expect(page.getByTestId('enhance-selected')).toBeEnabled();
  });

  test('one click renders the dual-band palette and ordinary Enhance stays natural', async ({ page }) => {
    await page.goto('/');
    await page.getByTestId('file-input').setInputFiles(path.join(dir!, 'broadband.fits'));
    await page.getByTestId('intake-option-linear').click();
    await expect(page.getByTestId('asset-status')).toHaveText('Ready');
    const quick = page.getByRole('button', { name: /Enhance Hubble-style/ });
    await expect(quick).toHaveCount(0);

    await page.getByTestId('file-input').setInputFiles(path.join(dir!, 'dualband.fits'));
    await page.getByTestId('intake-option-linear').click();
    await expect(quick).toBeEnabled();
    await quick.click();
    await expect(page.getByTestId('result-note')).toContainText('Hubble-style (not SHO)');

    await page.getByText('Object Color', { exact: true }).click();
    await page.getByText('Hubble-style (dual-band)', { exact: true }).click();
    await expect(page.getByRole('img', { name: 'Hubble-style palette preview' })).toBeVisible();
    await page.getByRole('slider', { name: 'Palette strength' }).fill('0.8');
    await expect(page.getByText('Palette strength: 80%')).toBeVisible();
    const paletteJob = page.waitForRequest((r) => r.method() === 'POST' && r.url().endsWith('/api/v1/jobs'));
    await quick.click();
    expect((await paletteJob).postDataJSON().recipe.hubble_strength).toBe(0.8);

    const normalJob = page.waitForRequest((r) => r.method() === 'POST' && r.url().endsWith('/api/v1/jobs'));
    await page.getByTestId('enhance-selected').click();
    expect((await normalJob).postDataJSON().recipe.hubble_strength).toBe(0);
    await expect(page.getByTestId('result-note')).not.toContainText('Hubble-style');
  });
});
