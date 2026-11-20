import { expect, test } from '@playwright/test';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { collectConsoleErrors, resetBackend, showAllControls, uploadAndWaitReady } from './helpers';

const monoFits = path.join(path.dirname(fileURLToPath(import.meta.url)), 'fixtures', 'mono-linear.fits');

test.describe('AI tools', () => {
  test.beforeEach(async ({ page, request }) => {
    await resetBackend(request);
    await showAllControls(page);
  });

  test('opt-in switches show model status, survive preset changes and are listed in Settings', async ({ page }) => {
    const errors = collectConsoleErrors(page);
    await page.goto('/');
    await uploadAndWaitReady(page);
    const panel = page.getByTestId('ai-tools');
    await expect(panel).toBeVisible();
    await expect(panel.getByText(/AI processing can take much longer without a compatible GPU/)).toBeVisible();
    for (const tool of ['background', 'denoise', 'stars']) {
      await expect(page.getByTestId(`switch-ai-${tool}`)).not.toBeChecked();  // AI is never on by default
    }
    await expect(page.getByTestId('ai-disclosure')).toContainText('trained neural networks');
    await page.getByTestId('switch-ai-denoise').check({ force: true });
    await expect(page.getByTestId('ai-state-denoise')).toContainText('Model not downloaded');
    await expect(page.getByTestId('ai-download-denoise')).toContainText(/Download \(\d+ MB\)/);
    await page.getByTestId('preset-select').selectOption('vivid');
    await expect(page.getByTestId('switch-ai-denoise')).toBeChecked();  // built-in presets keep the AI switches
    await page.getByTestId('settings-button').click();
    const section = page.getByTestId('ai-models-section');
    await expect(section).toContainText('GraXpert denoising');
    await expect(section).toContainText('CC BY-NC-SA 4.0');
    await expect(section).toContainText('Dark Star');
    await expect(section.locator('tr')).toHaveCount(4);
    expect(errors).toEqual([]);
  });

  test('star brightness is opt-in on linear stacks and is sent with the enhancement', async ({ page }) => {
    await page.goto('/');
    await page.getByTestId('file-input').setInputFiles(monoFits);
    await page.getByTestId('intake-option-linear').click({ timeout: 30_000 });
    await expect(page.getByTestId('asset-status')).toHaveText('Ready', { timeout: 30_000 });
    const slider = page.getByRole('slider', { name: 'Star brightness' });
    const stars = page.getByTestId('switch-ai-stars');
    await expect(slider).toBeHidden();
    await stars.check({ force: true });
    await expect(slider).toHaveValue('100');
    await slider.fill('0');
    await page.getByTestId('preset-select').selectOption('vivid');
    await expect(slider).toHaveValue('0');
    const job = page.waitForRequest((req) => req.method() === 'POST' && new URL(req.url()).pathname === '/api/v1/jobs');
    await page.getByTestId('enhance-selected').click();
    expect((await job).postDataJSON().recipe.ai).toMatchObject({ stars: true, star_brightness: 0 });
    await expect(page.getByTestId('asset-status')).toHaveText(/^Complete/, { timeout: 60_000 });
  });
});
