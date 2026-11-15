import type { ReactNode } from 'react';
import type { AITool, Asset, Job, Preset, Recipe, Strength } from '../api/types';
import type { AIModels } from '../hooks/useAIModels';
import { backgroundPending, isMono } from '../lib/recipe';
import type { BgDraft, ViewerTool } from '../types/ui';
import { AdvancedPanel } from './AdvancedPanel';
import { AIToolsPanel } from './AIToolsPanel';
import { BackgroundPanel } from './BackgroundPanel';
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

export function EnhancementPanel(p: EnhancementPanelProps) {
  const { recipe, asset } = p;
  if (!recipe) {
    return <aside className="panel" aria-label="Enhancement settings"><p className="muted pad">Loading settings…</p></aside>;
  }
  const mono = isMono(asset);
  const pending = p.assets.filter((a) => a.status === 'ready' && backgroundPending(recipe, a));
  const blocked = asset !== null && asset.status === 'needs_input';
  const hasLabelRegion = asset !== null && asset.regions.length > 0;
  const busy = p.submitting || p.jobs.length > 0;

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
        <PresetBar presets={p.presets} presetId={p.presetId} disabled={false} onSelect={p.selectPreset} onSave={p.savePreset} onChanged={p.reloadPresets} />

        <LookControls look={recipe.look} stretchOn={recipe.tone.enabled} mono={mono} edit={p.edit} />

        <AIToolsPanel ai={recipe.ai} asset={asset} models={p.aiModels} onToggle={p.setAI} />

        <div className="options">
          <OptionRow id="background" label="Manual sky regions" checked={recipe.background.enabled} strength={recipe.background.strength}
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

        {asset && (
          <LabelRegionTool asset={asset} tool={p.tool} lineY={p.labelLineY} onTool={p.onTool} onLineY={p.onLabelLine} onAssetUpdated={p.onAssetUpdated} />
        )}

        <AdvancedPanel asset={asset} recipe={recipe} edit={p.edit} star={p.star} onChangeState={p.onChangeState} onAssetUpdated={p.onAssetUpdated} />
      </div>

      <div className="panel-actions">
        {p.settingsChanged && (
          <div className="changed-row">
            <span className="badge warn" data-testid="settings-changed">Settings changed</span>
            <button type="button" className="btn small" disabled={busy || !asset?.can_process} onClick={p.onReprocess} data-testid="reprocess-button">Reprocess</button>
          </div>
        )}
        <button type="button" className="btn primary big" disabled={busy || p.selectedReady === 0} onClick={p.onEnhanceSelected} data-testid="enhance-selected">
          Enhance selected
          <small>{p.selectedReady} selected</small>
        </button>
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
