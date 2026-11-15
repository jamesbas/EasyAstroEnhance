import type { AdvancedRecipe, Asset, AutoRecipe, LookRecipe, Recipe, Strength, ToneRecipe } from '../api/types';

export const STRENGTHS: Strength[] = ['gentle', 'balanced', 'strong'];
export const STRENGTH_LABEL: Record<Strength, string> = { gentle: 'Gentle', balanced: 'Balanced', strong: 'Strong' };

// Background strength behind the Gentle/Balanced/Strong buttons (backend BACKGROUND_STRENGTH).
export const BACKGROUND_STRENGTH: Record<Strength, number> = { gentle: 0.5, balanced: 0.75, strong: 1.0 };

export const TONE_NEUTRAL: Pick<ToneRecipe, 'brightness_ev' | 'shadows' | 'highlights' | 'black_point'> = {
  brightness_ev: 0,
  shadows: 0,
  highlights: 0,
  black_point: 0,
};

export type LookKey = Exclude<keyof LookRecipe, 'protect_cores'>;

export interface LookSliderSpec {
  key: LookKey;
  id: string;
  label: string;
  min: number;
  max: number;
  step: number;
  left: string;
  right: string;
  hint: string;
  colorOnly?: boolean;
}

// Bounds mirror LookRecipe in backend/app/processing/recipe.py. Every slider changes a documented parameter.
export const LOOK_SLIDERS: LookSliderSpec[] = [
  { key: 'background', id: 'background-level', label: 'Background', min: 0.04, max: 0.25, step: 0.01, left: 'Darker', right: 'Brighter', hint: 'Brightness of the empty sky on screen' },
  { key: 'stretch', id: 'stretch', label: 'Stretch', min: -1, max: 1, step: 0.05, left: 'Gentle', right: 'Deep', hint: 'How strongly faint signal is lifted, relative to the automatic choice' },
  { key: 'contrast', id: 'contrast', label: 'Contrast / Pop', min: 0, max: 1, step: 0.05, left: 'Off', right: 'Strong', hint: 'A finishing S-curve anchored at the sky' },
  { key: 'color', id: 'color', label: 'Color', min: 0, max: 1, step: 0.05, left: 'Off', right: 'Strong', hint: 'Saturation of the color already in the image (not in the dark sky)', colorOnly: true },
  { key: 'detail', id: 'detail', label: 'Detail', min: 0, max: 1, step: 0.05, left: 'Off', right: 'Strong', hint: 'Multiscale local contrast on real structure, never on noise or stars' },
  { key: 'noise', id: 'noise', label: 'Noise reduction', min: 0, max: 1, step: 0.05, left: 'Off', right: 'Strong', hint: 'Relative to the noise measured in this image' },
];

export interface AutoStageSpec {
  key: keyof AutoRecipe;
  label: string;
  hint: string;
}

export const AUTO_STAGES: AutoStageSpec[] = [
  { key: 'neutralize', label: 'Neutralize the background', hint: 'Makes the empty sky gray (removes the color cast)' },
  { key: 'gradient', label: 'Remove gradients', hint: 'Light pollution / moonlight glow, linear stacks only; skipped when the target fills the frame' },
  { key: 'white_balance', label: 'Balance color from stars', hint: 'Bounded gains so the average field star is white (not photometric calibration)' },
  { key: 'green_removal', label: 'Remove green cast', hint: 'Only when green remains after balancing' },
  { key: 'star_stretch', label: 'Keep stars small', hint: 'A gentler stretch inside confident star masks (never removes or shrinks stars)' },
];

export interface NumericBound {
  key: Exclude<keyof AdvancedRecipe, 'deconvolution'>;
  label: string;
  min: number;
  max: number;
  step: number;
  hint: string;
}

// Bounds mirror AdvancedRecipe in backend/app/processing/recipe.py. Empty = chosen automatically.
export const ADVANCED_BOUNDS: NumericBound[] = [
  { key: 'stretch_log_d', label: 'Stretch factor log10(D)', min: 0, max: 5, step: 0.05, hint: 'Fixes the hyperbolic stretch factor instead of solving it' },
  { key: 'stretch_b', label: 'Local intensity b', min: 0, max: 15, step: 0.5, hint: 'Higher keeps the stretch more linear at low levels (default 6)' },
  { key: 'highlight_convergence', label: 'Highlight convergence', min: 1, max: 8, step: 0.1, hint: 'How quickly bright cores fade to white (default 3.5)' },
  { key: 'star_stretch_amount', label: 'Star softening amount', min: 0, max: 1, step: 0.05, hint: 'Blend of the gentler star stretch (default 0.5)' },
  { key: 'hdr_amount', label: 'Core compression amount', min: 0, max: 1, step: 0.05, hint: 'Used when a bright extended core is found (default 0.5)' },
  { key: 'white_balance_limit', label: 'White balance limit', min: 1, max: 1.5, step: 0.01, hint: 'Largest allowed channel gain (default 1.25)' },
  { key: 'gradient_degree', label: 'Gradient model degree', min: 1, max: 3, step: 1, hint: '1 = plane, 2 = gentle curvature (default), 3 = more flexible' },
  { key: 'scnr_amount', label: 'Green removal amount', min: 0, max: 1, step: 0.05, hint: 'Used when green remains (default 1)' },
  { key: 'denoise_scales', label: 'Noise reduction scales', min: 2, max: 6, step: 1, hint: 'Wavelet layers for luminance (default 4; chroma uses one more)' },
  { key: 'detail_scale_px', label: 'Detail scale (px)', min: 4, max: 64, step: 1, hint: 'Largest structure size boosted by Detail (default 16)' },
  { key: 'tone_gain', label: 'Midtone gain (processed images)', min: 1, max: 2.5, step: 0.01, hint: 'Rational midtone gain for already-processed images' },
  { key: 'background_strength', label: 'Manual background strength', min: 0, max: 1, step: 0.01, hint: 'Replaces the Balance background strength button' },
  { key: 'deconvolution_iterations', label: 'Deconvolution iterations', min: 1, max: 50, step: 1, hint: 'Used only when deconvolution is switched on (default 10)' },
];

export const PRESET_DESCRIPTIONS: Record<string, string> = {
  natural: 'Balanced, faithful result: neutral sky, protected cores, gentle color and contrast.',
  vivid: 'Darker sky, more pop, color and detail — the "make it pop" look.',
  'faint-detail': 'Deeper stretch and stronger noise reduction for dim nebulae and galaxy outskirts.',
  'bright-core': 'Stronger core compression for high-dynamic-range targets such as M42 or M31.',
  'star-field': 'Gentle stretch that keeps stars small and colorful for clusters and star fields.',
  'seestar-match': 'Close to the Seestar app look, for side-by-side comparison.',
};

export function cloneRecipe(r: Recipe): Recipe {
  return JSON.parse(JSON.stringify(r)) as Recipe;
}

function sortKeys(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(sortKeys);
  if (value && typeof value === 'object') {
    const out: Record<string, unknown> = {};
    for (const k of Object.keys(value).sort()) out[k] = sortKeys((value as Record<string, unknown>)[k]);
    return out;
  }
  return value;
}

// The preset label is bookkeeping; two recipes with identical settings are the same intent.
export function normalizeRecipe(r: Recipe): string {
  const { preset: _preset, ...rest } = r;
  return JSON.stringify(sortKeys(rest));
}

export function recipesDiffer(a: Recipe, b: Recipe): boolean {
  return normalizeRecipe(a) !== normalizeRecipe(b);
}

export function toneIsNeutral(t: ToneRecipe): boolean {
  return t.brightness_ev === 0 && t.shadows === 0 && t.highlights === 0 && t.black_point === 0;
}

// Fraction (0..1) of pixels strictly below `level` (0..1) using a 256-bin luminance histogram, interpolating within the bin.
export function fractionBelow(histogram: number[], level: number): number {
  const total = histogram.reduce((s, v) => s + v, 0);
  if (total <= 0 || level <= 0) return 0;
  const pos = Math.min(level, 1) * histogram.length;
  const whole = Math.floor(pos);
  let below = 0;
  for (let i = 0; i < whole && i < histogram.length; i++) below += histogram[i];
  if (whole < histogram.length) below += histogram[whole] * (pos - whole);
  return below / total;
}

export function isMono(asset: Asset | null | undefined): boolean {
  return asset?.channel_layout === 'mono';
}

// Background balancing is "pending" when requested but not confirmed (for the requested model) on this asset.
export function backgroundPending(recipe: Recipe, asset: Asset): boolean {
  if (!recipe.background.enabled) return false;
  const bg = asset.background;
  return !bg || !bg.confirmed || bg.method !== recipe.background.method;
}
