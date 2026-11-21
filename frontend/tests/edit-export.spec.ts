import { expect, test } from '@playwright/test';
import { readFile } from 'node:fs/promises';
import { enhanceAndWait, resetBackend, uploadAndWaitReady } from './helpers';

test('edit and download the enhanced framing with text while retaining the regular export', async ({ page, request }) => {
  await resetBackend(request);
  await page.goto('/');
  await uploadAndWaitReady(page);
  await enhanceAndWait(page);
  const normal = page.getByTestId('download-png');
  const originalURL = (await normal.getAttribute('href'))!;
  const original = await (await request.get(originalURL)).body();
  await page.getByRole('button', { name: 'Edit export…' }).click();
  const editor = page.getByRole('dialog', { name: 'Edit export' });
  const preview = editor.getByRole('img', { name: 'Edited export preview' });
  await expect(preview).toBeVisible();
  await editor.getByRole('button', { name: 'Rotate right 90°' }).click();
  await expect(editor.getByRole('slider', { name: 'Rotation' })).toHaveValue('90');
  await editor.getByRole('slider', { name: 'Export zoom' }).fill('2');
  await preview.focus();
  await preview.press('ArrowRight');
  await editor.getByLabel('Label text', { exact: true }).fill('Galaxy Photos');
  await editor.getByLabel('Include target name').check();
  await expect(editor.getByText('No FITS target name found.', { exact: false })).toBeVisible();
  await editor.getByLabel('Target name', { exact: true }).fill('M 31');
  const style = editor.getByTestId('text-style');
  await style.getByLabel('Font').selectOption('mono');
  await style.getByLabel('Text colour').fill('#ffd080');
  await style.getByLabel('Dark box behind the text').uncheck();
  await style.getByLabel('Target name position').selectOption('top-center');
  await style.getByLabel('Target name size').fill('1.5');
  await style.getByLabel('Label text position').selectOption('bottom-right');
  const exportRequest = page.waitForRequest((req) => req.url().endsWith('/edit-export?preview=false'));
  const download = page.waitForEvent('download');
  await editor.getByRole('button', { name: 'Download edited image' }).click();
  expect((await exportRequest).postDataJSON()).toMatchObject({
    rotation: 90, zoom: 2, pan_x: 0.1, label: 'Galaxy Photos', target: 'M 31', format: 'png',
    text_style: { font: 'mono', color: '#ffd080', box: false },
    target_place: { position: 'top-center', size: 1.5 }, label_place: { position: 'bottom-right', size: 1 },
  });
  const file = await download;
  expect(file.suggestedFilename()).toMatch(/-edited\.png$/);
  const bytes = await readFile(await file.path());
  expect(bytes.readUInt32BE(16)).toBe(Math.round(original.readUInt32BE(20) / 2));
  expect(bytes.readUInt32BE(20)).toBe(Math.round(original.readUInt32BE(16) / 2));
  expect(bytes[24]).toBe(16);
  expect(bytes.includes('Galaxy Photos')).toBe(true);
  await editor.getByRole('button', { name: 'Cancel' }).click();
  await expect(normal).toHaveAttribute('href', originalURL);

  // The label text and text style are remembered for the next export; the target name is not.
  await page.getByRole('button', { name: 'Edit export…' }).click();
  await expect(editor.getByLabel('Label text', { exact: true })).toHaveValue('Galaxy Photos');
  await expect(editor.getByLabel('Include target name')).not.toBeChecked();
  await expect(editor.getByTestId('text-style').getByLabel('Font')).toHaveValue('mono');
  await expect(editor.getByTestId('text-style').getByLabel('Label text position')).toHaveValue('bottom-right');
});

test('Help explains how to use the app', async ({ page, request }) => {
  await resetBackend(request);
  await page.goto('/');
  await page.getByTestId('help-button').click();
  const help = page.getByTestId('help-dialog');
  await expect(help.getByTestId('help-start')).toHaveAttribute('open', '');
  await expect(help).toContainText('Enhance selected');
  await help.getByText('Sky position, star colours and annotations').click();
  await expect(help.getByTestId('help-sky')).toContainText('Settings → Reference data');
  await help.getByRole('button', { name: 'Close dialog' }).click();
  await expect(help).toHaveCount(0);
});
