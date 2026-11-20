import { expect, test } from '@playwright/test';
import { collectConsoleErrors, enhanceAndWait, resetBackend, uploadAndWaitReady } from './helpers';

test.describe('one-button polish: Simple panel, Auto, live preview, preset quick looks', () => {
  test.beforeEach(async ({ request }) => {
    await resetBackend(request);
  });

  test('Simple panel by default, Auto explains its choice, live preview before saving', async ({ page }) => {
    const errors = collectConsoleErrors(page);
    await page.goto('/');
    await uploadAndWaitReady(page);

    // Simple: the preset, three sliders and Enhance; everything else is one click away and the choice is remembered.
    await expect(page.getByTestId('preset-select')).toHaveValue('auto');
    await expect(page.getByTestId('slider-stretch')).toBeVisible();
    await expect(page.getByTestId('slider-color')).toHaveCount(0);
    await expect(page.getByTestId('tone-disclosure')).toHaveCount(0);
    await expect(page.getByTestId('simple-note')).toContainText('All controls');
    await expect(page.getByTestId('auto-choice')).toContainText('Auto picks the style');

    await enhanceAndWait(page);
    await expect(page.getByTestId('auto-choice')).toContainText('Auto chose');
    await expect(page.getByTestId('result-note')).toBeVisible();
    await expect(page.getByTestId('settings-changed')).toHaveCount(0);

    // Moving a Look slider makes the settings the user's own and shows them live, without saving a result.
    await page.getByTestId('slider-stretch').fill('0.5');
    await expect(page.getByTestId('preset-select')).toHaveValue('custom');
    await expect(page.getByTestId('settings-changed')).toBeVisible();
    await expect(page.getByTestId('label-enhanced')).toHaveText('Live preview (not saved)', { timeout: 60_000 });
    await expect(page.getByTestId('live-status')).toContainText('Showing your new settings');
    await expect(page.getByTestId('run-select').locator('option')).toHaveCount(1);
    await expect(page.getByTestId('reprocess-button')).toHaveText('Save this result');
    await page.getByTestId('reprocess-button').click();
    await expect(page.getByTestId('run-select').locator('option')).toHaveCount(2, { timeout: 60_000 });
    await expect(page.getByTestId('settings-changed')).toHaveCount(0);
    await expect(page.getByTestId('label-enhanced')).toHaveText('Enhanced');

    // Restore the first result's settings (Auto) from the history; nothing is reprocessed until asked.
    const first = await page.getByTestId('run-select').locator('option').nth(1).getAttribute('value');
    await page.getByTestId('run-select').selectOption(first as string);
    await page.getByTestId('use-run-settings').click();
    await expect(page.getByTestId('preset-select')).toHaveValue('auto');
    await expect(page.getByTestId('use-run-settings')).toBeDisabled();
    await expect(page.getByTestId('run-select').locator('option')).toHaveCount(2);

    // All controls is remembered across reloads; live preview can be switched off.
    await page.getByTestId('panel-all').click();
    await expect(page.getByTestId('slider-color')).toBeVisible();
    await page.reload();
    await expect(page.getByTestId('slider-color')).toBeVisible();
    await expect(page.getByTestId('panel-all')).toHaveAttribute('aria-pressed', 'true');
    await page.getByTestId('switch-live').uncheck({ force: true });
    await expect(page.getByTestId('switch-live')).not.toBeChecked();

    expect(errors).toEqual([]);
  });

  test('preset quick looks render on this image and select a preset with one click', async ({ page }) => {
    await page.goto('/');
    await uploadAndWaitReady(page);
    await page.getByTestId('preview-presets').click();
    const vivid = page.getByTestId('preset-thumb-vivid');
    await expect(vivid).toBeVisible({ timeout: 60_000 });
    await expect(page.getByTestId('preset-thumb-auto')).toContainText('→');
    await expect.poll(() => vivid.locator('img').evaluate((img: HTMLImageElement) => img.naturalWidth)).toBeGreaterThan(0);
    await vivid.click();
    await expect(page.getByTestId('preset-select')).toHaveValue('vivid');
    await expect(vivid).toHaveClass(/active/);
  });
});
