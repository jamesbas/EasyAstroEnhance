// Typed models of the EasyAstroEnhance local API (/api/v1). Mirrors backend/app/models/api.py and processing/recipe.py.

export type Strength = 'gentle' | 'balanced' | 'strong';
export type BackgroundMethod = 'constant' | 'planar';

// Main sliders (0 switches a finishing stage off). Mirrors LookRecipe.
export interface LookRecipe {
  background: number;
  stretch: number;
  contrast: number;
  color: number;
  detail: number;
  noise: number;
  protect_cores: boolean;
}

// Automatic stages; each measures the image and runs or is skipped with a reason. Mirrors AutoRecipe.
export interface AutoRecipe {
  neutralize: boolean;
  gradient: boolean;
  white_balance: boolean;
  green_removal: boolean;
  star_stretch: boolean;
}

export interface ToneRecipe {
  enabled: boolean;
  brightness_ev: number;
  shadows: number;
  highlights: number;
  black_point: number;
}

export interface BackgroundRecipe {
  enabled: boolean;
  method: BackgroundMethod;
  strength: Strength;
}

export interface AdvancedRecipe {
  stretch_log_d: number | null;
  stretch_b: number | null;
  highlight_convergence: number | null;
  star_stretch_amount: number | null;
  hdr_amount: number | null;
  white_balance_limit: number | null;
  gradient_degree: number | null;
  scnr_amount: number | null;
  denoise_scales: number | null;
  detail_scale_px: number | null;
  tone_gain: number | null;
  background_strength: number | null;
  deconvolution: boolean;
  deconvolution_iterations: number | null;
}

// Optional learned (AI) tools, all off by default. Mirrors AIRecipe.
export interface AIRecipe {
  background: boolean;
  denoise: boolean;
  stars: boolean;
  star_brightness: number;
}
export type AITool = Exclude<keyof AIRecipe, 'star_brightness'>;

export interface ObjectColorRecipe {
  reds: number;
  greens: number;
  blues: number;
}

export interface FocusStretchRecipe {
  enabled: boolean;
  strength: number;
  focus: number;
  protect_shadows: boolean;
  protect_highlights: boolean;
}

export type MixMode = 'RGB' | 'LRGB' | 'HOO' | 'SHO' | 'DUAL-SHO' | 'HA-RGB';
export interface ColorMixBody {
  mode: MixMode;
  asset_ids: string[];
  gains: number[];
  strength: number;
  prealigned: boolean;
}

export interface Recipe {
  schema_version: number;
  preset: string;
  look: LookRecipe;
  auto: AutoRecipe;
  tone: ToneRecipe;
  background: BackgroundRecipe;
  protect_regions: boolean;
  advanced: AdvancedRecipe;
  ai: AIRecipe;
  object_color: ObjectColorRecipe;
  focus_stretch: FocusStretchRecipe;
  catalog_sha256: string | null;
  hubble_strength: number;
}

export interface Rect {
  x: number;
  y: number;
  w: number;
  h: number;
}

// ---- errors / session
export interface ApiErrorBody {
  code: string;
  message: string;
  detail?: unknown;
}

export interface Session {
  token: string;
  version: string;
  recipe_schema: number;
  stack_version: string;
  limits: { max_files: number; max_file_mib: number; max_megapixels: number };
}

// ---- assets
export type AssetStatus = 'inspecting' | 'needs_input' | 'ready' | 'failed';
export type StatusLabel =
  | 'Inspecting'
  | 'Ready'
  | 'Needs input'
  | 'Queued'
  | 'Processing'
  | 'Complete'
  | 'Complete with notes'
  | 'Failed'
  | 'Cancelled'
  | 'Interrupted';
export type InputState = 'linear' | 'rendered' | 'unsure';

export interface QuestionOption {
  value: string | number;
  label: string;
  help?: string;
}

export interface Question {
  id: 'hdu' | 'layout' | 'state';
  kind: 'hdu' | 'layout' | 'state';
  title: string;
  help?: string;
  options: QuestionOption[];
}

export interface HduCandidate {
  index: number;
  name: string;
  shape: number[];
  kind: string;
  thumb_url: string | null;
}

export interface Baseline {
  label: string | null;
  preview_only: boolean | null;
  frame: Record<string, unknown> | null;
  histogram: number[] | null;
  invalid_pixels: number | null;
  domain: string | null;
  orientation_transform: string | null;
  notes: string[];
  has_sensitive_metadata: boolean;
}

export interface Interpretation {
  hdu?: number;
  layout?: string;
  state?: InputState;
  dualband_confirmed?: boolean;
}

export interface ResolvedIntake {
  hdu: number | null;
  layout: string | null;
  state: InputState | null;
}

export interface BackgroundIssue {
  level: 'error' | 'warning';
  code: string;
  message: string;
  sample: number | null;
}

export interface BackgroundConfirmation {
  method: BackgroundMethod;
  samples: Rect[];
  confirmed: boolean;
  confirmed_at: string;
  samples_hash: string;
  model_hash: string;
  warnings: BackgroundIssue[];
  residuals: Record<string, unknown> | null;
}

export interface Asset {
  id: string;
  filename: string;
  format: 'jpeg' | 'tiff' | 'fits' | null;
  size_bytes: number;
  sha256: string | null;
  status: AssetStatus;
  status_label: StatusLabel;
  error: ApiErrorBody | null;
  width: number | null;
  height: number | null;
  channel_layout: string | null;
  bit_depth: number | null;
  questions: Question[];
  interpretation: Interpretation;
  hubble_input: 'dualband' | 'unknown' | 'broadband' | 'unsupported';
  resolved: ResolvedIntake | null;
  can_process: boolean;
  intake_message: string | null;
  candidates: HduCandidate[];
  baseline: Baseline | null;
  regions: Rect[];
  background: BackgroundConfirmation | null;
  thumb_url: string | null;
  preview_url: string | null;
  latest_item: JobItem | null;
  latest_run: Run | null;
  run_count: number;
  stack: AssetStackInfo | null;
  created_at: string;
}

export interface AssetList {
  assets: Asset[];
}

export interface UploadResult {
  assets: Asset[];
}

// ---- runs / jobs
export type RunState = 'queued' | 'running' | 'succeeded' | 'succeeded_with_notes' | 'failed' | 'cancelled' | 'interrupted';
export type ExportKind = 'png' | 'tiff' | 'jpeg' | 'comparison' | 'fits' | 'linear-tiff' | 'report' | 'summary';

export interface ExportEntry {
  kind: ExportKind;
  filename: string;
  label: string;
  bytes: number;
  sha256: string;
  url: string;
}

export interface OperationNote {
  name: string;
  status: string;
  reason?: string | null;
}

export interface Run {
  id: string;
  asset_id: string;
  created_at: string;
  state: RunState;
  serial: number;
  recipe: Recipe;
  recipe_hash: string;
  summary: string | null;
  operations: OperationNote[];
  run_name: string | null;
  seconds: number | null;
  needs_review: boolean;
  backend_label: string | null;
  exports: ExportEntry[];
  preview_url: string;
  filename?: string | null;
}

export interface RunDetail extends Run {
  applied: Record<string, unknown> | null;
  has_fixed_mapping: boolean;
}

export interface RunList {
  runs: Run[];
}

export interface ItemNote {
  kind: string;
  operation?: string;
  message: string;
}

export interface JobItem {
  id: string;
  asset_id: string;
  filename: string | null;
  state: RunState;
  status_label: StatusLabel;
  stage: string | null;
  backend_label: string | null;
  notes: ItemNote[];
  run_id: string | null;
  error: ApiErrorBody | null;
}

export interface Job {
  id: string;
  state: RunState;
  status_label: StatusLabel;
  created_at: string;
  items: JobItem[];
  processing_label: string | null;
  recipe: Recipe;
}

export interface SkippedAsset {
  asset_id: string;
  code: string;
  message: string;
  filename?: string;
}

export interface JobCreated extends Job {
  idempotent_replay: boolean;
  skipped: SkippedAsset[];
}

export interface JobList {
  jobs: Job[];
}

// ---- stacking
export type StackMode = 'auto' | 'subs' | 'sessions';
export type StackGrading = 'off' | 'lenient' | 'standard' | 'strict';

export interface StackFolders {
  folder: string;
  mode?: StackMode;
  darks?: string | null;
  flats?: string | null;
  bias?: string | null;
  darkflats?: string | null;
}

export interface StackCreateBody extends StackFolders {
  request_key: string;
  scale: 1 | 2;
  grading: StackGrading;
  rejection: 'sigma' | 'none';
  auto_enhance: boolean;
  recipe: Recipe | null;
  preset_id: string | null;
}

export interface FrameSummary {
  count: number;
  layout?: 'cfa' | 'mono' | 'rgb';
  width?: number;
  height?: number;
  bayer?: string | null;
  filter?: string | null;
  instrument?: string | null;
  exposures?: number[];
  total_exposure_s?: number | null;
  sub_frames?: number;
  nights?: string[];
}

export interface NamedReason {
  name: string;
  reason: string;
}

export interface StackPlan {
  name: string;
  mode: 'subs' | 'sessions';
  lights: FrameSummary;
  excluded: NamedReason[];
  skipped: NamedReason[];
  calibration: { dark: number; flat: number; bias: number; darkflat: number } | null;
  warnings: string[];
  can_stack: boolean;
  drizzle_available: boolean;
  output?: { native: [number, number]; drizzle2x: [number, number] | null };
}

export interface StackReport {
  mode: 'subs' | 'sessions';
  frames_used: number;
  frames_total: number;
  rejected_frames: NamedReason[];
  seconds: number;
  device?: string;
  output?: { width: number; height: number };
  [key: string]: unknown;
}

export interface Stack {
  id: string;
  name: string;
  state: RunState;
  status_label: string;
  created_at: string;
  finished_at: string | null;
  stage: string | null;
  progress: number | null;
  request: StackFolders & { scale: number; grading: StackGrading };
  auto_enhance: boolean;
  job_id: string | null;
  asset_id: string | null;
  asset_status: string | null;
  report: StackReport | null;
  error: ApiErrorBody | null;
}

export interface StackList {
  stacks: Stack[];
}

export interface AssetStackInfo {
  id: string;
  name: string;
  mode: 'subs' | 'sessions';
  frames_used: number;
  frames_total: number;
  rejected_frames: NamedReason[];
  total_exposure_s: number | null;
  drizzle: boolean;
  seconds: number;
  calibration: { darks: number; flats: number; bias: number; dark_flats: number };
  defective_pixels: number | null;
}

export interface JobCreateBody {
  request_key: string;
  asset_ids: string[];
  recipe: Recipe;
  preset_id?: string | null;
  force?: boolean;
}

// ---- presets
export interface Preset {
  id: string;
  name: string;
  builtin: boolean;
  recipe: Recipe | null;
  compatible: boolean;
  schema_version: number;
  engine_version: string;
  updated_at: string;
  migration_note: string | null;
}

export interface PresetList {
  presets: Preset[];
}

// ---- background / star mask
export interface BackgroundSuggestion {
  patches: Rect[];
  note: string;
}

export interface BackgroundModel {
  method: BackgroundMethod;
  ok: boolean;
  model_hash: string;
  channel_offsets: number[];
  reference_level: number;
  plane: Record<string, number> | null;
  samples: Record<string, unknown>[];
  residuals: Record<string, unknown>;
  issues: BackgroundIssue[];
}

export interface BackgroundPreview {
  model: BackgroundModel;
  samples_hash: string;
  preview_file?: string;
  preview_url?: string;
  plane_grid?: number[][];
}

export interface BackgroundBody {
  method: BackgroundMethod;
  samples: Rect[];
  strength: number;
  confirmed?: boolean;
}

export interface StarMaskResult {
  reliable: boolean;
  file: string | null;
  overlay_url: string | null;
  stats: Record<string, unknown>;
  settings?: Record<string, unknown> | null;
}

// ---- compute / settings
export type DevicePreference = 'auto' | 'gpu' | 'cpu';

export interface ProbeInfo {
  ok: boolean;
  status: string;
  note: string | null;
  cupy_version?: string;
  cuda_runtime_version?: number;
  cuda_driver_version?: number;
  device_count?: number;
  device_name?: string;
  compute_capability?: string;
  free_memory_bytes?: number;
  total_memory_bytes?: number;
  probe_max_abs_error?: number;
  probe_seconds?: number;
}

export interface StagePolicy {
  stage: string;
  gpu_eligible: boolean;
  backend?: string;
}

export interface ComputeInfo {
  preference: DevicePreference;
  gpu_memory_fraction: number;
  ram_fraction: number;
  probe: ProbeInfo | null;
  gpu_usable: boolean;
  resolved_label: string;
  note: string | null;
  stage_policy: StagePolicy[];
  devices: {
    name?: string;
    compute_capability?: string;
    free_memory_bytes?: number;
    total_memory_bytes?: number;
  }[];
  gpu_threshold_pixels: number;
}

export interface ComputePatchBody {
  device?: DevicePreference;
  gpu_memory_fraction?: number;
  ram_fraction?: number;
}

export interface AppSettings {
  compute: ComputeInfo;
  strip_location: boolean;
  limits: { max_files: number; max_file_mib: number; max_megapixels: number };
  data_dir: string;
}

export interface HistorySummary {
  assets: number;
  runs: number;
  bytes: { uploaded_originals_copies: number; results: number; zip_exports: number };
  will_remove: string;
  location: string;
}

// ---- exports
export type BatchIncludeKind = 'tiff' | 'jpeg' | 'comparison' | 'fits' | 'linear-tiff';

export interface BatchExportStarted {
  id: string;
  state: 'building';
}

export interface ExportStatus {
  id: string;
  state: 'building' | 'ready' | 'failed';
  detail: { done?: number; total?: number; bytes?: number; error?: ApiErrorBody } | null;
  download_url: string | null;
}

// ---- AI models
export type AIModelState = 'installed' | 'missing' | 'downloading' | 'error';

export interface AIModelInfo {
  id: string;
  tool: AITool;
  title: string;
  file: string;
  version: string;
  url: string;
  sha256: string;
  size: number;
  license: string;
  license_url: string;
  attribution: string;
  source: string;
  state: AIModelState;
  received: number;
  error: string | null;
  local_graxpert_copy: boolean;
}

export interface AIToolInfo {
  models: string[];
  ready: boolean;
  state: AIModelState;
  download_bytes: number;
}

export interface AIOverview {
  models: AIModelInfo[];
  tools: Record<AITool, AIToolInfo>;
  runtime_available: boolean;
  provider_label: string | null;
  models_dir: string;
  note: string;
}
