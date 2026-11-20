import type { AIOverview, AIRecipe, AITool, Asset } from '../api/types';
import type { AIModels } from '../hooks/useAIModels';
import { Switch } from './Controls';

const TOOLS: { tool: AITool; label: string; hint: string; linearOnly: boolean }[] = [
  {
    tool: 'background', label: 'AI background extraction', linearOnly: true,
    hint: 'Removes light pollution and gradients with GraXpert’s trained model, even around large galaxies and nebulae. Replaces the automatic gradient step.',
  },
  {
    tool: 'denoise', label: 'AI noise reduction', linearOnly: false,
    hint: 'GraXpert’s denoising model removes grain and color mottle; strength follows the Noise reduction slider. Replaces wavelet noise reduction.',
  },
  {
    tool: 'stars', label: 'AI star separation', linearOnly: true,
    hint: 'Dark Star separates the stars so the galaxy or nebula can be enhanced on its own.',
  },
  {
    tool: 'sharpen', label: 'AI sharpening', linearOnly: true,
    hint: 'Cosmic Clarity sharpens fine structure and tightens stars blurred by seeing and focus. Replaces deconvolution; skipped on very noisy images.',
  },
];

interface PercentSliderProps {
  id: string;
  label: string;
  value: number;
  min?: number;
  hint: string;
  onChange: (v: number) => void;
}

function PercentSlider({ id, label, value, min = 0, hint, onChange }: PercentSliderProps) {
  const pct = Math.round(value * 100);
  return (
    <div className="slider-row">
      <div className="slider-head">
        <label htmlFor={id}>{label}</label>
        <output className="slider-value" htmlFor={id}>{pct}%</output>
      </div>
      <div className="range-wrap">
        <input id={id} type="range" min={min} max={100} step={1} value={pct} aria-describedby={`hint-${id}`} aria-valuetext={`${pct}%`}
          onChange={(e) => onChange(e.currentTarget.valueAsNumber / 100)} />
      </div>
      <p className="slider-hint" id={`hint-${id}`}>{hint}</p>
    </div>
  );
}

function mb(bytes: number): string {
  return `${Math.round(bytes / 1e6)} MB`;
}

interface ToolStatusProps {
  tool: AITool;
  overview: AIOverview;
  models: AIModels;
}

function ToolStatus({ tool, overview, models }: ToolStatusProps) {
  const info = overview.tools[tool];
  const parts = overview.models.filter((m) => info.models.includes(m.id));
  if (info.state === 'installed') return <span className="ai-state ok" data-testid={`ai-state-${tool}`}>Ready</span>;
  if (info.state === 'downloading') {
    const total = parts.reduce((s, m) => s + m.size, 0);
    const got = parts.reduce((s, m) => s + (m.state === 'installed' ? m.size : m.received), 0);
    return (
      <span className="ai-state" data-testid={`ai-state-${tool}`}>
        Downloading {Math.round((100 * got) / Math.max(total, 1))}%{' '}
        <button type="button" className="btn tiny" onClick={() => void models.cancel(tool)}>Cancel</button>
      </span>
    );
  }
  const failed = parts.find((m) => m.state === 'error');
  return (
    <span className="ai-state" data-testid={`ai-state-${tool}`}>
      {failed ? <span className="err-text">{failed.error}</span> : 'Model not downloaded'}{' '}
      <button type="button" className="btn tiny" onClick={() => void models.download(tool)} data-testid={`ai-download-${tool}`}>
        {failed ? 'Retry' : `Download (${mb(info.download_bytes)})`}
      </button>
    </span>
  );
}

interface AIToolsPanelProps {
  ai: AIRecipe;
  asset: Asset | null;
  models: AIModels;
  onToggle: (tool: AITool, on: boolean) => void;
  onStarBrightness: (factor: number) => void;
  onChange: (patch: Partial<AIRecipe>) => void;
}

export function AIToolsPanel({ ai, asset, models, onToggle, onStarBrightness, onChange }: AIToolsPanelProps) {
  const o = models.overview;
  const linear = asset?.interpretation.state === 'linear';
  const rendered = asset?.format === 'jpeg' || asset?.interpretation.state === 'rendered';
  return (
    <section className="ai-tools" aria-labelledby="ai-tools-title" data-testid="ai-tools">
      <h3 id="ai-tools-title">AI tools <span className="muted small">optional</span></h3>
      <p className="muted small">
        AI processing can take much longer without a compatible GPU, especially noise reduction on large images.
        Leave these tools off for faster, standard enhancement.
      </p>
      {o && !o.runtime_available && <p className="warn-text small">The AI runtime is not installed, so these tools are unavailable.</p>}
      {TOOLS.map((t) => (
        <div key={t.tool} className={`option-row${ai[t.tool] ? ' on' : ''}`}>
          <div className="option-head">
            <Switch checked={ai[t.tool]} onChange={(v) => onToggle(t.tool, v)} label={t.label} testId={`switch-ai-${t.tool}`} describedBy={`hint-ai-${t.tool}`} />
          </div>
          <p className="option-hint" id={`hint-ai-${t.tool}`}>
            {t.hint}
            {t.linearOnly && rendered && ai[t.tool] ? ' Not used on this image: it works on linear stacks only.' : ''}
          </p>
          {ai[t.tool] && o && <ToolStatus tool={t.tool} overview={o} models={models} />}
          {t.tool === 'stars' && ai.stars && linear && (
            <>
              <PercentSlider id="ai-star-brightness" label="Star brightness" value={ai.star_brightness} onChange={onStarBrightness}
                hint="100% keeps the usual blend. 0% leaves out the separated stars; some stars may remain. Applies on your next enhancement, not to the linear data." />
              <PercentSlider id="ai-star-size" label="Star size" value={ai.star_size} min={50} onChange={(v) => onChange({ star_size: v })}
                hint="100% keeps the stars as recorded. Lower values shrink each star's glow toward its core, keeping its centre, colour and peak brightness; display only." />
            </>
          )}
          {t.tool === 'sharpen' && ai.sharpen && (
            <PercentSlider id="ai-sharpen-amount" label="Sharpening strength" value={ai.sharpen_amount} onChange={(v) => onChange({ sharpen_amount: v })}
              hint="How strongly galaxy and nebula detail is sharpened. Star sharpening is in Advanced." />
          )}
        </div>
      ))}
      <p className="muted small" data-testid="ai-disclosure">
        These tools run trained neural networks on this computer{o?.provider_label ? ` (${o.provider_label})` : ''}. They predict cleaner
        pixel values from your image — no prompts or reference images — but can smooth away the faintest detail or add texture when pushed.
        Every result’s report names the model used. GraXpert models: CC BY-NC-SA 4.0, non-commercial use; Dark Star and Cosmic Clarity: MIT.
      </p>
    </section>
  );
}
