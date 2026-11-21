import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../api/client';
import type { AITool, AutoPresetChoice, Preset, Recipe } from '../api/types';
import { cloneRecipe } from '../lib/recipe';
import { REMOVABLE_STEPS } from '../lib/steps';

export interface RecipeState {
  recipe: Recipe | null;
  presets: Preset[];
  presetId: string;
  edit: (mutate: (draft: Recipe) => void) => void;
  setAI: (tool: AITool, on: boolean) => void;
  selectPreset: (id: string) => void;
  reloadPresets: () => Promise<Preset[]>;
  savePreset: (name: string) => Promise<Preset>;
  resetTo: (recipe: Recipe) => void;
  adoptAutoChoice: (choice: AutoPresetChoice | null | undefined) => void;
  /** turn off one step a result applied (see lib/steps.ts); false when there was nothing to turn off */
  removeStep: (name: string) => boolean;
  /** the app's defaults: the Auto preset with every optional tool off */
  resetDefaults: () => void;
  undo: () => void;
  redo: () => void;
  canUndo: boolean;
  canRedo: boolean;
}

const lookAndAdvanced = (r: Recipe) => JSON.stringify([r.look, r.advanced]);
const HISTORY_LIMIT = 100;
const COALESCE_MS = 700; // a slider drag (many edits in a row) is one undo step

interface History {
  past: Recipe[];
  future: Recipe[];
  lastEdit: number;
}

// Auto keeps choosing the style per image until the user moves a Look slider or an Advanced value; from then on the
// sliders (which show what Auto chose) are the user's own settings. Other changes keep Auto.
function withAutoRule(prev: Recipe, next: Recipe): Recipe {
  if (prev.auto_preset && lookAndAdvanced(prev) === lookAndAdvanced(next)) {
    next.auto_preset = true;
    next.preset = 'auto';
  } else {
    next.auto_preset = false;
    next.preset = 'custom';
  }
  return next;
}

// The recipe is shared intent only: it never carries sky regions, label regions or masks (those belong to each asset).
// Undo/Redo keeps a separate history for each image (``historyKey``): the changes made while that image was selected.
export function useRecipe(onError: (err: unknown) => void, historyKey: string = ''): RecipeState {
  const [recipe, setRecipeState] = useState<Recipe | null>(null);
  const [presets, setPresets] = useState<Preset[]>([]);
  const [, setHistoryVersion] = useState(0);
  const recipeRef = useRef<Recipe | null>(null);
  const histories = useRef(new Map<string, History>());
  const keyRef = useRef(historyKey);
  keyRef.current = historyKey;

  const history = useCallback((): History => {
    let h = histories.current.get(keyRef.current);
    if (!h) {
      h = { past: [], future: [], lastEdit: 0 };
      histories.current.set(keyRef.current, h);
    }
    return h;
  }, []);

  // Every settings change goes through here. ``mode``: record an undo step, extend the current one (slider drags), or
  // not record (loading, and showing the look Auto chose).
  const commit = useCallback((next: Recipe | null, mode: 'record' | 'coalesce' | 'none') => {
    const prev = recipeRef.current;
    if (prev && next && JSON.stringify(prev) === JSON.stringify(next)) return;
    if (mode !== 'none' && prev) {
      const h = history();
      const t = Date.now();
      if (!(mode === 'coalesce' && t - h.lastEdit < COALESCE_MS)) {
        h.past.push(prev);
        if (h.past.length > HISTORY_LIMIT) h.past.shift();
      }
      h.future = [];
      h.lastEdit = mode === 'coalesce' ? t : 0;
      setHistoryVersion((v) => v + 1);
    }
    recipeRef.current = next;
    setRecipeState(next);
  }, [history]);

  const reloadPresets = useCallback(async () => {
    const list = (await api.listPresets()).presets;
    setPresets(list);
    return list;
  }, []);

  useEffect(() => {
    let cancelled = false;
    api.listPresets().then(
      ({ presets: list }) => {
        if (cancelled) return;
        setPresets(list);
        const first = list.find((p) => p.id === 'auto' && p.recipe) ?? list.find((p) => p.id === 'natural' && p.recipe)
          ?? list.find((p) => p.compatible && p.recipe);
        if (first?.recipe) commit({ ...cloneRecipe(first.recipe), preset: first.id }, 'none');
      },
      onError,
    );
    return () => {
      cancelled = true;
    };
  }, [onError, commit]);

  const edit = useCallback((mutate: (draft: Recipe) => void) => {
    const prev = recipeRef.current;
    if (!prev) return;
    const next = cloneRecipe(prev);
    mutate(next);
    commit(withAutoRule(prev, next), 'coalesce');
  }, [commit]);

  // Show the look Auto chose for the current image in the sliders (not an input while Auto is on; see normalizeRecipe).
  const adoptAutoChoice = useCallback(
    (choice: AutoPresetChoice | null | undefined) => {
      const prev = recipeRef.current;
      if (!choice || !prev?.auto_preset) return;
      const chosen = presets.find((p) => p.id === choice.chosen)?.recipe;
      const advanced = { ...prev.advanced, hdr_amount: chosen?.advanced.hdr_amount ?? null, star_stretch_amount: chosen?.advanced.star_stretch_amount ?? null };
      if (JSON.stringify([prev.look, prev.advanced]) === JSON.stringify([choice.look, advanced])) return;
      commit({ ...prev, look: { ...choice.look }, advanced }, 'none');
    },
    [presets, commit],
  );

  const selectPreset = useCallback(
    (id: string) => {
      const prev = recipeRef.current;
      if (id === 'custom') {
        if (prev) commit({ ...prev, preset: 'custom', auto_preset: false }, 'record');
        return;
      }
      const p = presets.find((x) => x.id === id);
      // Built-in presets describe a look; the AI tool switches stay as the user set them. Saved presets bring their own.
      if (p?.recipe && p.compatible) {
        const next = p.recipe;
        commit({ ...cloneRecipe(next), preset: p.id, ai: p.builtin && prev ? { ...prev.ai } : { ...next.ai } }, 'record');
      }
    },
    [presets, commit],
  );

  const savePreset = useCallback(
    async (name: string) => {
      if (!recipe) throw new Error('Settings are still loading.');
      const created = await api.createPreset(name, recipe);
      await reloadPresets();
      if (created.recipe) commit({ ...cloneRecipe(created.recipe), preset: created.id }, 'none');
      return created;
    },
    [recipe, reloadPresets, commit],
  );

  const setAI = useCallback((tool: AITool, on: boolean) => {
    const prev = recipeRef.current;
    if (prev) commit({ ...prev, ai: { ...prev.ai, [tool]: on } }, 'record');
  }, [commit]);

  const resetTo = useCallback((r: Recipe) => commit(cloneRecipe(r), 'record'), [commit]);

  const removeStep = useCallback((name: string) => {
    const step = REMOVABLE_STEPS[name];
    const prev = recipeRef.current;
    if (!step || !prev || step.isOff(prev)) return false;
    const next = cloneRecipe(prev);
    step.off(next);
    commit(withAutoRule(prev, next), 'record');
    return true;
  }, [commit]);

  const resetDefaults = useCallback(() => {
    const auto = presets.find((p) => p.id === 'auto' && p.recipe);
    if (auto?.recipe) commit({ ...cloneRecipe(auto.recipe), preset: 'auto' }, 'record');
  }, [presets, commit]);

  const undo = useCallback(() => {
    const h = history();
    const cur = recipeRef.current;
    const prev = h.past.pop();
    if (!prev || !cur) return;
    h.future.push(cur);
    h.lastEdit = 0;
    recipeRef.current = prev;
    setRecipeState(prev);
    setHistoryVersion((v) => v + 1);
  }, [history]);

  const redo = useCallback(() => {
    const h = history();
    const cur = recipeRef.current;
    const next = h.future.pop();
    if (!next || !cur) return;
    h.past.push(cur);
    h.lastEdit = 0;
    recipeRef.current = next;
    setRecipeState(next);
    setHistoryVersion((v) => v + 1);
  }, [history]);

  const h = histories.current.get(historyKey);
  return {
    recipe, presets, presetId: recipe?.preset ?? 'auto', edit, setAI, selectPreset, reloadPresets, savePreset, resetTo, adoptAutoChoice,
    removeStep, resetDefaults, undo, redo, canUndo: Boolean(h?.past.length), canRedo: Boolean(h?.future.length),
  };
}
