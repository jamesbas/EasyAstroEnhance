import { useCallback, useEffect, useState } from 'react';
import { api } from '../api/client';
import type { AITool, AutoPresetChoice, Preset, Recipe } from '../api/types';
import { cloneRecipe } from '../lib/recipe';

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
}

const lookAndAdvanced = (r: Recipe) => JSON.stringify([r.look, r.advanced]);

// The recipe is shared intent only: it never carries sky regions, label regions or masks (those belong to each asset).
export function useRecipe(onError: (err: unknown) => void): RecipeState {
  const [recipe, setRecipe] = useState<Recipe | null>(null);
  const [presets, setPresets] = useState<Preset[]>([]);

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
        if (first?.recipe) setRecipe({ ...cloneRecipe(first.recipe), preset: first.id });
      },
      onError,
    );
    return () => {
      cancelled = true;
    };
  }, [onError]);

  // Auto keeps choosing the style per image until the user moves a Look slider or an Advanced value; from then on the
  // sliders (which show what Auto chose) are the user's own settings. Other changes keep Auto.
  const edit = useCallback((mutate: (draft: Recipe) => void) => {
    setRecipe((prev) => {
      if (!prev) return prev;
      const next = cloneRecipe(prev);
      mutate(next);
      if (prev.auto_preset && lookAndAdvanced(prev) === lookAndAdvanced(next)) {
        next.auto_preset = true;
        next.preset = 'auto';
      } else {
        next.auto_preset = false;
        next.preset = 'custom';
      }
      return next;
    });
  }, []);

  // Show the look Auto chose for the current image in the sliders (not an input while Auto is on; see normalizeRecipe).
  const adoptAutoChoice = useCallback(
    (choice: AutoPresetChoice | null | undefined) => {
      if (!choice) return;
      const chosen = presets.find((p) => p.id === choice.chosen)?.recipe;
      setRecipe((prev) => {
        if (!prev?.auto_preset) return prev;
        const advanced = { ...prev.advanced, hdr_amount: chosen?.advanced.hdr_amount ?? null, star_stretch_amount: chosen?.advanced.star_stretch_amount ?? null };
        if (JSON.stringify([prev.look, prev.advanced]) === JSON.stringify([choice.look, advanced])) return prev;
        return { ...prev, look: { ...choice.look }, advanced };
      });
    },
    [presets],
  );

  const selectPreset = useCallback(
    (id: string) => {
      if (id === 'custom') {
        setRecipe((prev) => (prev ? { ...prev, preset: 'custom', auto_preset: false } : prev));
        return;
      }
      const p = presets.find((x) => x.id === id);
      // Built-in presets describe a look; the AI tool switches stay as the user set them. Saved presets bring their own.
      if (p?.recipe && p.compatible) {
        const next = p.recipe;
        setRecipe((prev) => ({ ...cloneRecipe(next), preset: p.id, ai: p.builtin && prev ? { ...prev.ai } : { ...next.ai } }));
      }
    },
    [presets],
  );

  const savePreset = useCallback(
    async (name: string) => {
      if (!recipe) throw new Error('Settings are still loading.');
      const created = await api.createPreset(name, recipe);
      await reloadPresets();
      if (created.recipe) setRecipe({ ...cloneRecipe(created.recipe), preset: created.id });
      return created;
    },
    [recipe, reloadPresets],
  );

  const setAI = useCallback((tool: AITool, on: boolean) => {
    setRecipe((prev) => (prev ? { ...prev, ai: { ...prev.ai, [tool]: on } } : prev));
  }, []);

  const resetTo = useCallback((r: Recipe) => setRecipe(cloneRecipe(r)), []);

  return { recipe, presets, presetId: recipe?.preset ?? 'auto', edit, setAI, selectPreset, reloadPresets, savePreset, resetTo, adoptAutoChoice };
}
