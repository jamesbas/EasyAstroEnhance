import type { Asset, Recipe, Strength, ToneRecipe } from '../api/types';

export const STRENGTHS: Strength[] = ['gentle', 'balanced', 'strong'];
export const STRENGTH_LABEL: Record<Strength, string> = { gentle: 'Gentle', balanced: 'Balanced', strong: 'Strong' };

// Background strength behind the Gentle/Balanced/Strong buttons (backend STRENGTH_TABLES["background"]).
export const BACKGROUND_STRENGTH: Record<Strength, number> = { gentle: 0.5, balanced: 0.75, strong: 1.0 };

export const TONE_NEUTRAL: Pick<ToneRecipe, 'brightness_ev' | 'shadows' | 'highlights' | 'black_point'> = {
  brightness_ev: 0,
  shadows: 0,
  highlights: 0,
  black_point: 0,
};

export interface NumericBound {
  key: keyof Recipe['advanced'];
  label: string;
  min: number;
  max: number;
  step: number;
  hint: string;
}

// Bounds mirror AdvancedRecipe in backend/app/processing/recipe.py.
export const ADVANCED_BOUNDS: NumericBound[] = [
  { key: 'denoise_amount', label: 'Noise reduction amount', min: 0, max: 0.8, step: 0.01, hint: 'Replaces the Reduce noise strength button' },
  { key: 'tone_gain', label: 'Tone gain (display images)', min: 1, max: 2.5, step: 0.01, hint: 'Midtone gain for already-processed images' },
  { key: 'asinh_k', label: 'Stretch strength (linear images)', min: 2, max: 200, step: 1, hint: 'asinh stretch factor for linear stacks' },
  { key: 'saturation', label: 'Saturation', min: 1, max: 1.4, step: 0.01, hint: 'Existing-color boost' },
  { key: 'star_protection_amount', label: 'Star protection amount', min: 0, max: 1, step: 0.01, hint: 'Limits extra brightening of stars' },
  { key: 'local_contrast_amount', label: 'Local contrast amount', min: 0, max: 1.2, step: 0.01, hint: 'Medium-scale contrast' },
  { key: 'local_contrast_scale_px', label: 'Local contrast scale (px)', min: 8, max: 64, step: 1, hint: 'Feature size in pixels' },
  { key: 'background_strength', label: 'Background correction strength', min: 0, max: 1, step: 0.01, hint: 'Replaces the Balance background strength button' },
];

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
