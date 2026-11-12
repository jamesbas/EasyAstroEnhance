import { expect, test } from '@playwright/test';
import { collectConsoleErrors, resetBackend } from './helpers';

test.describe('empty state', () => {
  test.beforeEach(async ({ request }) => {
    await resetBackend(request);
  });

  test('shows the title, description, drop zone and helper text', async ({ page }) => {
    const errors = collectConsoleErrors(page);
    await page.goto('/');
    await expect(page.getByRole('heading', { name: 'EasyAstroEnhance' })).toBeVisible();
    await expect(page.getByText('Bring out the detail in your telescope photos.')).toBeVisible();
    const zone = page.getByTestId('drop-zone');
    await expect(zone).toContainText('Drop photos here or Choose files');
    await expect(zone.getByRole('button', { name: 'Choose files' })).toBeVisible();
    await expect(zone).toContainText('JPEG, TIFF, FITS • Multiple files supported • Processed on this computer');
    const input = page.getByTestId('file-input');
    await expect(input).toHaveAttribute('multiple', '');
    await expect(input).toHaveAttribute('accept', '.jpg,.jpeg,.tif,.tiff,.fit,.fits,.fts');
    expect(errors).toEqual([]);
  });

  test('settings dialog exposes the processing device choices and the status chip', async ({ page }) => {
    await page.goto('/');
    await expect(page.getByTestId('processing-chip')).toHaveText(/Processing: (CPU|GPU)/);
    await page.getByTestId('settings-button').click();
    const dialog = page.getByTestId('settings-dialog');
    await expect(dialog).toBeVisible();
    const select = page.getByTestId('device-select');
    await expect(select.locator('option')).toHaveText(['Auto', 'NVIDIA GPU', 'CPU']);
    await select.selectOption('cpu');
    await expect(page.getByTestId('resolved-label')).toContainText('Processing: CPU');
    await page.getByTestId('check-gpu').click();
    await expect(page.getByTestId('probe-details')).toBeVisible({ timeout: 60_000 });
    await expect(dialog.getByText('Remove location/observer details from shared exports')).toBeVisible();
    await select.selectOption('auto');
    await page.keyboard.press('Escape');
    await expect(dialog).toBeHidden();
  });

  test('clear local history needs an explicit confirmation', async ({ page }) => {
    await page.goto('/');
    await page.getByTestId('settings-button').click();
    await page.getByTestId('clear-history').click();
    await expect(page.getByTestId('history-confirm')).toContainText('This will remove');
    await page.getByTestId('confirm-clear-history').click();
    await expect(page.getByTestId('history-confirm')).toBeHidden();
  });
});
