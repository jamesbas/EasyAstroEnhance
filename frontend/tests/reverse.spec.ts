import { expect, test } from '@playwright/test';
import fs from 'node:fs';
import { collectConsoleErrors, enhanceAndWait, resetBackend, TEST_JPEG } from './helpers';

test.describe('reversing steps: remove a step, undo/redo, reset, go back to or delete a result', () => {
  test.beforeEach(async ({ request }) => {
    await resetBackend(request);
  });

  test('remove a step, undo and redo it, save; go back to the first result; delete the other', async ({ page }) => {
    const errors = collectConsoleErrors(page);
    await page.goto('/');
    const buffer = fs.readFileSync(TEST_JPEG);
    await page.getByTestId('file-input').setInputFiles([
      { name: 'first.jpg', mimeType: 'image/jpeg', buffer },
      { name: 'second.jpg', mimeType: 'image/jpeg', buffer },
    ]);
    await expect(page.getByTestId('asset-status')).toHaveText(['Ready', 'Ready'], { timeout: 30_000 });
    await page.getByTestId('asset-card').first().getByRole('button', { name: /^Show/ }).click();
    await page.getByTestId('enhance-selected').click();
    await expect(page.getByTestId('asset-status').first()).toHaveText(/^Complete/, { timeout: 60_000 });
    await expect(page.getByTestId('undo')).toBeDisabled();

    // The result lists the steps that can be removed; removing one turns its setting off and previews the result.
    const chips = page.getByTestId('remove-steps').locator('button:not([disabled])');
    await expect(chips.first()).toBeVisible();
    const chip = chips.first();
    const testId = await chip.getAttribute('data-testid');
    await chip.click();
    const removed = page.getByTestId(testId as string);
    await expect(removed).toBeDisabled();
    await expect(page.getByTestId('settings-changed')).toBeVisible();
    await expect(page.getByTestId('label-enhanced')).toHaveText('Live preview (not saved)', { timeout: 60_000 });

    // Undo brings it back (button and Ctrl+Z), Redo removes it again.
    await page.getByTestId('undo').click();
    await expect(removed).toBeEnabled();
    await expect(page.getByTestId('settings-changed')).toHaveCount(0);
    await page.getByTestId('redo').click();
    await expect(removed).toBeDisabled();
    await page.locator('body').press('Control+z');
    await expect(removed).toBeEnabled();
    await page.locator('body').press('Control+Shift+z');
    await expect(removed).toBeDisabled();

    // The history belongs to the image: the second image has none.
    await page.getByTestId('asset-card').nth(1).getByRole('button', { name: /^Show/ }).click();
    await expect(page.getByTestId('undo')).toBeDisabled();
    await page.getByTestId('asset-card').first().getByRole('button', { name: /^Show/ }).click();
    await expect(page.getByTestId('undo')).toBeEnabled();

    // Save the result without the step: it becomes Run 2 and no longer lists that step.
    await expect(page.getByTestId('reprocess-button')).toHaveText('Save this result', { timeout: 60_000 });
    await page.getByTestId('reprocess-button').click();
    await expect(page.getByTestId('run-select').locator('option')).toHaveCount(2, { timeout: 60_000 });
    await expect(page.getByTestId(testId as string)).toHaveCount(0);
    await expect(page.getByTestId('run-select').locator('option').first()).toContainText('(current)');

    // Go back to Run 1: it becomes the image's result and its settings are loaded (nothing is reprocessed).
    const first = await page.getByTestId('run-select').locator('option').nth(1).getAttribute('value');
    await page.getByTestId('run-select').selectOption(first as string);
    await page.getByTestId('make-current').click();
    await expect(page.getByTestId('toast-success')).toContainText('Run 1 is this image');
    await expect(page.getByTestId('run-select')).toHaveValue(first as string);
    await expect(page.getByTestId('run-select').locator('option', { hasText: '(current)' })).toContainText('Run 1');
    await expect(page.getByTestId('settings-changed')).toHaveCount(0);
    await expect(page.getByTestId(testId as string)).toBeEnabled();  // Run 1 still has the step
    await expect(page.getByTestId('make-current')).toHaveCount(0);

    // Delete Run 2 after confirming; Run 1 stays.
    const second = await page.getByTestId('run-select').locator('option', { hasText: 'Run 2' }).getAttribute('value');
    await page.getByTestId('run-select').selectOption(second as string);
    await page.getByTestId('delete-run').click();
    await expect(page.getByTestId('delete-run-confirm')).toContainText('Delete Run 2?');
    await page.getByTestId('delete-run-yes').click();
    await expect(page.getByTestId('run-select').locator('option')).toHaveCount(1);
    await expect(page.getByTestId('run-select').locator('option')).toContainText('Run 1');
    expect(errors).toEqual([]);
  });

  test('Reset to defaults returns to Auto and can be undone', async ({ page }) => {
    await page.goto('/');
    await page.getByTestId('file-input').setInputFiles(TEST_JPEG);
    await expect(page.getByTestId('asset-status')).toHaveText('Ready');
    await enhanceAndWait(page);
    await page.getByTestId('slider-stretch').fill('0.5');
    await expect(page.getByTestId('preset-select')).toHaveValue('custom');
    await page.getByTestId('reset-defaults').click();
    await expect(page.getByTestId('preset-select')).toHaveValue('auto');
    await page.getByTestId('undo').click();
    await expect(page.getByTestId('preset-select')).toHaveValue('custom');
    await expect(page.getByTestId('slider-stretch')).toHaveValue('0.5');
  });
});
