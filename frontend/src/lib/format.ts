import type { Asset } from '../api/types';

export function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  const units = ['KB', 'MB', 'GB', 'TB'];
  let v = n / 1024;
  let i = 0;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i++;
  }
  return `${v >= 100 ? v.toFixed(0) : v.toFixed(1)} ${units[i]}`;
}

export function formatDims(a: Asset): string | null {
  return a.width && a.height ? `${a.width.toLocaleString()} × ${a.height.toLocaleString()}` : null;
}

export function fileTypeLabel(a: Asset): string {
  switch (a.format) {
    case 'jpeg': return 'JPEG';
    case 'tiff': return 'TIFF';
    case 'fits': return 'FITS';
    default: return '—';
  }
}

export function colorLabel(a: Asset): string | null {
  if (a.channel_layout === 'mono') return 'Monochrome';
  if (a.channel_layout === 'rgb') return 'RGB';
  return null;
}

export function formatTime(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

export function plural(n: number, one: string, many: string = `${one}s`): string {
  return `${n} ${n === 1 ? one : many}`;
}

export function clamp(v: number, lo: number, hi: number): number {
  return Math.min(hi, Math.max(lo, v));
}
