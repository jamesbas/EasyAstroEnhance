import type { ReactNode } from 'react';
import { Modal } from './Modal';

interface Topic {
  id: string;
  title: string;
  body: ReactNode;
}

const TOPICS: Topic[] = [
  {
    id: 'start',
    title: 'Quick start',
    body: (
      <ol>
        <li><strong>Add files</strong> (or <strong>Import from Seestar…</strong>): JPEG, TIFF or FITS. A Seestar stacked FITS (<code>Stacked_….fit</code>) gives the best result.</li>
        <li>Answer the short question about how the image was saved, if asked (the recommended answer is pre-selected).</li>
        <li>Leave the preset on <strong>Auto</strong> and click <strong>Enhance selected</strong> (or <strong>Enhance all ready images</strong>).</li>
        <li>Compare with <strong>Divider</strong>, <strong>Side by side</strong> or <strong>Blink</strong>, then <strong>Download PNG</strong> or pick a format under <strong>More formats</strong>.</li>
      </ol>
    ),
  },
  {
    id: 'look',
    title: 'Changing the look',
    body: (
      <ul>
        <li><strong>Auto</strong> measures each image and picks a style; the reason is shown above the sliders. <strong>Preview presets on this image</strong> shows small quick looks of every preset.</li>
        <li><strong>Simple</strong> shows Sky brightness, Stretch and Noise reduction; <strong>All controls</strong> adds Contrast, Color, Detail, Star color, Advanced, colour tools and AI tools.</li>
        <li>After a first result, changed settings appear at once as a <strong>Live preview (not saved)</strong>. Click <strong>Save this result</strong> to keep it.</li>
        <li>Settings apply to every image; sky regions and labels stay with their own image.</li>
      </ul>
    ),
  },
  {
    id: 'undo',
    title: 'Taking a step back',
    body: (
      <ul>
        <li><strong>Remove a step</strong> under a result turns off one thing it did (for example <em>Detail enhanced</em>) and previews the result without it.</li>
        <li><strong>Undo</strong> / <strong>Redo</strong> at the top of the panel, or Ctrl+Z / Ctrl+Y, step through your settings changes (kept separately for each image).</li>
        <li><strong>Reset to defaults</strong> returns to Auto with every optional tool off.</li>
        <li>In the result list: <strong>Go back to this result</strong> makes an earlier result the current one, <strong>Use these settings</strong> loads its settings, and <strong>Delete…</strong> removes a result. Your original file is never changed.</li>
      </ul>
    ),
  },
  {
    id: 'stack',
    title: 'Seestar import and stacking',
    body: (
      <ul>
        <li><strong>Import from Seestar…</strong> finds your MyWorks folder and lists targets, newest first. <strong>Add newest stack</strong> copies the telescope's stack into the app (the original is only read).</li>
        <li><strong>Stack frames…</strong> stacks a folder of sub-frames (a <code>…_sub</code> folder), mosaics, or a Moon/Sun/planet video. Calibration frames are optional. Tick <strong>Enhance automatically</strong> to enhance as soon as stacking finishes.</li>
      </ul>
    ),
  },
  {
    id: 'sky',
    title: 'Sky position, star colours and annotations',
    body: (
      <ul>
        <li>Some tools need to know where the image points on the sky. The app finds this by itself from a Seestar FITS file's header (a few seconds) the first time a tool needs it.</li>
        <li>It needs the free star catalog: <strong>Settings → Reference data</strong>. Labelling objects also needs the deep-sky object catalog there.</li>
        <li>If the position can't be found (for example a JPEG without coordinates), type the target's name in <strong>All controls → Advanced → Sky position</strong>.</li>
        <li><strong>Accurate star colours</strong> (All controls → Star colour) calibrates colour against catalog stars.</li>
      </ul>
    ),
  },
  {
    id: 'share',
    title: 'Sharing: Edit export',
    body: (
      <ul>
        <li><strong>Edit export…</strong> makes a separate sharing copy: rotate, zoom and drag to crop, or <strong>Crop stacking edges</strong>.</li>
        <li>Add your name (<strong>Label text</strong>, remembered for next time) and the <strong>target name</strong>. <strong>Text style</strong> sets the font, colour, dark box, and each text's position and size.</li>
        <li><strong>Annotations</strong> draw object labels, a compass and a scale bar. They become available once the sky position is known.</li>
        <li>Choose PNG (16-bit) or JPEG. Regular downloads are not changed.</li>
      </ul>
    ),
  },
  {
    id: 'ai',
    title: 'AI tools (optional)',
    body: (
      <ul>
        <li>Download the models in <strong>Settings → AI models</strong>, then switch tools on in <strong>All controls → AI tools</strong>: background extraction, noise reduction, sharpening and star separation (with Star brightness and Star size).</li>
        <li>They run on your computer only and are listed in every result's report. GPU memory is released after 60 seconds without AI work.</li>
      </ul>
    ),
  },
  {
    id: 'trouble',
    title: 'If something goes wrong',
    body: (
      <ul>
        <li>If an image fails, the reason is shown under it in the queue. Other images are not affected.</li>
        <li>The chip at the top shows whether processing uses the GPU or the CPU; change it in <strong>Settings → Processing device</strong>.</li>
        <li><strong>Settings → Storage</strong> shows the space results use and how many to keep per image; <strong>Settings → Local history</strong> clears the app's copies. Your original files elsewhere are never changed.</li>
        <li>Full guide and downloads: <a href="https://jamesbas.github.io/EasyAstroEnhance" target="_blank" rel="noreferrer">jamesbas.github.io/EasyAstroEnhance</a>.</li>
      </ul>
    ),
  },
];

export function HelpDialog({ onClose }: { onClose: () => void }) {
  return (
    <Modal title="How to use EasyAstroEnhance" wide onClose={onClose} testId="help-dialog">
      <div className="help">
        {TOPICS.map((t, i) => (
          <details key={t.id} open={i === 0} data-testid={`help-${t.id}`}>
            <summary>{t.title}</summary>
            {t.body}
          </details>
        ))}
      </div>
    </Modal>
  );
}
