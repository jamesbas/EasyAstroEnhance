import { expect, test } from '@playwright/test';
import { collectConsoleErrors, resetBackend, uploadAndWaitReady } from './helpers';

test.describe('AI tools', () => {
  test.beforeEach(async ({ request }) => {
    await resetBackend(request);
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
});
