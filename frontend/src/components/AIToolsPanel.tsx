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
    hint: 'Dark Star lifts the stars off so the galaxy or nebula is stretched and sharpened on its own; the stars are then added back, kept small.',
  },
];

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
}

export function AIToolsPanel({ ai, asset, models, onToggle }: AIToolsPanelProps) {
  const o = models.overview;
  const rendered = asset !== null && asset.interpretation.state !== 'linear' && asset.format !== 'fits';
  return (
    <section className="ai-tools" aria-labelledby="ai-tools-title" data-testid="ai-tools">
      <h3 id="ai-tools-title">AI tools <span className="muted small">optional</span></h3>
      {o && !o.runtime_available && <p className="warn-text small">The AI runtime is not installed, so these tools are unavailable.</p>}
      {TOOLS.map((t) => (
        <div key={t.tool} className={`option-row${ai[t.tool] ? ' on' : ''}`}>
          <div className="option-head">
            <Switch checked={ai[t.tool]} onChange={(v) => onToggle(t.tool, v)} label={t.label} testId={`switch-ai-${t.tool}`} describedBy={`hint-ai-${t.tool}`} />
          </div>
          <p className="option-hint" id={`hint-ai-${t.tool}`}>
            {t.hint}
            {t.linearOnly && rendered && ai[t.tool] ? ' Not used on this image: it works on linear stacks (FITS) only.' : ''}
          </p>
          {ai[t.tool] && o && <ToolStatus tool={t.tool} overview={o} models={models} />}
        </div>
      ))}
      <p className="muted small" data-testid="ai-disclosure">
        These tools run trained neural networks on this computer{o?.provider_label ? ` (${o.provider_label})` : ''}. They predict cleaner
        pixel values from your image — no prompts or reference images — but can smooth away the faintest detail or add texture when pushed.
        Every result’s report names the model used. GraXpert models: CC BY-NC-SA 4.0, non-commercial use; Dark Star: MIT.
      </p>
    </section>
  );
}
