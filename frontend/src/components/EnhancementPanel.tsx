import type { ReactNode } from 'react';
import type { AITool, Asset, AutoPresetChoice, Job, Preset, Recipe, Strength } from '../api/types';
import type { AIModels } from '../hooks/useAIModels';
import type { ReferenceData } from '../hooks/useReferenceData';
import type { LiveStatus } from '../hooks/useLivePreview';
import { usePersistent } from '../hooks/usePersistent';
import { backgroundPending, isMono } from '../lib/recipe';
import type { BgDraft, ViewerTool } from '../types/ui';
import { AdvancedPanel } from './AdvancedPanel';
import { AIToolsPanel } from './AIToolsPanel';
import { BackgroundPanel } from './BackgroundPanel';
import { ColorTools } from './ColorTools';
import { StrengthButtons, Switch } from './Controls';
import { JobStatus } from './JobStatus';
import { LabelRegionTool } from './LabelRegionTool';
import { LookControls } from './LookControls';
import { PresetBar } from './PresetBar';
import { ToneControls } from './ToneControls';

interface StarState {
  on: boolean;
  loading: boolean;
  result: import('../api/types').StarMaskResult | null;
  onToggle: (on: boolean) => void;
}

export interface EnhancementPanelProps {
  recipe: Recipe | null;
  presets: Preset[];
  presetId: string;
  edit: (mutate: (r: Recipe) => void) => void;
  setAI: (tool: AITool, on: boolean) => void;
  aiModels: AIModels;
  referenceData: ReferenceData;
  selectPreset: (id: string) => void;
  savePreset: (name: string) => Promise<void>;
  reloadPresets: () => Promise<void>;
  asset: Asset | null;
  assets: Asset[];
  selectedReady: number;
  allReady: number;
  submitting: boolean;
  settingsChanged: boolean;
  onEnhanceSelected: () => void;
  hubbleStrength: number;
  onHubbleStrength: (strength: number) => void;
  onEnhanceHubble?: () => void;
  onEnhanceAll: () => void;
  onReprocess: () => void;
  jobs: Job[];
  cancelling: boolean;
  onCancel: () => void;
  bgDraft: BgDraft | null;
  patchBgDraft: (fn: (d: BgDraft) => BgDraft) => void;
  tool: ViewerTool;
  onTool: (t: ViewerTool) => void;
  labelLineY: number | null;
  onLabelLine: (y: number | null) => void;
  star: StarState;
  onChangeState: () => void;
  onAssetUpdated: (a: Asset) => void;
  autoChoice: AutoPresetChoice | null;
  live: { on: boolean; onToggle: (on: boolean) => void; status: LiveStatus; current: boolean; error: string | null; seconds: number | null };
}

interface OptionRowProps {
  id: string;
  label: string;
  hint: string;
  checked: boolean;
  disabled?: boolean;
  strength?: Strength;
  onChecked: (v: boolean) => void;
  onStrength?: (s: Strength) => void;
  children?: ReactNode;
}

function OptionRow(p: OptionRowProps) {
  return (
    <div className={`option-row${p.checked && !p.disabled ? ' on' : ''}`}>
      <div className="option-head">
        <Switch checked={p.checked && !p.disabled} disabled={p.disabled} onChange={p.onChecked} label={p.label} testId={`switch-${p.id}`} describedBy={`hint-${p.id}`} />
        {p.strength && p.onStrength && p.checked && !p.disabled && (
          <StrengthButtons value={p.strength} onChange={p.onStrength} label={p.label} testId={`strength-${p.id}`} />
        )}
      </div>
      <p className="option-hint" id={`hint-${p.id}`}>{p.hint}</p>
      {p.children}
    </div>
  );
}

const PANEL_MODES = ['simple', 'all'] as const;

function liveText(l: EnhancementPanelProps['live']): string {
  if (l.status === 'failed') return l.error ?? 'The live preview could not be made.';
  if (l.status === 'waiting' || l.status === 'working') return 'Updating the live preview…';
  if (l.status === 'ready' && l.current) return `Showing your new settings (not saved${l.seconds ? `, ${l.seconds.toFixed(1)} s` : ''}).`;
  return 'Shows changed settings on the image before you save a result.';
}

export function EnhancementPanel(p: EnhancementPanelProps) {
  const [mode, setMode] = usePersistent('eae.panel', 'simple', PANEL_MODES);
  const { recipe, asset } = p;
  if (!recipe) {
    return <aside className="panel" aria-label="Enhancement settings"><p className="muted pad">Loading settings…</p></aside>;
  }
  const simple = mode === 'simple';
  const mono = isMono(asset);
  const pending = p.assets.filter((a) => a.status === 'ready' && backgroundPending(recipe, a));
  const blocked = asset !== null && asset.status === 'needs_input';
  const hasLabelRegion = asset !== null && asset.regions.length > 0;
  const busy = p.submitting || p.jobs.length > 0;
  const hiddenOn = [
    recipe.ai.background && 'AI background', recipe.ai.denoise && 'AI noise reduction', recipe.ai.stars && 'AI star separation', recipe.ai.sharpen && 'AI sharpening',
    recipe.catalog_builtin && 'accurate star colours',
    recipe.background.enabled && 'background from sky samples', !recipe.tone.enabled && 'stretch off',
  ].filter(Boolean) as string[];

  let why: string | null = null;
  if (p.allReady === 0) {
    why = blocked && asset?.questions.length === 0
      ? 'Enhancement is blocked until you confirm how this image was saved.'
      : 'Add a photo and wait until it is ready.';
  } else if (p.selectedReady === 0) {
    why = 'Select a ready image in the queue, or use Enhance all ready images.';
  }

  return (
    <aside className="panel" aria-label="Enhancement settings">
      <div className="panel-scroll">
        <div className="panel-mode">
          <div className="segmented small" role="group" aria-label="Controls shown">
            <button type="button" className={`seg${simple ? ' active' : ''}`} aria-pressed={simple} onClick={() => setMode('simple')} data-testid="panel-simple">Simple</button>
            <button type="button" className={`seg${simple ? '' : ' active'}`} aria-pressed={!simple} onClick={() => setMode('all')} data-testid="panel-all">All controls</button>
          </div>
        </div>
        <PresetBar presets={p.presets} presetId={p.presetId} disabled={false} onSelect={p.selectPreset} onSave={p.savePreset} onChanged={p.reloadPresets}
          asset={asset} recipe={recipe} />

        <LookControls look={recipe.look} stretchOn={recipe.tone.enabled && !(recipe.focus_stretch.enabled && asset?.baseline?.domain === 'linear')} mono={mono} edit={p.edit}
          simple={simple} auto={recipe.auto_preset} autoChoice={recipe.auto_preset ? p.autoChoice : null} />

        {simple && (
          <p className="muted small" data-testid="simple-note">
            {hiddenOn.length > 0 ? `Also on: ${hiddenOn.join(', ')}. ` : ''}
            Color, detail, AI tools, tone and more are in <button type="button" className="link-btn" onClick={() => setMode('all')}>All controls</button>.
          </p>
        )}

        {!simple && (<>
        <AIToolsPanel ai={recipe.ai} asset={asset} models={p.aiModels} onToggle={p.setAI}
          onStarBrightness={(factor) => p.edit((r) => { r.ai.star_brightness = factor; })}
          onChange={(patch) => p.edit((r) => { Object.assign(r.ai, patch); })} />

        <div className="options">
          <OptionRow id="background" label="Correct background from my sky samples" checked={recipe.background.enabled} strength={recipe.background.strength}
            hint="Optional: correct the background from sky regions you confirm for this image. The automatic background steps already run without it."
            onChecked={(v) => p.edit((r) => { r.background.enabled = v; })} onStrength={(s) => p.edit((r) => { r.background.strength = s; })}>
            {recipe.background.enabled && asset && (
              <BackgroundPanel
                asset={asset}
                recipe={recipe}
                draft={p.bgDraft as BgDraft}
                tool={p.tool}
                pendingNames={pending.map((a) => a.filename)}
                edit={p.edit}
                patchDraft={p.patchBgDraft}
                onTool={p.onTool}
                onAssetUpdated={p.onAssetUpdated}
              />
            )}
          </OptionRow>
          <OptionRow id="labels" label="Preserve labels" checked={recipe.protect_regions}
            hint={hasLabelRegion ? 'Confirmed label areas stay untouched.' : 'Only used once a label region is confirmed for an image.'}
            onChecked={(v) => p.edit((r) => { r.protect_regions = v; })} />
        </div>

        <ToneControls tone={recipe.tone} histogram={asset?.baseline?.histogram ?? null} edit={p.edit} />
        <ColorTools asset={asset} recipe={recipe} edit={p.edit} busy={busy} hubbleStrength={p.hubbleStrength}
          onHubbleStrength={p.onHubbleStrength} onAssetUpdated={p.onAssetUpdated} starsReady={p.referenceData.starsReady} />

        {asset && (
          <LabelRegionTool asset={asset} tool={p.tool} lineY={p.labelLineY} onTool={p.onTool} onLineY={p.onLabelLine} onAssetUpdated={p.onAssetUpdated} />
        )}

        <AdvancedPanel asset={asset} recipe={recipe} edit={p.edit} star={p.star} onChangeState={p.onChangeState} onAssetUpdated={p.onAssetUpdated}
          starsReady={p.referenceData.starsReady} />
        </>)}
      </div>

      <div className="panel-actions">
        <div className="live-row" data-testid="live-row">
          <Switch checked={p.live.on} onChange={p.live.onToggle} label="Live preview" testId="switch-live" describedBy="hint-live" />
          <p className={`option-hint${p.live.status === 'failed' ? ' warn-text' : ''}`} id="hint-live" data-testid="live-status">{liveText(p.live)}</p>
        </div>
        {p.settingsChanged && (
          <div className="changed-row">
            <span className="badge warn" data-testid="settings-changed">Settings changed</span>
            <button type="button" className="btn small" disabled={busy || !asset?.can_process} onClick={p.onReprocess} data-testid="reprocess-button"
              title={p.live.current ? 'Saves the live preview as a new result (no recomputation needed)' : undefined}>
              {p.live.status === 'ready' && p.live.current ? 'Save this result' : 'Reprocess'}
            </button>
          </div>
        )}
        <button type="button" className="btn primary big" disabled={busy || p.selectedReady === 0} onClick={p.onEnhanceSelected} data-testid="enhance-selected">
          Enhance selected
          <small>{p.selectedReady} selected</small>
        </button>
        {p.onEnhanceHubble && (
          <button type="button" className="btn big" disabled={busy} onClick={p.onEnhanceHubble}>
            Enhance Hubble-style
            <small>This image only · Gold and teal, not SHO</small>
          </button>
        )}
        <button type="button" className="btn big" disabled={busy || p.allReady === 0} onClick={p.onEnhanceAll} data-testid="enhance-all">
          Enhance all ready images
          <small>{p.allReady} ready</small>
        </button>
        {why && <p className="muted small">{why}</p>}
        <p className="muted small">The same settings apply to every image. Sky regions and labels always stay with their own image.</p>
        <JobStatus jobs={p.jobs} cancelling={p.cancelling} onCancel={p.onCancel} />
      </div>
    </aside>
  );
}
