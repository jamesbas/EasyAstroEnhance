import type {
  AppSettings, Asset, AssetList, BackgroundBody, BackgroundPreview, BackgroundSuggestion, BatchExportStarted,
  BatchIncludeKind, ComputeInfo, ComputePatchBody, ExportStatus, HistorySummary, Interpretation, Job, JobCreateBody,
  JobCreated, JobList, Preset, PresetList, Recipe, Rect, RunDetail, RunList, Session, StarMaskResult, UploadResult,
  ApiErrorBody, Stack, StackCreateBody, StackFolders, StackList, StackPlan, AIOverview,
} from './types';

export const API = '/api/v1';
const TOKEN_HEADER = 'X-EAE-Token';

export class ApiError extends Error {
  readonly code: string;
  readonly status: number;
  readonly detail: unknown;

  constructor(status: number, body: ApiErrorBody) {
    super(body.message);
    this.name = 'ApiError';
    this.status = status;
    this.code = body.code;
    this.detail = body.detail;
  }
}

const NETWORK_MESSAGE = 'Cannot reach EasyAstroEnhance. Check that the app is still running, then try again.';

// The session token lives only in memory: never in URLs or storage.
let tokenPromise: Promise<string> | null = null;

async function loadToken(): Promise<string> {
  const session = await rawRequest<Session>('GET', '/session');
  return session.token;
}

function getToken(refresh = false): Promise<string> {
  if (refresh || !tokenPromise) {
    tokenPromise = loadToken().catch((err: unknown) => {
      tokenPromise = null;
      throw err;
    });
  }
  return tokenPromise;
}

async function parseError(res: Response): Promise<ApiError> {
  let body: ApiErrorBody | null = null;
  try {
    const json: unknown = await res.json();
    if (json && typeof json === 'object' && 'error' in json) {
      const e = (json as { error: Partial<ApiErrorBody> }).error;
      if (e && typeof e.message === 'string') body = { code: e.code ?? 'ERROR', message: e.message, detail: e.detail };
    }
  } catch {
    // not JSON (for example a proxy error page); fall through to a generic message
  }
  if (!body) {
    body = {
      code: 'HTTP_ERROR',
      message: res.status >= 500 ? 'The app ran into a problem. Please try again.' : `The request was not accepted (HTTP ${res.status}).`,
    };
  }
  return new ApiError(res.status, body);
}

async function rawRequest<T>(method: string, path: string, body?: unknown, token?: string): Promise<T> {
  const headers: Record<string, string> = {};
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  if (token) headers[TOKEN_HEADER] = token;
  let res: Response;
  try {
    res = await fetch(`${API}${path}`, { method, headers, body: body === undefined ? undefined : JSON.stringify(body), cache: 'no-store' });
  } catch {
    throw new ApiError(0, { code: 'NETWORK', message: NETWORK_MESSAGE });
  }
  if (!res.ok) throw await parseError(res);
  return (await res.json()) as T;
}

const MUTATING = new Set(['POST', 'PUT', 'PATCH', 'DELETE']);

async function authenticated<T>(send: (token: string) => Promise<T>): Promise<T> {
  try {
    return await send(await getToken());
  } catch (err) {
    if (err instanceof ApiError && err.status === 403 && err.code === 'TOKEN_INVALID') {
      return send(await getToken(true));
    }
    throw err;
  }
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  return MUTATING.has(method)
    ? authenticated((token) => rawRequest<T>(method, path, body, token))
    : rawRequest<T>(method, path);
}

async function postFileOrPreview(path: string, body: FormData | string, signal?: AbortSignal): Promise<Response> {
  return authenticated(async (token) => {
    const headers: Record<string, string> = { [TOKEN_HEADER]: token };
    if (typeof body === 'string') headers['Content-Type'] = 'application/json';
    const res = await fetch(`${API}${path}`, { method: 'POST', headers, body, signal, cache: 'no-store' });
    if (!res.ok) throw await parseError(res);
    return res;
  });
}

function xhrUpload(files: File[], token: string, onProgress: (fraction: number) => void): Promise<UploadResult> {
  return new Promise((resolve, reject) => {
    const form = new FormData();
    for (const f of files) form.append('files', f, f.name);
    const xhr = new XMLHttpRequest();
    xhr.open('POST', `${API}/assets`);
    xhr.setRequestHeader(TOKEN_HEADER, token);
    xhr.responseType = 'json';
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable && e.total > 0) onProgress(e.loaded / e.total);
    };
    xhr.onerror = () => reject(new ApiError(0, { code: 'NETWORK', message: NETWORK_MESSAGE }));
    xhr.onload = () => {
      const data: unknown = xhr.response;
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(data as UploadResult);
        return;
      }
      const e = data && typeof data === 'object' && 'error' in data ? (data as { error: Partial<ApiErrorBody> }).error : null;
      reject(new ApiError(xhr.status, {
        code: e?.code ?? 'UPLOAD_FAILED',
        message: e?.message ?? 'The files could not be uploaded.',
        detail: e?.detail,
      }));
    };
    xhr.send(form);
  });
}

export async function uploadAssets(files: File[], onProgress: (fraction: number) => void): Promise<UploadResult> {
  try {
    return await xhrUpload(files, await getToken(), onProgress);
  } catch (err) {
    if (err instanceof ApiError && err.status === 403 && err.code === 'TOKEN_INVALID') {
      return xhrUpload(files, await getToken(true), onProgress);
    }
    throw err;
  }
}

export const api = {
  session: () => rawRequest<Session>('GET', '/session'),
  // assets
  listAssets: () => request<AssetList>('GET', '/assets'),
  getAsset: (id: string) => request<Asset>('GET', `/assets/${id}`),
  deleteAsset: (id: string) => request<{ deleted: string; note: string }>('DELETE', `/assets/${id}`),
  setInterpretation: (id: string, body: Interpretation) => request<Asset>('PATCH', `/assets/${id}/interpretation`, body),
  setRegions: (id: string, regions: Rect[]) => request<Asset>('PUT', `/assets/${id}/regions`, { regions }),
  importCatalog: async (file: File): Promise<{ sha256: string; name: string; stars: number }> => {
    const form = new FormData();
    form.append('file', file);
    return (await postFileOrPreview('/assets/color-catalog', form)).json();
  },
  colorMix: (body: import('./types').ColorMixBody) => request<Asset>('POST', '/assets/color-mix', body),
  objectColorPreview: async (id: string, color: import('./types').ObjectColorRecipe, mask: boolean, protect: boolean,
    signal: AbortSignal, hubbleStrength = 0) =>
    (await postFileOrPreview(`/assets/${id}/object-color-preview?mask=${mask}&protect_regions=${protect}&hubble_strength=${hubbleStrength}`,
      JSON.stringify(color), signal)).blob(),
  suggestBackground: (id: string) => request<BackgroundSuggestion>('GET', `/assets/${id}/background/suggest`),
  previewBackground: (id: string, body: BackgroundBody) => request<BackgroundPreview>('POST', `/assets/${id}/background/preview`, body),
  confirmBackground: (id: string, body: BackgroundBody) => request<Asset>('PUT', `/assets/${id}/background`, body),
  starMask: (id: string) => request<StarMaskResult>('GET', `/assets/${id}/star-mask`),
  // jobs
  createJob: (body: JobCreateBody) => request<JobCreated>('POST', '/jobs', body),
  listJobs: (active: boolean) => request<JobList>('GET', `/jobs${active ? '?active=true' : ''}`),
  cancelJob: (id: string) => request<Job>('POST', `/jobs/${id}/cancel`),
  retryJob: (id: string) => request<Job>('POST', `/jobs/${id}/retry`),
  // optional AI tools (fixed, verified model files)
  aiModels: () => request<AIOverview>('GET', '/ai/models'),
  downloadAI: (key: string) => request<AIOverview>('POST', `/ai/models/${key}/download`),
  cancelAI: (key: string) => request<AIOverview>('POST', `/ai/models/${key}/cancel`),
  deleteAI: (key: string) => request<AIOverview>('DELETE', `/ai/models/${key}`),
  // stacking (folders are read, never written)
  scanStack: (body: StackFolders) => request<StackPlan>('POST', '/stacks/scan', body),
  createStack: (body: StackCreateBody) => request<Stack>('POST', '/stacks', body),
  listStacks: (active: boolean) => request<StackList>('GET', `/stacks${active ? '?active=true' : ''}`),
  getStack: (id: string) => request<Stack>('GET', `/stacks/${id}`),
  cancelStack: (id: string) => request<Stack>('POST', `/stacks/${id}/cancel`),
  retryStack: (id: string) => request<Stack>('POST', `/stacks/${id}/retry`),
  // runs
  listRuns: (assetId: string) => request<RunList>('GET', `/runs?asset_id=${encodeURIComponent(assetId)}`),
  getRun: (id: string) => request<RunDetail>('GET', `/runs/${id}`),
  // presets
  listPresets: () => request<PresetList>('GET', '/presets'),
  createPreset: (name: string, recipe: Recipe) => request<Preset>('POST', '/presets', { name, recipe }),
  renamePreset: (id: string, name: string) => request<Preset>('PATCH', `/presets/${id}`, { name }),
  duplicatePreset: (id: string) => request<Preset>('POST', `/presets/${id}/duplicate`),
  deletePreset: (id: string) => request<{ deleted: string }>('DELETE', `/presets/${id}`),
  // settings / compute
  getCompute: () => request<ComputeInfo>('GET', '/compute'),
  probeCompute: () => request<ComputeInfo>('POST', '/compute/probe'),
  patchCompute: (body: ComputePatchBody) => request<ComputeInfo>('PATCH', '/settings/compute', body),
  getSettings: () => request<AppSettings>('GET', '/settings'),
  patchSettings: (body: { strip_location: boolean }) => request<AppSettings>('PATCH', '/settings', body),
  // exports / history
  startBatchExport: (runIds: string[], include: BatchIncludeKind[]) =>
    request<BatchExportStarted>('POST', '/exports/batch', { run_ids: runIds, include }),
  getExport: (id: string) => request<ExportStatus>('GET', `/exports/${id}`),
  historySummary: () => request<HistorySummary>('GET', '/history/summary'),
  clearHistory: () => request<{ cleared: boolean }>('DELETE', '/history', { confirm: true }),
};

export function readableError(err: unknown): string {
  if (err instanceof ApiError) return err.message;
  if (err instanceof Error && err.message) return err.message;
  return 'Something went wrong. Please try again.';
}

// ---- plain same-origin GET URLs (no token needed)
export function withRoi(url: string, roi: Rect, extra?: Record<string, string>): string {
  const q = new URLSearchParams({ x: String(roi.x), y: String(roi.y), w: String(roi.w), h: String(roi.h), ...extra });
  return `${url}${url.includes('?') ? '&' : '?'}${q.toString()}`;
}

export function withQuery(url: string, extra: Record<string, string>): string {
  return `${url}${url.includes('?') ? '&' : '?'}${new URLSearchParams(extra).toString()}`;
}

// Baseline images are regenerated when the intake answers change; the version keeps the browser cache honest.
export function assetImageUrl(asset: Asset, url: string): string {
  const i = asset.interpretation;
  return withQuery(url, { v: `${i.state ?? ''}-${i.hdu ?? ''}-${i.layout ?? ''}` });
}

export const clippingOverlayUrl = (runId: string): string => `${API}/runs/${runId}/overlay/clipping`;
export const fullMetadataFitsUrl = (runId: string): string => `${API}/runs/${runId}/exports/fits-full`;
