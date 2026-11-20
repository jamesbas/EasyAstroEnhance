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
  await editor.getByLabel('Label text').fill('Galaxy Photos');
  await editor.getByLabel('Include target name').check();
  await expect(editor.getByText('No FITS target name found.', { exact: false })).toBeVisible();
  await editor.getByLabel('Target name', { exact: true }).fill('M 31');
  const exportRequest = page.waitForRequest((req) => req.url().endsWith('/edit-export?preview=false'));
  const download = page.waitForEvent('download');
  await editor.getByRole('button', { name: 'Download edited image' }).click();
  expect((await exportRequest).postDataJSON()).toMatchObject({
    rotation: 90, zoom: 2, pan_x: 0.1, label: 'Galaxy Photos', target: 'M 31', format: 'png',
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
});
