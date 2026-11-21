import type { Recipe } from '../api/types';

// Steps of a finished result that the user can turn off ("remove"), mapped to the setting that turns each one off.
// Names are the processing report's operation names (backend/app/processing/pipeline.py). Steps without a setting of
// their own (the stretch, large-scale structure, Moon surface balance) are not listed: they cannot be removed alone.
export interface RemovableStep {
  label: string;
  /** where the setting lives, shown in the button's tooltip */
  setting: string;
  off: (r: Recipe) => void;
  /** true when the step is already off in these settings (nothing to remove) */
  isOff: (r: Recipe) => boolean;
}

export const REMOVABLE_STEPS: Record<string, RemovableStep> = {
  cosmetic: { label: 'Defective pixels repaired', setting: 'Advanced → Repair hot and cold pixels', off: (r) => { r.auto.cosmetic = false; }, isOff: (r) => !r.auto.cosmetic },
  banding: { label: 'Banding reduced', setting: 'Advanced → Repair row/column banding', off: (r) => { r.auto.banding = false; }, isOff: (r) => !r.auto.banding },
  background: { label: 'Background balanced', setting: 'Correct background from my sky samples', off: (r) => { r.background.enabled = false; }, isOff: (r) => !r.background.enabled },
  ai_background: { label: 'AI background removed', setting: 'AI tools → AI background extraction', off: (r) => { r.ai.background = false; }, isOff: (r) => !r.ai.background },
  gradient: { label: 'Gradient removed', setting: 'Advanced → Remove gradients', off: (r) => { r.auto.gradient = false; }, isOff: (r) => !r.auto.gradient },
  neutralize: { label: 'Background neutralized', setting: 'Advanced → Neutralize the background', off: (r) => { r.auto.neutralize = false; }, isOff: (r) => !r.auto.neutralize },
  white_balance: { label: 'Color balanced', setting: 'Advanced → Balance color from stars', off: (r) => { r.auto.white_balance = false; }, isOff: (r) => !r.auto.white_balance },
  catalog_color: {
    label: 'Star colors calibrated (catalog)', setting: 'Star colour → Accurate star colours / my own catalog',
    off: (r) => { r.catalog_builtin = false; r.catalog_sha256 = null; }, isOff: (r) => !r.catalog_builtin && !r.catalog_sha256,
  },
  deconvolution: { label: 'Sharpened (deconvolution)', setting: 'Advanced → Sharpen by deconvolution', off: (r) => { r.advanced.deconvolution = false; }, isOff: (r) => !r.advanced.deconvolution },
  ai_sharpen: { label: 'Sharpened (AI)', setting: 'AI tools → AI sharpening', off: (r) => { r.ai.sharpen = false; }, isOff: (r) => !r.ai.sharpen },
  denoise: { label: 'Noise reduced', setting: 'Look → Noise reduction (set to 0)', off: (r) => { r.look.noise = 0; }, isOff: (r) => r.look.noise === 0 },
  ai_denoise: { label: 'AI noise reduction', setting: 'AI tools → AI noise reduction', off: (r) => { r.ai.denoise = false; }, isOff: (r) => !r.ai.denoise },
  ai_stars: { label: 'Stars separated (AI)', setting: 'AI tools → AI star separation', off: (r) => { r.ai.stars = false; }, isOff: (r) => !r.ai.stars },
  star_brightness: { label: 'Stars dimmed', setting: 'AI tools → Star brightness (back to 100%)', off: (r) => { r.ai.star_brightness = 1; }, isOff: (r) => r.ai.star_brightness >= 1 },
  star_size: { label: 'Stars made smaller', setting: 'AI tools → Star size (back to 100%)', off: (r) => { r.ai.star_size = 1; }, isOff: (r) => r.ai.star_size >= 1 },
  star_stretch: { label: 'Stars kept small', setting: 'Advanced → Gentler stretch on stars', off: (r) => { r.auto.star_stretch = false; }, isOff: (r) => !r.auto.star_stretch },
  hdr: { label: 'Bright cores protected', setting: 'Look → Protect bright cores', off: (r) => { r.look.protect_cores = false; }, isOff: (r) => !r.look.protect_cores },
  green_removal: { label: 'Green cast removed', setting: 'Advanced → Remove green cast', off: (r) => { r.auto.green_removal = false; }, isOff: (r) => !r.auto.green_removal },
  contrast: { label: 'Contrast added', setting: 'Look → Contrast / Pop (set to 0)', off: (r) => { r.look.contrast = 0; }, isOff: (r) => r.look.contrast === 0 },
  detail: { label: 'Detail enhanced', setting: 'Look → Detail (set to 0)', off: (r) => { r.look.detail = 0; }, isOff: (r) => r.look.detail === 0 },
  fine_sharpen: { label: 'Fine detail sharpened', setting: 'Advanced → Fine sharpening (set to 0)', off: (r) => { r.advanced.fine_sharpen = 0; }, isOff: (r) => r.advanced.fine_sharpen === 0 },
  color: { label: 'Colors enhanced', setting: 'Look → Color (set to 0)', off: (r) => { r.look.color = 0; }, isOff: (r) => r.look.color === 0 },
  star_color: { label: 'Star colors enhanced', setting: 'Look → Star color (set to 0)', off: (r) => { r.look.star_color = 0; }, isOff: (r) => r.look.star_color === 0 },
  star_fringe: { label: 'Star color fringes reduced', setting: 'Advanced → Reduce star color fringes', off: (r) => { r.auto.halo_reduction = false; }, isOff: (r) => !r.auto.halo_reduction },
  object_color: {
    label: 'Object colors adjusted', setting: 'Object Color (reset)',
    off: (r) => { r.object_color = { reds: 0, greens: 0, blues: 0 }; }, isOff: (r) => !r.object_color.reds && !r.object_color.greens && !r.object_color.blues,
  },
  hubble_style: { label: 'Hubble-style palette', setting: 'Enhance Hubble-style (normal Enhance)', off: (r) => { r.hubble_strength = 0; }, isOff: (r) => r.hubble_strength === 0 },
  focus_stretch: { label: 'Manual focus stretch', setting: 'Stretch method → Automatic', off: (r) => { r.focus_stretch.enabled = false; }, isOff: (r) => !r.focus_stretch.enabled },
  protect_regions: { label: 'Label areas protected', setting: 'Preserve labels', off: (r) => { r.protect_regions = false; }, isOff: (r) => !r.protect_regions },
};

/** The steps a result applied that can be removed, in the order the result ran them. */
export function removableSteps(operations: { name: string; status: string }[]): string[] {
  return operations.filter((o) => (o.status === 'applied' || o.status === 'reduced') && o.name in REMOVABLE_STEPS).map((o) => o.name);
}
