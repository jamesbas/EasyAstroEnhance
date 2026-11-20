import { useEffect, useState } from 'react';
import { api } from '../api/client';
import type { AppSettings, ComputeInfo, DevicePreference, HistorySummary } from '../api/types';
import type { AIModels } from '../hooks/useAIModels';
import type { AppVersion } from '../hooks/useAppVersion';
import { useToasts } from '../hooks/useToasts';
import { formatBytes } from '../lib/format';
import { Modal } from './Modal';

interface SettingsDialogProps {
  onClose: () => void;
  onCompute: (c: ComputeInfo) => void;
  onHistoryCleared: () => void;
  busyJobs: boolean;
  version: AppVersion | null;
  aiModels: AIModels;
}

function AIModelsSection({ models }: { models: AIModels }) {
  const o = models.overview;
  return (
    <section className="settings-section" data-testid="ai-models-section">
      <h3>AI models</h3>
      {!o ? <p className="muted small">Loading…</p> : (
        <>
          <p className="muted small">{o.note} Runs on: {o.provider_label ?? 'unavailable'}. Folder: {o.models_dir}</p>
          <table className="ai-models">
            <tbody>
              {o.models.map((m) => (
                <tr key={m.id} data-testid={`ai-model-${m.id}`}>
                  <td><strong>{m.title}</strong> {m.version}<br /><span className="muted small">{m.attribution} · <a href={m.license_url} target="_blank" rel="noreferrer">{m.license}</a></span></td>
                  <td className="small">{formatBytes(m.size)}</td>
                  <td className="small">
                    {m.state === 'installed' && <>Installed <button type="button" className="btn tiny" onClick={() => void models.remove(m.id)}>Remove</button></>}
                    {m.state === 'downloading' && <>{Math.round((100 * m.received) / m.size)}% <button type="button" className="btn tiny" onClick={() => void models.cancel(m.id)}>Cancel</button></>}
                    {(m.state === 'missing' || m.state === 'error') && (
                      <>{m.state === 'error' && <span className="err-text">{m.error} </span>}
                        <button type="button" className="btn tiny" onClick={() => void models.download(m.id)}>{m.local_graxpert_copy ? 'Copy from GraXpert' : 'Download'}</button></>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </section>
  );
}

function gib(n?: number): string {
  return n === undefined ? '—' : `${(n / 1024 ** 3).toFixed(1)} GB`;
}

function cudaVersion(v?: number): string {
  return v === undefined ? '—' : `${Math.floor(v / 1000)}.${Math.floor((v % 1000) / 10)}`;
}

function ProbeDetails({ compute }: { compute: ComputeInfo }) {
  const p = compute.probe;
  if (!p) return <p className="muted small">GPU not checked yet. Use Check GPU setup.</p>;
  return (
    <dl className="stats" data-testid="probe-details">
      <div><dt>Status</dt><dd>{p.status}{p.ok ? ' (usable)' : ''}</dd></div>
      {p.device_name && <div><dt>Device</dt><dd>{p.device_name}</dd></div>}
      {p.compute_capability && <div><dt>Compute capability</dt><dd>{p.compute_capability}</dd></div>}
      {p.cuda_runtime_version !== undefined && <div><dt>CUDA runtime</dt><dd>{cudaVersion(p.cuda_runtime_version)}</dd></div>}
      {p.cuda_driver_version !== undefined && <div><dt>CUDA driver</dt><dd>{cudaVersion(p.cuda_driver_version)}</dd></div>}
      {p.total_memory_bytes !== undefined && <div><dt>GPU memory</dt><dd>{gib(p.free_memory_bytes)} free of {gib(p.total_memory_bytes)}</dd></div>}
      {p.note && <div className="wide"><dt>Note</dt><dd>{p.note}</dd></div>}
    </dl>
  );
}

function FractionField({ id, label, hint, value, min, max, onCommit }: { id: string; label: string; hint: string; value: number; min: number; max: number; onCommit: (v: number) => void }) {
  const [local, setLocal] = useState(value);
  useEffect(() => setLocal(value), [value]);
  const commit = () => {
    const v = Math.round(local * 100) / 100;
    if (v !== Math.round(value * 100) / 100) onCommit(Math.min(max, Math.max(min, v)));
  };
  return (
    <div className="slider-row">
      <div className="slider-head">
        <label htmlFor={id}>{label}</label>
        <span className="num-readout">{Math.round(local * 100)}%</span>
      </div>
      <input id={id} type="range" min={min} max={max} step={0.05} value={local} onChange={(e) => setLocal(Number(e.target.value))} onPointerUp={commit} onKeyUp={commit} onBlur={commit} />
      <p className="slider-hint">{hint}</p>
    </div>
  );
}

function HistorySection({ busyJobs, onCleared }: { busyJobs: boolean; onCleared: () => void }) {
  const toasts = useToasts();
  const [summary, setSummary] = useState<HistorySummary | null>(null);
  const [busy, setBusy] = useState(false);

  const load = async () => {
    setBusy(true);
    try {
      setSummary(await api.historySummary());
    } catch (err) {
      toasts.error(err);
    } finally {
      setBusy(false);
    }
  };

  const clear = async () => {
    setBusy(true);
    try {
      await api.clearHistory();
      toasts.notify('success', 'Local history cleared.');
      setSummary(null);
      onCleared();
    } catch (err) {
      toasts.error(err);
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="settings-section">
      <h3>Local history</h3>
      {!summary ? (
        <>
          <p className="muted small">Removes the app&apos;s own copies of added images, previews, results and ZIPs. Your original files are never touched.</p>
          <button type="button" className="btn danger" disabled={busy} onClick={() => void load()} data-testid="clear-history">Clear local history</button>
        </>
      ) : (
        <div className="confirm-box" data-testid="history-confirm" role="alert">
          <p><strong>This will remove:</strong> {summary.assets} image{summary.assets === 1 ? '' : 's'} and {summary.runs} result{summary.runs === 1 ? '' : 's'}.</p>
          <ul className="small">
            <li>Copies of added images: {formatBytes(summary.bytes.uploaded_originals_copies)}</li>
            <li>Results and previews: {formatBytes(summary.bytes.results)}</li>
            <li>ZIP exports: {formatBytes(summary.bytes.zip_exports)}</li>
          </ul>
          <p className="muted small">{summary.will_remove}</p>
          <p className="muted small">Location: {summary.location}</p>
          {busyJobs && <p className="warn-text small">Cancel the running job first.</p>}
          <div className="row">
            <button type="button" className="btn" onClick={() => setSummary(null)}>Keep history</button>
            <button type="button" className="btn danger" disabled={busy || busyJobs} onClick={() => void clear()} data-testid="confirm-clear-history">Yes, clear history</button>
          </div>
        </div>
      )}
    </section>
  );
}

const KEEP_CHOICES = [0, 1, 3, 5, 10, 20];

function StorageSection({ keep, onKeep }: { keep: number; onKeep: (n: number) => void }) {
  const [usage, setUsage] = useState<HistorySummary | null>(null);
  useEffect(() => {
    api.historySummary().then(setUsage, () => setUsage(null));
  }, [keep]);
  return (
    <section className="settings-section" data-testid="storage-section">
      <h3>Storage</h3>
      {usage && (
        <p className="small" data-testid="disk-usage">
          Results and previews: {formatBytes(usage.bytes.results)} · Copies of added images: {formatBytes(usage.bytes.uploaded_originals_copies)} · ZIP exports: {formatBytes(usage.bytes.zip_exports)}
        </p>
      )}
      <div className="field">
        <label htmlFor="keep-runs">Results to keep per image</label>
        <select id="keep-runs" value={keep} data-testid="keep-runs" onChange={(e) => onKeep(Number(e.target.value))}>
          {KEEP_CHOICES.map((n) => <option key={n} value={n}>{n === 0 ? 'All results' : `Newest ${n}`}</option>)}
        </select>
      </div>
      <p className="muted small">When an image gets a new result, older results beyond this number are deleted from the app&apos;s data folder. The image&apos;s current result is always kept. Your original files are never touched.</p>
    </section>
  );
}

export function SettingsDialog({ onClose, onCompute, onHistoryCleared, busyJobs, version, aiModels }: SettingsDialogProps) {
  const toasts = useToasts();
  const { error: notifyError } = toasts;
  const [settings, setSettings] = useState<AppSettings | null>(null);
  const [probing, setProbing] = useState(false);

  useEffect(() => {
    api.getSettings().then(setSettings, notifyError);
  }, [notifyError]);

  const apply = (s: AppSettings) => {
    setSettings(s);
    onCompute(s.compute);
  };

  const patchCompute = async (body: Parameters<typeof api.patchCompute>[0]) => {
    try {
      const c = await api.patchCompute(body);
      setSettings((prev) => (prev ? { ...prev, compute: c } : prev));
      onCompute(c);
    } catch (err) {
      toasts.error(err);
    }
  };

  const probe = async () => {
    setProbing(true);
    try {
      const c = await api.probeCompute();
      setSettings((prev) => (prev ? { ...prev, compute: c } : prev));
      onCompute(c);
    } catch (err) {
      toasts.error(err);
    } finally {
      setProbing(false);
    }
  };

  const c = settings?.compute;

  return (
    <Modal title="Settings" onClose={onClose} testId="settings-dialog" wide>
      {!settings || !c ? (
        <p className="muted">Loading settings…</p>
      ) : (
        <>
          <section className="settings-section">
            <h3>Processing device</h3>
            <div className="field">
              <label htmlFor="device-select">Processing device</label>
              <select
                id="device-select"
                value={c.preference}
                data-testid="device-select"
                onChange={(e) => void patchCompute({ device: e.target.value as DevicePreference })}
              >
                <option value="auto">Auto</option>
                <option value="gpu">NVIDIA GPU</option>
                <option value="cpu">CPU</option>
              </select>
            </div>
            <p className="small" data-testid="resolved-label"><strong>{c.resolved_label}</strong>{c.note ? ` — ${c.note}` : ''}</p>
            <div className="row">
              <button type="button" className="btn" disabled={probing} onClick={() => void probe()} data-testid="check-gpu">
                {probing ? 'Checking…' : 'Check GPU setup'}
              </button>
            </div>
            <ProbeDetails compute={c} />
            <FractionField id="gpu-fraction" label="GPU memory to use" hint="Share of free GPU memory the app may use (never more than 70%)." value={c.gpu_memory_fraction} min={0.1} max={0.7} onCommit={(v) => void patchCompute({ gpu_memory_fraction: v })} />
            <FractionField id="ram-fraction" label="RAM to use" hint="Share of memory processing may use before work is split into smaller pieces." value={c.ram_fraction} min={0.2} max={0.8} onCommit={(v) => void patchCompute({ ram_fraction: v })} />
            <details className="manage">
              <summary>What runs on the GPU</summary>
              <ul className="small">
                {c.stage_policy.map((s) => (
                  <li key={s.stage}>{s.stage}: {s.gpu_eligible ? 'GPU when available' : (s.backend ?? 'CPU')}</li>
                ))}
              </ul>
              <p className="muted small">Auto uses the GPU for eligible steps on images of {(c.gpu_threshold_pixels / 1e6).toFixed(0)} MP or more.</p>
            </details>
          </section>

          <section className="settings-section">
            <h3>Sharing</h3>
            <label className="check">
              <input
                type="checkbox"
                checked={settings.strip_location}
                data-testid="strip-location"
                onChange={(e) => api.patchSettings({ strip_location: e.target.checked }).then(apply, (err) => toasts.error(err))}
              />
              Remove location/observer details from shared exports
            </label>
            <p className="muted small">Applies to display exports and processed FITS. Your stored copy keeps its full metadata.</p>
          </section>

          <section className="settings-section">
            <h3>Limits</h3>
            <p className="small">Up to {settings.limits.max_files} files per batch, {settings.limits.max_file_mib} MiB per file and {settings.limits.max_megapixels} megapixels per image.</p>
            <p className="muted small">Data folder: {settings.data_dir}</p>
          </section>

          <AIModelsSection models={aiModels} />

          <StorageSection
            keep={settings.keep_runs_per_image}
            onKeep={(n) => api.patchSettings({ keep_runs_per_image: n }).then(apply, (err) => toasts.error(err))}
          />

          <HistorySection busyJobs={busyJobs} onCleared={onHistoryCleared} />

          <section className="settings-section" data-testid="about-section">
            <h3>About</h3>
            <p className="small">
              EasyAstroEnhance <strong data-testid="about-version">{version ? `v${version.version}` : '…'}</strong>
              {version && <span className="muted"> · processing engine {version.version} · recipe schema {version.recipeSchema} · stacking {version.stackVersion}</span>}
            </p>
            <p className="muted small">Each result's processing report records the engine version that made it. If this differs from what you expect, restart the app and reload this page.</p>
          </section>
        </>
      )}
      <div className="modal-actions">
        <button type="button" className="btn" onClick={onClose}>Close</button>
      </div>
    </Modal>
  );
}
