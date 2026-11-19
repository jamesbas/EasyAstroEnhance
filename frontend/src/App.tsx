import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { api, uploadAssets } from './api/client';
import type { Asset, Interpretation, Question } from './api/types';
import { ChannelMixDialog, isLinearFits } from './components/ChannelMixDialog';
import { CompareViewer } from './components/CompareViewer';
import { EnhancementPanel } from './components/EnhancementPanel';
import { ExportMenu } from './components/ExportMenu';
import { ImageQueue } from './components/ImageQueue';
import { IntakeDialog } from './components/IntakeDialog';
import { isLabelBand } from './components/LabelRegionTool';
import { Toaster } from './components/Modal';
import { ResultNote } from './components/ResultNote';
import { RunHistory } from './components/RunHistory';
import { SettingsDialog } from './components/SettingsDialog';
import { StackBanner } from './components/StackBanner';
import { StackDialog } from './components/StackDialog';
import { StackInfo } from './components/StackInfo';
import { UploadPanel } from './components/UploadPanel';
import { useBgDrafts } from './hooks/useBgDrafts';
import { useAIModels } from './hooks/useAIModels';
import { useAppVersion } from './hooks/useAppVersion';
import { useCompute } from './hooks/useCompute';
import { useRecipe } from './hooks/useRecipe';
import { useRunDetail, useRunHistory } from './hooks/useRunHistory';
import { useSelection } from './hooks/useSelection';
import { useStarMask } from './hooks/useStarMask';
import { useToasts } from './hooks/useToasts';
import { useWindowDrop } from './hooks/useWindowDrop';
import { assetIsActive, useWorkspace } from './hooks/useWorkspace';
import { STATE_QUESTION } from './lib/intake';
import { recipesDiffer } from './lib/recipe';
import type { Mark, ViewerTool } from './types/ui';

function newKey(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') return crypto.randomUUID();
  return `${Date.now().toString(16)}-${Math.random().toString(16).slice(2)}-${Math.random().toString(16).slice(2)}`;
}

interface ForcedIntake {
  assetId: string;
  question: Question;
}

export default function App() {
  const toasts = useToasts();
  const { notify, error: notifyError } = toasts;
  const ws = useWorkspace();
  const { assets, activeJobs, activeStacks, upsert, refresh, remove } = ws;
  const compute = useCompute();
  const appVersion = useAppVersion();
  const reportError = useCallback((err: unknown) => notifyError(err), [notifyError]);
  const rec = useRecipe(reportError);
  const aiModels = useAIModels(reportError);
  const sel = useSelection(assets);
  const { choose } = sel;
  const drafts = useBgDrafts();
  const { drop: dropDraft } = drafts;

  const [uploading, setUploading] = useState<{ progress: number; count: number } | null>(null);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [stackOpen, setStackOpen] = useState(false);
  const [mixOpen, setMixOpen] = useState(false);
  const [dismissed, setDismissed] = useState<Set<string>>(() => new Set());
  const [forced, setForced] = useState<ForcedIntake | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [hubbleStrength, setHubbleStrength] = useState(0.65);
  const [cancelling, setCancelling] = useState(false);
  const [tool, setTool] = useState<ViewerTool>('none');
  const [labelLineY, setLabelLineY] = useState<number | null>(null);
  const [showClipping, setShowClipping] = useState(false);
  const [fixedMapping, setFixedMapping] = useState(false);
  const [runChoice, setRunChoice] = useState<Record<string, string>>({});
  const [announcement, setAnnouncement] = useState('');

  const primary = useMemo(() => assets.find((a) => a.id === sel.primaryId) ?? null, [assets, sel.primaryId]);
  const star = useStarMask(primary?.id ?? null, reportError);

  // ---- per-image view state resets when the viewed image changes
  useEffect(() => {
    setTool('none');
    setLabelLineY(null);
    setFixedMapping(false);
  }, [primary?.id]);

  // ---- runs
  const latestRun = primary?.latest_run ?? null;
  const runs = useRunHistory(primary?.id ?? null, latestRun?.id ?? null);
  const latestRunId = latestRun?.id ?? null;
  const primaryId = primary?.id ?? null;
  useEffect(() => {
    if (!primaryId) return;
    setRunChoice((prev) => {
      if (!(primaryId in prev)) return prev;
      const next = { ...prev };
      delete next[primaryId];
      return next;
    });
  }, [primaryId, latestRunId]);
  const chosenId = primary ? runChoice[primary.id] : undefined;
  const displayedRun = (chosenId ? runs.find((r) => r.id === chosenId) : undefined) ?? latestRun;
  const runDetail = useRunDetail(displayedRun?.id ?? null);
  const hasFixed = runDetail?.has_fixed_mapping ?? false;
  useEffect(() => {
    if (!hasFixed) setFixedMapping(false);
  }, [hasFixed]);

  // ---- batch scope
  const readySet = useMemo(() => new Set(assets.filter((a) => a.can_process && !assetIsActive(a)).map((a) => a.id)), [assets]);
  const selectedReady = sel.selectedIds.filter((id) => readySet.has(id));
  const batchRunIds = useMemo(() => {
    const pool = sel.selectedIds.length > 1 ? assets.filter((a) => sel.selectedIds.includes(a.id)) : assets;
    return pool.flatMap((a) => (a.latest_run ? [a.latest_run.id] : []));
  }, [assets, sel.selectedIds]);

  const settingsChanged = Boolean(
    rec.recipe && latestRun && primary && !assetIsActive(primary) && recipesDiffer(rec.recipe, latestRun.recipe),
  );

  // ---- announcements & item transitions
  const seenItems = useRef(new Map<string, string>());
  useEffect(() => {
    for (const a of assets) {
      const item = a.latest_item;
      const key = item ? `${item.id}:${item.state}` : '';
      const prev = seenItems.current.get(a.id);
      if (prev !== undefined && prev !== key && item) {
        if (item.state === 'failed') notify('error', `${a.filename}: ${item.error?.message ?? 'Enhancement failed.'}`);
        else if (item.state === 'succeeded' || item.state === 'succeeded_with_notes') setAnnouncement(`Finished enhancing ${a.filename}.`);
        else if (item.state === 'cancelled') setAnnouncement(`Cancelled ${a.filename}.`);
      }
      seenItems.current.set(a.id, key);
    }
  }, [assets, notify]);

  // A stack that leaves the active list has finished: report it and show the new stacked image.
  const seenStacks = useRef(new Set<string>());
  useEffect(() => {
    const now = new Set(activeStacks.map((s) => s.id));
    const gone = [...seenStacks.current].filter((id) => !now.has(id));
    seenStacks.current = now;
    for (const id of gone) {
      void api.getStack(id).then(async (s) => {
        if (s.state === 'succeeded' && s.report) {
          const r = s.report;
          const skipped = r.frames_total - r.frames_used;
          notify('success', `Stacked ${r.frames_used} frame${r.frames_used === 1 ? '' : 's'} of ${s.name}${skipped ? ` (${skipped} poor or unaligned frame${skipped === 1 ? '' : 's'} skipped)` : ''}.${s.auto_enhance ? ' Enhancing now.' : ' Adjust the settings, then Enhance.'}`);
          if (s.asset_id) {
            upsert([await api.getAsset(s.asset_id)]);
            choose([s.asset_id], s.asset_id);
          }
          void refresh();
        } else if (s.state === 'failed') {
          notify('error', `Stacking ${s.name} failed: ${s.error?.message ?? 'unknown error'}`);
        } else if (s.state === 'cancelled') {
          setAnnouncement(`Stacking ${s.name} was cancelled.`);
        }
      }, (err: unknown) => notifyError(err));
    }
  }, [activeStacks, refresh, choose, upsert, notify, notifyError]);

  const cancelStack = useCallback(async (id: string) => {
    try {
      await api.cancelStack(id);
      await refresh();
    } catch (err) {
      notifyError(err);
    }
  }, [refresh, notifyError]);

  const wasOffline = useRef(false);
  useEffect(() => {
    if (ws.offline) wasOffline.current = true;
    else if (wasOffline.current) {
      wasOffline.current = false;
      notify('success', 'Reconnected.');
    }
  }, [ws.offline, notify]);

  useEffect(() => {
    if (ws.activeJobs.length === 0) compute.reload();
  }, [ws.activeJobs.length]); // eslint-disable-line react-hooks/exhaustive-deps

  // ---- uploads
  const handleFiles = useCallback(
    async (files: File[]) => {
      setUploading({ progress: 0, count: files.length });
      try {
        const res = await uploadAssets(files, (p) => setUploading({ progress: p, count: files.length }));
        upsert(res.assets);
        const usable = res.assets.filter((a) => a.status !== 'failed');
        const first = usable[0] ?? res.assets[0];
        if (first) choose(usable.map((a) => a.id), first.id);
        const failed = res.assets.filter((a) => a.status === 'failed');
        if (failed.length > 0) notify('info', `${failed.length} file${failed.length === 1 ? '' : 's'} could not be added. See the queue for details; your other files are unaffected.`);
        setAnnouncement(`Added ${res.assets.length} file${res.assets.length === 1 ? '' : 's'}.`);
        void refresh();
      } catch (err) {
        notifyError(err);
      } finally {
        setUploading(null);
      }
    },
    [upsert, refresh, choose, notify, notifyError],
  );
  const dragging = useWindowDrop(handleFiles);

  // ---- intake
  const intake = useMemo(() => {
    if (forced) {
      const asset = assets.find((a) => a.id === forced.assetId);
      if (asset) return { asset, question: forced.question };
    }
    const pending = assets.filter((a) => a.status === 'needs_input' && a.questions.length > 0 && !dismissed.has(`${a.id}:${a.questions[0].id}`));
    const asset = pending.find((a) => a.id === sel.primaryId) ?? pending[0];
    return asset ? { asset, question: asset.questions[0] } : null;
  }, [assets, forced, dismissed, sel.primaryId]);

  const answerIntake = useCallback(
    async (assetId: string, answer: Interpretation) => {
      try {
        const updated = await api.setInterpretation(assetId, answer);
        upsert([updated]);
        setForced(null);
        void refresh();
      } catch (err) {
        notifyError(err);
      }
    },
    [upsert, refresh, notifyError],
  );

  const reopenIntake = useCallback(
    (assetId: string) => {
      const asset = assets.find((a) => a.id === assetId);
      if (!asset) return;
      const question = asset.questions[0] ?? STATE_QUESTION;
      setDismissed((prev) => {
        const next = new Set(prev);
        next.delete(`${asset.id}:${question.id}`);
        return next;
      });
      setForced({ assetId, question });
    },
    [assets],
  );

  const laterIntake = useCallback(() => {
    if (!intake) return;
    setDismissed((prev) => new Set(prev).add(`${intake.asset.id}:${intake.question.id}`));
    setForced(null);
  }, [intake]);

  // ---- asset actions
  const removeAsset = useCallback(
    async (id: string) => {
      try {
        const res = await api.deleteAsset(id);
        remove(id);
        dropDraft(id);
        notify('info', res.note);
      } catch (err) {
        notifyError(err);
      }
    },
    [remove, dropDraft, notify, notifyError],
  );

  const onAssetUpdated = useCallback((a: Asset) => upsert([a]), [upsert]);

  // ---- jobs
  const submit = useCallback(
    async (ids: string[], force: boolean, hubble = 0) => {
      if (!rec.recipe || ids.length === 0) return;
      setSubmitting(true);
      try {
        const recipe = hubble > 0 ? { ...rec.recipe, preset: 'custom', hubble_strength: hubble } : rec.recipe;
        const job = await api.createJob({
          request_key: newKey(),
          asset_ids: ids,
          recipe,
          preset_id: recipe.preset === 'custom' ? null : recipe.preset,
          force,
        });
        for (const s of job.skipped) notify('info', `${s.filename ? `${s.filename}: ` : ''}${s.message}`);
        setAnnouncement(`Started enhancing ${job.items.length} image${job.items.length === 1 ? '' : 's'}.`);
        await refresh();
      } catch (err) {
        notifyError(err);
        void refresh();
      } finally {
        setSubmitting(false);
      }
    },
    [rec.recipe, refresh, notify, notifyError],
  );

  // Manual retry: the item payload has no job id, so find the job that holds the item; fall back to a forced new job.
  const retryAsset = useCallback(
    async (assetId: string) => {
      const asset = assets.find((a) => a.id === assetId);
      const item = asset?.latest_item;
      if (!asset || !item) return;
      setSubmitting(true);
      try {
        const job = (await api.listJobs(false)).jobs.find((j) => j.items.some((i) => i.id === item.id));
        if (job) {
          await api.retryJob(job.id);
        } else if (rec.recipe) {
          await api.createJob({ request_key: newKey(), asset_ids: [assetId], recipe: rec.recipe, preset_id: null, force: true });
        }
        setAnnouncement(`Retrying ${asset.filename}.`);
        await refresh();
      } catch (err) {
        notifyError(err);
      } finally {
        setSubmitting(false);
      }
    },
    [assets, rec.recipe, refresh, notifyError],
  );

  const cancelJobs = useCallback(async () => {
    setCancelling(true);
    try {
      await Promise.all(activeJobs.map((j) => api.cancelJob(j.id)));
      setAnnouncement('Cancel requested.');
      await refresh();
    } catch (err) {
      notifyError(err);
    } finally {
      setCancelling(false);
    }
  }, [activeJobs, refresh, notifyError]);

  // ---- viewer marks (background samples / label band)
  const draft = primary ? drafts.draftFor(primary) : null;
  const marks: Mark[] = useMemo(() => {
    if (!primary || !draft) return [];
    const out: Mark[] = draft.samples.map((s, i) => ({ rect: s.rect, kind: s.excluded ? 'excluded' : 'sample', label: String(i + 1) }));
    for (const r of draft.suggestions) out.push({ rect: r, kind: 'suggested' });
    for (const r of primary.regions) if (!isLabelBand(r, primary)) out.push({ rect: r, kind: 'region' });
    return out;
  }, [primary, draft]);

  const onRectDrawn = useCallback(
    (rect: { x: number; y: number; w: number; h: number }) => {
      if (primary) drafts.patch(primary, (d) => ({ ...d, samples: [...d.samples, { rect, excluded: false }] }));
    },
    [primary, drafts],
  );

  const busyJobs = ws.activeJobs.length > 0;
  const hasAssets = assets.length > 0;

  return (
    <div className="app">
      <header className="topbar">
        {hasAssets ? <h1 className="brand">EasyAstroEnhance</h1> : <span />}
        <div className="topbar-actions">
          {hasAssets && <UploadPanel variant="compact" onFiles={(f) => void handleFiles(f)} uploading={uploading !== null} />}
          {hasAssets && <button type="button" className="btn" onClick={() => setStackOpen(true)} data-testid="stack-button">Stack frames…</button>}
          {assets.filter(isLinearFits).length >= 2 && <button type="button" className="btn" onClick={() => setMixOpen(true)}>Combine channels…</button>}
          {appVersion && (
            <span className="version-chip" data-testid="app-version" title={`EasyAstroEnhance version ${appVersion.version} (processing engine; recipe schema ${appVersion.recipeSchema}; stacking ${appVersion.stackVersion})`}>
              v{appVersion.version}
            </span>
          )}
          <button type="button" className="chip" onClick={() => setSettingsOpen(true)} data-testid="processing-chip" title="Processing device">
            {compute.compute?.resolved_label ?? 'Processing: checking…'}
          </button>
          <button type="button" className="icon-btn gear" onClick={() => setSettingsOpen(true)} aria-label="Settings" data-testid="settings-button">
            <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
              <circle cx="12" cy="12" r="3" />
              <path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3h0a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5h0a1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8v0a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z" />
            </svg>
          </button>
        </div>
      </header>

      {ws.offline && (
        <div className="banner error" role="alert" data-testid="offline-banner">
          <span>{ws.offline}</span>
          <button type="button" className="btn small" onClick={() => void refresh()}>Try again</button>
        </div>
      )}

      <StackBanner stacks={activeStacks} onCancel={(id) => void cancelStack(id)} />

      {uploading && (
        <div className="upload-progress" role="status" data-testid="upload-progress">
          <span>
            {uploading.progress >= 1 ? 'Reading files…' : `Uploading ${uploading.count} file${uploading.count === 1 ? '' : 's'}… ${Math.round(uploading.progress * 100)}%`}
          </span>
          <progress max={1} value={uploading.progress >= 1 ? undefined : uploading.progress} aria-label="Upload progress" />
        </div>
      )}

      <main className="main">
        {!hasAssets ? (
          ws.loaded ? <UploadPanel variant="empty" onFiles={(f) => void handleFiles(f)} uploading={uploading !== null} onStack={() => setStackOpen(true)} /> : <p className="muted pad">Loading…</p>
        ) : (
          <div className="workspace">
            <ImageQueue
              assets={assets}
              selectedIds={sel.selectedIds}
              primaryId={sel.primaryId}
              recipe={rec.recipe}
              onSelect={sel.select}
              onToggle={sel.toggle}
              onRemove={removeAsset}
              onAnswer={reopenIntake}
              onRetry={(id) => void retryAsset(id)}
              retryBusy={submitting}
            />
            <section className="center" aria-label="Viewer">
              {primary && primary.preview_url && primary.width && primary.height ? (
                <>
                  <CompareViewer
                    key={`${primary.id}:${primary.width}x${primary.height}`}
                    asset={primary}
                    run={displayedRun}
                    hasFixedMapping={hasFixed}
                    tool={tool}
                    onToolDone={() => { setTool('none'); setLabelLineY(null); }}
                    marks={marks}
                    onRectDrawn={onRectDrawn}
                    labelLineY={labelLineY}
                    onLabelLine={setLabelLineY}
                    showClipping={showClipping}
                    onShowClipping={setShowClipping}
                    fixedMapping={fixedMapping}
                    onFixedMapping={setFixedMapping}
                    starOverlayUrl={star.overlayUrl}
                  />
                  <div className="under-viewer">
                    <RunHistory runs={runs} currentId={displayedRun?.id ?? null} onSelect={(id) => setRunChoice((prev) => ({ ...prev, [primary.id]: id }))} />
                    <ExportMenu run={displayedRun} batchRunIds={batchRunIds} onError={reportError} />
                  </div>
                  <ResultNote asset={primary} run={displayedRun} />
                  <StackInfo asset={primary} />
                  {primary.status === 'needs_input' && (
                    <div className="callout" data-testid="preview-only-note">
                      <strong>Preview only.</strong> {primary.intake_message ?? 'Confirm how this image was saved to enable enhancing.'}{' '}
                      <button type="button" className="btn small" onClick={() => reopenIntake(primary.id)}>How was this image saved?</button>
                    </div>
                  )}
                </>
              ) : (
                <div className="viewer-empty" data-testid="viewer-empty">
                  {!primary ? <p>Select an image to see it here.</p> : primary.status === 'failed' ? (
                    <><p className="err-text"><strong>{primary.filename}</strong> could not be used.</p><p>{primary.error?.message ?? 'This file could not be read.'}</p></>
                  ) : primary.status === 'needs_input' ? (
                    <><p>This image needs one answer before a preview can be shown.</p><button type="button" className="btn primary" onClick={() => reopenIntake(primary.id)}>Answer question</button></>
                  ) : (
                    <p>Preparing a preview of {primary.filename}…</p>
                  )}
                </div>
              )}
            </section>
            <EnhancementPanel
              recipe={rec.recipe}
              presets={rec.presets}
              presetId={rec.presetId}
              edit={rec.edit}
              setAI={rec.setAI}
              aiModels={aiModels}
              selectPreset={rec.selectPreset}
              savePreset={async (name) => { await rec.savePreset(name); notify('success', `Saved preset “${name}”.`); }}
              reloadPresets={async () => { await rec.reloadPresets(); }}
              asset={primary}
              assets={assets}
              selectedReady={selectedReady.length}
              allReady={readySet.size}
              submitting={submitting}
              settingsChanged={settingsChanged}
              onEnhanceSelected={() => void submit(selectedReady, false)}
              hubbleStrength={hubbleStrength}
              onHubbleStrength={setHubbleStrength}
              onEnhanceHubble={primary?.hubble_input === 'dualband' && readySet.has(primary.id)
                ? () => void submit([primary.id], false, hubbleStrength) : undefined}
              onEnhanceAll={() => void submit([...readySet], false)}
              onReprocess={() => primary && void submit([primary.id], true)}
              jobs={ws.activeJobs}
              cancelling={cancelling}
              onCancel={() => void cancelJobs()}
              bgDraft={draft}
              patchBgDraft={(fn) => primary && drafts.patch(primary, fn)}
              tool={tool}
              onTool={setTool}
              labelLineY={labelLineY}
              onLabelLine={setLabelLineY}
              star={{ on: star.on, loading: star.loading, result: star.result, onToggle: star.toggle }}
              onChangeState={() => primary && reopenIntake(primary.id)}
              onAssetUpdated={onAssetUpdated}
            />
          </div>
        )}
      </main>

      {intake && (
        <IntakeDialog
          key={`${intake.asset.id}:${intake.question.id}`}
          asset={intake.asset}
          question={intake.question}
          onAnswer={answerIntake}
          onLater={laterIntake}
        />
      )}
      {settingsOpen && (
        <SettingsDialog
          onClose={() => setSettingsOpen(false)}
          onCompute={compute.setCompute}
          version={appVersion}
          aiModels={aiModels}
          busyJobs={busyJobs}
          onHistoryCleared={() => { void refresh(); setSettingsOpen(false); }}
        />
      )}
      {stackOpen && (
        <StackDialog
          recipe={rec.recipe}
          presetId={rec.recipe && rec.recipe.preset !== 'custom' ? rec.recipe.preset : null}
          settingsLabel={rec.presets.find((p) => p.id === rec.presetId)?.name ?? 'custom settings'}
          newKey={newKey}
          onClose={() => setStackOpen(false)}
          onStarted={(s) => {
            setStackOpen(false);
            setAnnouncement(`Started stacking ${s.name}.`);
            void refresh();
          }}
        />
      )}
      {mixOpen && (
        <ChannelMixDialog assets={assets} onClose={() => setMixOpen(false)} onCreated={(asset) => {
          upsert([asset]);
          choose([asset.id], asset.id);
          setMixOpen(false);
          notify('success', 'Color master created. Select a preset and Enhance when ready.');
          void refresh();
        }} />
      )}
      {dragging && hasAssets && <div className="drop-overlay" aria-hidden="true"><p>Drop to add photos</p></div>}
      <Toaster />
      <div className="visually-hidden" role="status" aria-live="polite" data-testid="announcer">{announcement}</div>
    </div>
  );
}
