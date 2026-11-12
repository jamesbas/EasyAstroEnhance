import type { BackgroundPreview, Rect } from '../api/types';

export type ViewerMode = 'divider' | 'side' | 'blink';
export type ViewerTool = 'none' | 'samples' | 'label';
export type OverlayId = 'clipping' | 'stars';

export interface BgSample {
  rect: Rect;
  excluded: boolean;
}

export interface BgDraft {
  samples: BgSample[];
  suggestions: Rect[];
  suggestNote: string | null;
  check: BackgroundPreview | null;
  checkKey: string | null;
}

export interface Mark {
  rect: Rect;
  kind: 'sample' | 'excluded' | 'suggested' | 'region';
  label?: string;
}

export interface Toast {
  id: number;
  kind: 'error' | 'info' | 'success';
  text: string;
}

export const STATUS_ACTIVE: readonly string[] = ['Inspecting', 'Queued', 'Processing'];
